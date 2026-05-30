#!/usr/bin/env python3
"""
Eggshell GPU Validation + Diagnostics + Performance Confirmation System
eggshell-gpu-benchmark layer — v1.0.0

Usage:
    gpu-benchmark                   # full validation + 30 s stress test
    gpu-benchmark --no-stress       # skip stress test
    gpu-benchmark --no-ollama       # skip Ollama check
    gpu-benchmark --stress-duration 60
    gpu-benchmark --json            # output JSON to stdout
    gpu-benchmark --no-save         # skip JSON report file
"""

from __future__ import annotations

import argparse
import ctypes
import datetime
import json
import os
import platform
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

# CUDA 12.x runtime rejects CUDA_VISIBLE_DEVICES="all" (requires numeric indices
# or unset). Normalize here before any CUDA library is loaded.
_cvd = os.environ.get("CUDA_VISIBLE_DEVICES", "")
if _cvd.lower() == "all":
    os.environ.pop("CUDA_VISIBLE_DEVICES")

console = Console()

VERSION    = "1.0.0"
REPORT_DIR = Path(os.environ.get("EGGSHELL_REPORTS", "/eggshell/reports"))
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class GpuInfo:
    index: int
    name: str
    vram_total_mb: int
    vram_used_mb: int
    vram_free_mb: int
    utilization_gpu: int
    utilization_memory: int
    temperature_c: int
    power_draw_w: float
    power_limit_w: float
    compute_capability: str
    driver_version: str
    cuda_version_str: str
    pcie_gen: int = 0
    pcie_width: int = 0


@dataclass
class Check:
    name: str
    passed: bool
    value: str
    detail: str = ""


@dataclass
class BenchResult:
    name: str
    passed: bool
    gpu_ms: float
    cpu_ms: float
    speedup: float
    metric: str = ""
    notes: str = ""


@dataclass
class StressResult:
    duration_sec: float
    avg_util: float
    max_util: float
    min_util: float
    avg_temp: float
    max_temp: float
    avg_power_w: float
    throttled: bool
    samples: list = field(default_factory=list)
    notes: str = ""


@dataclass
class OllamaResult:
    reachable: bool
    models_loaded: list
    gpu_confirmed: bool
    vram_used_mb: int
    util_during_inference: float
    inference_ms: float
    notes: str = ""


@dataclass
class Scores:
    gpu_utilization: int = 0
    cuda_health: int = 0
    inference_acceleration: int = 0
    vram_efficiency: int = 0
    container_compatibility: int = 0
    overall: int = 0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(cmd: str, timeout: int = 10) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return -1, str(e)


def _find_cuda_lib() -> Optional[str]:
    candidates = [
        "/usr/local/cuda/lib64/libcuda.so.1",
        "/usr/lib/x86_64-linux-gnu/libcuda.so.1",
        "/usr/lib/aarch64-linux-gnu/libcuda.so.1",
        "/usr/lib/libcuda.so.1",
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    rc, out = _run("ldconfig -p 2>/dev/null | grep 'libcuda.so.1'")
    if rc == 0 and "=>" in out:
        return out.split("=>")[-1].strip().split("\n")[0].strip()
    # ctypes fallback
    try:
        ctypes.CDLL("libcuda.so.1")
        return "libcuda.so.1 (via ldconfig)"
    except Exception:
        return None


def _in_docker() -> bool:
    return os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv")


def _ok(passed: bool) -> str:
    return "[green]PASS[/green]" if passed else "[red]FAIL[/red]"


def _sample_gpu_util_single() -> float:
    """Single pynvml sample — average across all GPUs."""
    try:
        import pynvml
        pynvml.nvmlInit()
        n = pynvml.nvmlDeviceGetCount()
        utils = [pynvml.nvmlDeviceGetUtilizationRates(
            pynvml.nvmlDeviceGetHandleByIndex(i)).gpu for i in range(n)]
        pynvml.nvmlShutdown()
        return sum(utils) / len(utils) if utils else 0.0
    except Exception:
        return 0.0


# ── Phase 1: Environment ──────────────────────────────────────────────────────

def scan_environment() -> dict:
    env: dict = {
        "timestamp": datetime.datetime.now().isoformat(),
        "hostname": platform.node(),
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "in_docker": _in_docker(),
        "NVIDIA_VISIBLE_DEVICES": os.environ.get("NVIDIA_VISIBLE_DEVICES", "NOT SET"),
        "NVIDIA_DRIVER_CAPABILITIES": os.environ.get("NVIDIA_DRIVER_CAPABILITIES", "NOT SET"),
        "CUDA_VISIBLE_DEVICES": os.environ.get("CUDA_VISIBLE_DEVICES", "NOT SET"),
    }
    rc, out = _run("nvidia-smi --query-gpu=name --format=csv,noheader")
    env["nvidia_smi"] = out[:80] if rc == 0 else "NOT FOUND"
    rc, out = _run("nvcc --version")
    env["nvcc"] = out.split("release")[-1].strip()[:30] if rc == 0 else "NOT FOUND"
    return env


# ── Phase 2: GPU inventory ────────────────────────────────────────────────────

def scan_gpus() -> list[GpuInfo]:
    try:
        import pynvml
        pynvml.nvmlInit()
    except Exception as e:
        console.print(f"[red]pynvml init failed:[/red] {e}")
        return []

    gpus: list[GpuInfo] = []
    try:
        count  = pynvml.nvmlDeviceGetCount()
        driver = pynvml.nvmlSystemGetDriverVersion()
        try:
            cv = pynvml.nvmlSystemGetCudaDriverVersion_v2()
            cuda_str = f"{cv // 1000}.{(cv % 1000) // 10}"
        except Exception:
            cuda_str = "unknown"

        for i in range(count):
            h    = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(h)
            mem  = pynvml.nvmlDeviceGetMemoryInfo(h)
            util = pynvml.nvmlDeviceGetUtilizationRates(h)
            temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            try:
                power = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0
            except Exception:
                power = 0.0
            try:
                plimit = pynvml.nvmlDeviceGetPowerManagementLimit(h) / 1000.0
            except Exception:
                plimit = 0.0
            major, minor = pynvml.nvmlDeviceGetCudaComputeCapability(h)
            try:
                pcie_gen = pynvml.nvmlDeviceGetCurrPcieLinkGeneration(h)
                pcie_w   = pynvml.nvmlDeviceGetCurrPcieLinkWidth(h)
            except Exception:
                pcie_gen = pcie_w = 0

            gpus.append(GpuInfo(
                index=i, name=name,
                vram_total_mb=mem.total >> 20,
                vram_used_mb=mem.used   >> 20,
                vram_free_mb=mem.free   >> 20,
                utilization_gpu=util.gpu,
                utilization_memory=util.memory,
                temperature_c=temp,
                power_draw_w=power,
                power_limit_w=plimit,
                compute_capability=f"{major}.{minor}",
                driver_version=driver,
                cuda_version_str=cuda_str,
                pcie_gen=pcie_gen,
                pcie_width=pcie_w,
            ))
    finally:
        pynvml.nvmlShutdown()
    return gpus


# ── Phase 3: Docker / container runtime validation ────────────────────────────

def validate_docker_runtime() -> list[Check]:
    checks: list[Check] = []

    val = os.environ.get("NVIDIA_VISIBLE_DEVICES", "")
    # "void" is set by nvidia-container-toolkit when --gpus all is used at the
    # Docker runtime level; the actual GPU access is confirmed by /dev/nvidia* nodes.
    devs_present = bool([d for d in os.listdir("/dev") if d.startswith("nvidia")]
                        if os.path.exists("/dev") else [])
    ok = bool(val) and (val not in ("",) and (val != "void" or devs_present))
    checks.append(Check(
        "NVIDIA_VISIBLE_DEVICES", ok, val or "NOT SET",
        "Set via --gpus all or NVIDIA_VISIBLE_DEVICES=all",
    ))

    val = os.environ.get("NVIDIA_DRIVER_CAPABILITIES", "")
    ok  = "compute" in val
    checks.append(Check(
        "NVIDIA_DRIVER_CAPABILITIES includes 'compute'", ok, val or "NOT SET",
        "Required for CUDA workloads inside containers",
    ))

    try:
        devs = sorted(d for d in os.listdir("/dev") if d.startswith("nvidia"))
    except Exception:
        devs = []
    checks.append(Check(
        "/dev/nvidia* device files", bool(devs),
        ", ".join(devs[:6]) or "NONE",
        "NVIDIA device nodes bind-mounted by nvidia-container-toolkit",
    ))

    lib = _find_cuda_lib()
    checks.append(Check(
        "libcuda.so.1 accessible", lib is not None,
        lib or "NOT FOUND",
        "CUDA runtime library required for GPU compute",
    ))

    rc, out = _run("nvidia-smi --query-gpu=name --format=csv,noheader")
    checks.append(Check(
        "nvidia-smi available", rc == 0,
        out[:60] if rc == 0 else "NOT FOUND",
        "Bind-mounted from host by nvidia-container-toolkit",
    ))

    checks.append(Check(
        "Running inside container", _in_docker(),
        "YES" if _in_docker() else "NO",
        "Benchmark is designed for containerised deployment",
    ))

    return checks


# ── Phase 4: CUDA validation ──────────────────────────────────────────────────

def validate_cuda() -> list[Check]:
    checks: list[Check] = []

    try:
        import pynvml
        pynvml.nvmlInit()
        count = pynvml.nvmlDeviceGetCount()
        pynvml.nvmlShutdown()
        checks.append(Check("pynvml / NVML", True, f"{count} GPU(s) detected", ""))
    except Exception as e:
        checks.append(Check(
            "pynvml / NVML", False, str(e)[:60],
            "Install pynvml or verify NVIDIA driver is loaded",
        ))

    try:
        import cupy as cp
        dev = cp.cuda.Device(0)
        dev.use()
        cc  = dev.compute_capability
        cc_str = f"sm_{cc}"
        checks.append(Check(
            "cupy (GPU compute)", True, cc_str,
            "Required for GPU kernel benchmarks",
        ))
        checks.append(Check(
            "CUDA compute capability", True, f"sm_{cc}",
            "sm_35+ required for GPU compute; sm_70+ for Tensor Cores",
        ))
    except Exception as e:
        checks.append(Check(
            "cupy (GPU compute)", False, str(e)[:60],
            "cupy-cuda12x not installed or CUDA driver unavailable",
        ))

    lib = _find_cuda_lib()
    checks.append(Check(
        "CUDA runtime library", lib is not None,
        lib or "NOT FOUND",
        "libcuda.so.1 must be loadable",
    ))

    rc, out = _run("nvcc --version")
    checks.append(Check(
        "CUDA toolkit (nvcc)", rc == 0,
        out.split("release")[-1].strip()[:40] if rc == 0 else "NOT FOUND",
        "Optional — needed to recompile CUDA kernels",
    ))

    return checks


# ── Phase 5: Tensor benchmarks ────────────────────────────────────────────────

def benchmark_elementwise_fma() -> BenchResult:
    """Sustained SGEMM throughput: 20 × 2048² cuBLAS matmul vs numpy.dot."""
    name = "sgemm_throughput_2048"
    try:
        import cupy as cp
        import numpy as np

        N     = 2048
        ITERS = 20

        A = np.random.random((N, N)).astype(np.float32)
        B = np.random.random((N, N)).astype(np.float32)
        d_A = cp.asarray(A)
        d_B = cp.asarray(B)

        # warmup
        _ = cp.matmul(d_A, d_B)
        cp.cuda.Stream.null.synchronize()

        t0 = time.perf_counter()
        for _ in range(ITERS):
            _C = cp.matmul(d_A, d_B)
        cp.cuda.Stream.null.synchronize()
        gpu_ms = (time.perf_counter() - t0) * 1000 / ITERS

        t0 = time.perf_counter()
        for _ in range(ITERS):
            _ = np.dot(A, B)
        cpu_ms = (time.perf_counter() - t0) * 1000 / ITERS

        speedup = cpu_ms / gpu_ms if gpu_ms > 0 else 0.0
        tflops  = (2 * N ** 3) / (gpu_ms / 1000) / 1e12

        return BenchResult(name, True, gpu_ms, cpu_ms, speedup,
                           metric=f"{tflops:.2f} TFLOPS (cuBLAS SGEMM)")
    except Exception as e:
        return BenchResult(name, False, 0, 0, 0, notes=str(e)[:80])


def benchmark_vram_bandwidth() -> BenchResult:
    """Host ↔ Device PCIe bandwidth using 512 MB float32 transfer."""
    name = "vram_bandwidth_512MB"
    try:
        import cupy as cp
        import numpy as np

        MB    = 512
        n     = MB * 1024 * 1024 // 4
        data  = np.random.random(n).astype(np.float32)
        ITERS = 4

        t0 = time.perf_counter()
        for _ in range(ITERS):
            d = cp.asarray(data)
            cp.cuda.Stream.null.synchronize()
        h2d = (MB * ITERS / 1024) / (time.perf_counter() - t0)   # GB/s

        t0 = time.perf_counter()
        for _ in range(ITERS):
            _ = cp.asnumpy(d)
        d2h = (MB * ITERS / 1024) / (time.perf_counter() - t0)

        bidi = (h2d + d2h) / 2

        t0 = time.perf_counter()
        for _ in range(ITERS):
            _ = data.copy()
        cpu_bw = (MB * ITERS / 1024) / (time.perf_counter() - t0)

        speedup = bidi / cpu_bw if cpu_bw > 0 else 0.0
        gpu_ms  = (MB / 1024) / bidi   * 1000 if bidi   > 0 else 0
        cpu_ms  = (MB / 1024) / cpu_bw * 1000 if cpu_bw > 0 else 0

        return BenchResult(
            name, True, gpu_ms, cpu_ms, speedup,
            metric=f"H→D {h2d:.1f} GB/s | D→H {d2h:.1f} GB/s",
        )
    except Exception as e:
        return BenchResult(name, False, 0, 0, 0, notes=str(e)[:80])


def benchmark_matmul_1024() -> BenchResult:
    """1024×1024 float32 matrix multiply: cupy cuBLAS vs numpy.dot."""
    name = "matmul_float32_1024x1024"
    try:
        import cupy as cp
        import numpy as np

        N     = 1024
        ITERS = 5

        A = np.random.random((N, N)).astype(np.float32)
        B = np.random.random((N, N)).astype(np.float32)

        d_A = cp.asarray(A)
        d_B = cp.asarray(B)

        # warmup
        _ = cp.matmul(d_A, d_B)
        cp.cuda.Stream.null.synchronize()

        t0 = time.perf_counter()
        for _ in range(ITERS):
            _C = cp.matmul(d_A, d_B)
        cp.cuda.Stream.null.synchronize()
        gpu_ms = (time.perf_counter() - t0) * 1000 / ITERS

        t0 = time.perf_counter()
        for _ in range(ITERS):
            _ = np.dot(A, B)
        cpu_ms = (time.perf_counter() - t0) * 1000 / ITERS

        speedup = cpu_ms / gpu_ms if gpu_ms > 0 else 0.0
        gflops  = (2 * N ** 3) / (gpu_ms / 1000) / 1e9

        return BenchResult(name, True, gpu_ms, cpu_ms, speedup,
                           metric=f"{gflops:.1f} GFLOPS (cuBLAS)")
    except Exception as e:
        return BenchResult(name, False, 0, 0, 0, notes=str(e)[:80])


# ── Phase 6: Ollama GPU validation ───────────────────────────────────────────

def validate_ollama_gpu() -> OllamaResult:
    try:
        import requests as _req
    except ImportError:
        return OllamaResult(False, [], False, 0, 0, 0, notes="requests not installed")

    try:
        r = _req.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        r.raise_for_status()
        model_names = [m.get("name", "?") for m in r.json().get("models", [])]
    except Exception as e:
        return OllamaResult(False, [], False, 0, 0, 0,
                            notes=f"unreachable: {e}"[:80])

    if not model_names:
        return OllamaResult(True, [], False, 0, 0, 0,
                            notes="Ollama reachable but no models installed")

    # Prefer a small model for the latency test
    test_model = next(
        (m for m in model_names
         if any(x in m.lower() for x in ["0.5b", "0.6b", "1b", "tiny"])),
        model_names[0],
    )

    # Sample GPU utilisation concurrently with inference
    util_samples: list[float] = []
    stop_event   = threading.Event()

    def _sampler():
        while not stop_event.is_set():
            util_samples.append(_sample_gpu_util_single())
            time.sleep(0.15)

    sampler = threading.Thread(target=_sampler, daemon=True)
    sampler.start()

    t0 = time.perf_counter()
    try:
        resp = _req.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": test_model, "prompt": "Reply with a single word: OK",
                  "stream": False},
            timeout=120,
        )
        resp.raise_for_status()
    except Exception as e:
        stop_event.set()
        sampler.join(timeout=2)
        return OllamaResult(True, model_names, False, 0,
                            max(util_samples, default=0), 0,
                            notes=f"inference error: {e}"[:80])

    inf_ms = (time.perf_counter() - t0) * 1000
    stop_event.set()
    sampler.join(timeout=2)

    peak_util = max(util_samples, default=0.0)

    # Check /api/ps for live VRAM usage (model may still be resident)
    try:
        ps  = _req.get(f"{OLLAMA_URL}/api/ps", timeout=5)
        running = ps.json().get("models", []) if ps.ok else []
    except Exception:
        running = []

    vram_mb = sum(m.get("size_vram", 0) for m in running) >> 20

    gpu_confirmed = (vram_mb > 0) or (peak_util > 15)

    return OllamaResult(
        reachable=True,
        models_loaded=model_names,
        gpu_confirmed=gpu_confirmed,
        vram_used_mb=vram_mb,
        util_during_inference=peak_util,
        inference_ms=inf_ms,
        notes=f"model={test_model}",
    )


# ── Phase 7: GPU stress test ──────────────────────────────────────────────────

def stress_test_gpu(duration_sec: int = 30) -> StressResult:
    """Saturate GPU compute with sustained cuBLAS SGEMM; monitor utilisation."""
    try:
        import cupy as cp
        import numpy as np
        import pynvml

        N = 4096   # large SGEMM saturates SMs with no JIT needed
        # Use np→cp transfer to allocate — avoids cupy fill kernels that need JIT
        A = cp.asarray(np.full((N, N), 1.01, dtype=np.float32))
        B = cp.asarray(np.full((N, N), 0.99, dtype=np.float32))

        # warmup
        _ = cp.matmul(A, B)
        cp.cuda.Stream.null.synchronize()

        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)

        samples_util:  list[float] = []
        samples_temp:  list[float] = []
        samples_power: list[float] = []
        throttled = False

        t_end = time.time() + duration_sec
        while time.time() < t_end:
            for _ in range(10):
                C = cp.matmul(A, B)
            cp.cuda.Stream.null.synchronize()

            util = pynvml.nvmlDeviceGetUtilizationRates(h).gpu
            temp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            try:
                pw = pynvml.nvmlDeviceGetPowerUsage(h) / 1000.0
            except Exception:
                pw = 0.0

            samples_util.append(float(util))
            samples_temp.append(float(temp))
            samples_power.append(pw)
            if temp > 87:
                throttled = True

        pynvml.nvmlShutdown()

        n = len(samples_util)
        return StressResult(
            duration_sec=float(duration_sec),
            avg_util=sum(samples_util) / n,
            max_util=max(samples_util),
            min_util=min(samples_util),
            avg_temp=sum(samples_temp) / n,
            max_temp=max(samples_temp),
            avg_power_w=sum(samples_power) / n,
            throttled=throttled,
            samples=[{"util": u, "temp": t, "power": p}
                     for u, t, p in zip(samples_util, samples_temp, samples_power)],
        )
    except Exception as e:
        return StressResult(
            duration_sec=0, avg_util=0, max_util=0, min_util=0,
            avg_temp=0, max_temp=0, avg_power_w=0, throttled=False,
            notes=str(e)[:120],
        )


# ── Phase 8: CPU-fallback detection ─────────────────────────────────────────

def detect_cpu_fallbacks(
    gpus: list[GpuInfo],
    cuda_checks: list[Check],
    ollama: OllamaResult,
) -> list[str]:
    issues: list[str] = []

    if not gpus:
        issues.append("No GPU detected — ALL workloads running on CPU")

    cuda_ok = any(c.name == "cupy (GPU compute)" and c.passed for c in cuda_checks)
    if not cuda_ok:
        issues.append("CUDA acceleration unavailable — tensor workloads fall back to CPU")

    nvd = os.environ.get("NVIDIA_VISIBLE_DEVICES", "")
    devs = [d for d in os.listdir("/dev") if d.startswith("nvidia")] if os.path.exists("/dev") else []
    # "void" + /dev/nvidia* present = GPU exposed via --gpus all runtime flag (valid)
    if not nvd or (nvd == "void" and not devs):
        issues.append("NVIDIA_VISIBLE_DEVICES not set — GPU not exposed to container runtime")

    if "compute" not in os.environ.get("NVIDIA_DRIVER_CAPABILITIES", ""):
        issues.append("NVIDIA_DRIVER_CAPABILITIES missing 'compute' — CUDA disabled in this container")

    if ollama.reachable and not ollama.gpu_confirmed:
        issues.append(
            "Ollama running but GPU inference NOT confirmed — "
            "model may be executing on CPU (VRAM=0, GPU%<15 during inference)"
        )

    return issues


# ── Phase 9: Scoring ──────────────────────────────────────────────────────────

def calculate_scores(
    gpus:              list[GpuInfo],
    container_checks:  list[Check],
    cuda_checks:       list[Check],
    benchmarks:        list[BenchResult],
    stress:            StressResult,
    ollama:            OllamaResult,
) -> Scores:
    s = Scores()

    # GPU Utilization Score — based on peak utilisation under stress
    if stress.max_util >= 90:   s.gpu_utilization = 100
    elif stress.max_util >= 70: s.gpu_utilization = 85
    elif stress.max_util >= 50: s.gpu_utilization = 65
    elif stress.max_util > 0:   s.gpu_utilization = 30
    else:                       s.gpu_utilization = 0

    # CUDA Health Score — 25 pts per gate
    pts = 0
    if gpus:                                                                  pts += 25
    if any(c.name == "pynvml / NVML"       and c.passed for c in cuda_checks):   pts += 25
    if any(c.name == "cupy (GPU compute)" and c.passed for c in cuda_checks):   pts += 25
    if any(b.passed for b in benchmarks):                                    pts += 25
    s.cuda_health = pts

    # Inference Acceleration Score
    if not ollama.reachable:
        s.inference_acceleration = 0
    elif ollama.gpu_confirmed:
        s.inference_acceleration = 100 if ollama.vram_used_mb > 0 else 80
    else:
        s.inference_acceleration = 20

    # VRAM Efficiency Score — penalise OOM risk (very high VRAM usage)
    if gpus:
        g = gpus[0]
        free_pct = g.vram_free_mb / g.vram_total_mb if g.vram_total_mb else 0
        s.vram_efficiency = min(100, int(free_pct * 80 + 20))
    else:
        s.vram_efficiency = 0

    # Container Compatibility Score
    passed = sum(1 for c in container_checks if c.passed)
    total  = len(container_checks)
    s.container_compatibility = int(passed / total * 100) if total else 0

    # Overall — weighted average
    vals    = [s.gpu_utilization, s.cuda_health, s.inference_acceleration,
               s.vram_efficiency, s.container_compatibility]
    weights = [0.25, 0.25, 0.25, 0.10, 0.15]
    s.overall = int(sum(w * v for w, v in zip(weights, vals)))

    return s


# ── Phase 10: Recommendations ────────────────────────────────────────────────

def build_recommendations(
    gpus:             list[GpuInfo],
    container_checks: list[Check],
    cuda_checks:      list[Check],
    ollama:           OllamaResult,
    stress:           StressResult,
) -> list[str]:
    recs: list[str] = []

    if not gpus:
        recs.append("No GPU found — run container with: docker run --gpus all ...")

    nvd  = os.environ.get("NVIDIA_VISIBLE_DEVICES", "")
    devs = [d for d in os.listdir("/dev") if d.startswith("nvidia")] if os.path.exists("/dev") else []
    if not nvd or (nvd == "void" and not devs):
        recs.append("Add -e NVIDIA_VISIBLE_DEVICES=all or use --gpus all to expose GPU")

    if "compute" not in os.environ.get("NVIDIA_DRIVER_CAPABILITIES", ""):
        recs.append("Add -e NVIDIA_DRIVER_CAPABILITIES=compute,utility for CUDA access")

    for c in container_checks:
        if not c.passed:
            if "device files" in c.name:
                recs.append(
                    "NVIDIA device files missing — install nvidia-container-toolkit "
                    "on the host and restart Docker daemon"
                )
            elif "libcuda" in c.name:
                recs.append(
                    "libcuda.so.1 not found — CUDA runtime not bind-mounted; "
                    "check nvidia-container-toolkit config"
                )

    for c in cuda_checks:
        if not c.passed and "cupy" in c.name:
            recs.append(
                "cupy unavailable — ensure cupy-cuda12x is installed and "
                "the container is started with --gpus all"
            )

    if ollama.reachable and not ollama.gpu_confirmed:
        recs.append(
            "Ollama not using GPU — ensure NVIDIA_VISIBLE_DEVICES and "
            "CUDA_VISIBLE_DEVICES are exported before 'ollama serve' starts"
        )

    if stress.throttled:
        recs.append(
            "GPU thermal throttling detected (>87 °C) — "
            "improve airflow, check TDP settings, or reduce workload concurrency"
        )

    if gpus and 0 < stress.max_util < 50:
        recs.append(
            "GPU utilisation below 50% under stress — possible CPU bottleneck "
            "or PCIe bandwidth limitation; profile with nsys or nvtop"
        )

    return recs


# ── Rich display helpers ──────────────────────────────────────────────────────

def _score_color(v: int) -> str:
    return "green" if v >= 80 else "yellow" if v >= 50 else "red"


def _score_label(v: int) -> str:
    return "EXCELLENT" if v >= 90 else "GOOD" if v >= 70 else "FAIR" if v >= 50 else "POOR"


def _speedup_cell(b: BenchResult) -> str:
    if not b.passed:
        return "—"
    if b.speedup >= 2.0:
        return f"[green]{b.speedup:.1f}x[/green]"
    if b.speedup >= 0.5:
        return f"[yellow]{b.speedup:.1f}x[/yellow]"
    return f"[red]{b.speedup:.2f}x[/red]"


def display_header():
    console.print(Rule("[bold cyan]EGGSHELL  ·  GPU VALIDATION + DIAGNOSTICS + BENCHMARK[/bold cyan]"))
    console.print(f"  v{VERSION}  ·  {datetime.datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}  ·  {platform.node()}")
    console.print()


def display_environment(env: dict):
    console.print(Rule("[bold]1 · Environment[/bold]"))
    t = Table(box=box.MINIMAL, show_header=False, padding=(0, 1))
    t.add_column(style="cyan", no_wrap=True, width=32)
    t.add_column()
    skip = {"timestamp", "PATH"}
    for k, v in env.items():
        if k not in skip:
            t.add_row(k, str(v))
    console.print(t)
    console.print()


def display_gpus(gpus: list[GpuInfo]):
    console.print(Rule("[bold]2 · GPU Inventory[/bold]"))
    if not gpus:
        console.print(Panel("[red bold]  NO GPUs DETECTED[/red bold]\n"
                            "  Container has no access to any NVIDIA GPU.",
                            border_style="red"))
        console.print()
        return
    t = Table(box=box.SIMPLE, show_header=True)
    t.add_column("#",  style="dim", width=3)
    t.add_column("Name", style="cyan")
    t.add_column("VRAM total / used / free", justify="right")
    t.add_column("GPU%", justify="right")
    t.add_column("Temp",  justify="right")
    t.add_column("Power", justify="right")
    t.add_column("CC")
    t.add_column("PCIe")
    t.add_column("Driver / CUDA")
    for g in gpus:
        t.add_row(
            str(g.index),
            g.name,
            f"{g.vram_total_mb:,} / {g.vram_used_mb:,} / {g.vram_free_mb:,} MB",
            f"{g.utilization_gpu}%",
            f"{g.temperature_c}°C",
            (f"{g.power_draw_w:.0f}/{g.power_limit_w:.0f}W"
             if g.power_limit_w else f"{g.power_draw_w:.0f}W"),
            g.compute_capability,
            (f"Gen{g.pcie_gen}×{g.pcie_width}" if g.pcie_gen else "—"),
            f"{g.driver_version} / {g.cuda_version_str}",
        )
    console.print(t)
    console.print()


def display_checks(title: str, checks: list[Check]):
    console.print(Rule(f"[bold]{title}[/bold]"))
    t = Table(box=box.MINIMAL, show_header=False, padding=(0, 1))
    t.add_column(width=42, no_wrap=True)
    t.add_column(width=6,  no_wrap=True)
    t.add_column()
    for c in checks:
        t.add_row(c.name, _ok(c.passed), c.value[:70])
    console.print(t)
    console.print()


def display_benchmarks(results: list[BenchResult]):
    console.print(Rule("[bold]5 · Tensor Benchmarks (GPU vs CPU)[/bold]"))
    t = Table(box=box.SIMPLE, show_header=True)
    t.add_column("Benchmark", style="cyan")
    t.add_column("Status", justify="center", width=6)
    t.add_column("GPU ms", justify="right")
    t.add_column("CPU ms", justify="right")
    t.add_column("Speedup", justify="right")
    t.add_column("Metric")
    for b in results:
        t.add_row(
            b.name,
            _ok(b.passed),
            f"{b.gpu_ms:.2f}" if b.passed else "—",
            f"{b.cpu_ms:.2f}" if b.passed else "—",
            _speedup_cell(b),
            b.metric if b.metric else (b.notes[:50] if b.notes else "—"),
        )
    console.print(t)
    console.print()


def display_ollama(o: OllamaResult):
    console.print(Rule("[bold]6 · Ollama GPU Validation[/bold]"))
    t = Table(box=box.MINIMAL, show_header=False, padding=(0, 1))
    t.add_column(style="cyan", width=30)
    t.add_column()
    t.add_row("Ollama reachable", _ok(o.reachable))
    t.add_row("Models available", ", ".join(o.models_loaded) or "NONE")
    t.add_row("GPU inference confirmed",
              "[green]YES — GPU ACCELERATION ACTIVE[/green]" if o.gpu_confirmed
              else "[red]NO  — CPU-only or unconfirmed[/red]")
    t.add_row("VRAM used by model",
              f"{o.vram_used_mb:,} MB" if o.vram_used_mb else "0 MB (model unloaded)")
    t.add_row("GPU% during inference", f"{o.util_during_inference:.0f}%")
    t.add_row("Inference latency", f"{o.inference_ms:.0f} ms" if o.inference_ms > 0 else "—")
    if o.notes:
        t.add_row("Notes", o.notes)
    console.print(t)
    console.print()


def display_stress(stress: StressResult):
    console.print(Rule("[bold]7 · GPU Stress Test[/bold]"))
    if stress.duration_sec == 0:
        reason = stress.notes or "skipped"
        console.print(f"[yellow]  Stress test not run — {reason}[/yellow]")
        console.print()
        return

    def _util_fmt(u: float) -> str:
        c = "green" if u >= 80 else "yellow" if u >= 50 else "red"
        return f"[{c}]{u:.1f}%[/{c}]"

    t = Table(box=box.MINIMAL, show_header=False, padding=(0, 1))
    t.add_column(style="cyan", width=30)
    t.add_column()
    t.add_row("Duration",             f"{stress.duration_sec:.0f} s")
    t.add_row("Avg GPU utilisation",  _util_fmt(stress.avg_util))
    t.add_row("Peak GPU utilisation", _util_fmt(stress.max_util))
    t.add_row("Min  GPU utilisation", _util_fmt(stress.min_util))
    t.add_row("Avg temperature",      f"{stress.avg_temp:.1f}°C")
    t.add_row("Peak temperature",
              f"[red]{stress.max_temp:.0f}°C  ← THERMAL THROTTLE RISK[/red]"
              if stress.max_temp > 85 else f"{stress.max_temp:.0f}°C")
    t.add_row("Avg power draw",
              f"{stress.avg_power_w:.0f} W" if stress.avg_power_w else "N/A")
    t.add_row("Thermal throttling",
              "[red]DETECTED[/red]" if stress.throttled else "[green]NONE[/green]")
    console.print(t)
    console.print()


def display_fallbacks(issues: list[str]):
    console.print(Rule("[bold]8 · CPU Fallback Detection[/bold]"))
    if not issues:
        console.print(Panel(
            "[green]  No CPU fallbacks detected.\n"
            "  All monitored workloads appear to be GPU-accelerated.[/green]",
            border_style="green",
        ))
    else:
        body = "\n".join(f"  [red]WARNING:[/red] {i}" for i in issues)
        console.print(Panel(body, border_style="red"))
    console.print()


def display_scores(scores: Scores):
    console.print(Rule("[bold]9 · Benchmark Scores[/bold]"))
    t = Table(box=box.SIMPLE, show_header=True)
    t.add_column("Category", style="cyan", width=38)
    t.add_column("Score", justify="right", width=7)
    t.add_column("Rating",  width=12)

    def _row(label: str, val: int, bold: bool = False):
        c = _score_color(val)
        lbl = _score_label(val)
        if bold:
            t.add_row(f"[bold]{label}[/bold]",
                      f"[bold]{val}[/bold]",
                      f"[bold][{c}]{lbl}[/{c}][/bold]")
        else:
            t.add_row(label, str(val), f"[{c}]{lbl}[/{c}]")

    _row("GPU Utilization Score",          scores.gpu_utilization)
    _row("CUDA Health Score",              scores.cuda_health)
    _row("Inference Acceleration Score",   scores.inference_acceleration)
    _row("VRAM Efficiency Score",          scores.vram_efficiency)
    _row("Container Compatibility Score",  scores.container_compatibility)
    t.add_section()
    _row("Overall GPU Score",              scores.overall, bold=True)
    console.print(t)
    console.print()


def display_recommendations(recs: list[str]):
    if not recs:
        return
    console.print(Rule("[bold yellow]10 · Recommendations[/bold yellow]"))
    for r in recs:
        console.print(f"  [yellow]→[/yellow]  {r}")
    console.print()


# ── Report persistence ────────────────────────────────────────────────────────

def save_report(data: dict) -> Optional[str]:
    try:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        ts   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = REPORT_DIR / f"gpu_benchmark_{ts}.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
        return str(path)
    except Exception as e:
        console.print(f"[yellow]Could not save report: {e}[/yellow]")
        return None


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="gpu-benchmark",
        description="Eggshell GPU Validation + Diagnostics + Performance Confirmation System",
    )
    parser.add_argument("--stress-duration", type=int, default=30, metavar="SEC",
                        help="Stress-test duration in seconds (default: 30)")
    parser.add_argument("--no-stress",  action="store_true", help="Skip GPU stress test")
    parser.add_argument("--no-ollama",  action="store_true", help="Skip Ollama GPU validation")
    parser.add_argument("--no-save",    action="store_true", help="Do not write JSON report file")
    parser.add_argument("--json",       action="store_true", help="Output JSON to stdout (no Rich UI)")
    args = parser.parse_args()

    if not args.json:
        display_header()

    # ── 1. Environment ────────────────────────────────────────────────────────
    env = scan_environment()
    if not args.json:
        display_environment(env)

    # ── 2. GPU inventory ──────────────────────────────────────────────────────
    if not args.json:
        console.print("[dim]Scanning GPUs via pynvml...[/dim]")
    gpus = scan_gpus()
    if not args.json:
        display_gpus(gpus)

    # ── 3. Docker runtime checks ──────────────────────────────────────────────
    container_checks = validate_docker_runtime()
    if not args.json:
        display_checks("3 · Docker / Container Runtime", container_checks)

    # ── 4. CUDA validation ────────────────────────────────────────────────────
    cuda_checks = validate_cuda()
    if not args.json:
        display_checks("4 · CUDA Validation", cuda_checks)

    # ── 5. Tensor benchmarks ──────────────────────────────────────────────────
    if not args.json:
        console.print("[dim]Running tensor benchmarks (JIT compile on first run)...[/dim]")
    benchmarks = [
        benchmark_elementwise_fma(),
        benchmark_vram_bandwidth(),
        benchmark_matmul_1024(),
    ]
    if not args.json:
        display_benchmarks(benchmarks)

    # ── 6. Ollama GPU validation ──────────────────────────────────────────────
    if args.no_ollama:
        ollama = OllamaResult(False, [], False, 0, 0, 0, notes="--no-ollama flag set")
    else:
        if not args.json:
            console.print("[dim]Validating Ollama GPU usage...[/dim]")
        ollama = validate_ollama_gpu()
    if not args.json:
        display_ollama(ollama)

    # ── 7. Stress test ────────────────────────────────────────────────────────
    cuda_available = any(c.name == "cupy (GPU compute)" and c.passed for c in cuda_checks)
    if args.no_stress or not cuda_available:
        stress = StressResult(
            duration_sec=0, avg_util=0, max_util=0, min_util=0,
            avg_temp=0, max_temp=0, avg_power_w=0, throttled=False,
            notes="--no-stress flag set" if args.no_stress else "CUDA unavailable",
        )
    else:
        if not args.json:
            console.print(f"[dim]Running {args.stress_duration}s GPU stress test...[/dim]")
        stress = stress_test_gpu(args.stress_duration)
    if not args.json:
        display_stress(stress)

    # ── 8. CPU fallback detection ─────────────────────────────────────────────
    fallbacks = detect_cpu_fallbacks(gpus, cuda_checks, ollama)
    if not args.json:
        display_fallbacks(fallbacks)

    # ── 9. Scores ─────────────────────────────────────────────────────────────
    scores = calculate_scores(gpus, container_checks, cuda_checks, benchmarks, stress, ollama)
    if not args.json:
        display_scores(scores)

    # ── 10. Recommendations ───────────────────────────────────────────────────
    recs = build_recommendations(gpus, container_checks, cuda_checks, ollama, stress)
    if not args.json:
        display_recommendations(recs)

    # ── Compile full report ───────────────────────────────────────────────────
    report = {
        "version":   VERSION,
        "timestamp": env["timestamp"],
        "hostname":  env["hostname"],
        "environment": env,
        "gpus":  [asdict(g) for g in gpus],
        "container_checks": [asdict(c) for c in container_checks],
        "cuda_checks":      [asdict(c) for c in cuda_checks],
        "benchmarks":       [asdict(b) for b in benchmarks],
        "stress_test":      asdict(stress),
        "ollama":           asdict(ollama),
        "scores":           asdict(scores),
        "cpu_fallbacks_detected": bool(fallbacks),
        "fallback_details": fallbacks,
        "recommendations":  recs,
    }

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        if not args.no_save:
            path = save_report(report)
            if path:
                console.print(f"[dim]  Report saved → {path}[/dim]")
        console.print(Rule())

    # Non-zero exit if overall score is critical
    sys.exit(0 if scores.overall >= 50 else 1)


if __name__ == "__main__":
    main()
