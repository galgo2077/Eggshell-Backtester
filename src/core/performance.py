"""Server-grade runtime tuning for the Pandas-only execution engine."""

from __future__ import annotations

import os
import shutil
import subprocess


def cpu_count() -> int:
    return os.cpu_count() or 1


def running_on_vastai() -> bool:
    markers = (
        "VAST_CONTAINERLABEL",
        "VAST_AI",
        "VAST_TCP_PORT_22",
        "VAST_MACHINE_ID",
        "VAST_CONTAINER_ID",
    )
    return any(os.environ.get(name) for name in markers) or os.path.exists("/.vast_container")


def default_worker_count() -> int:
    explicit = os.environ.get("EGGSHELL_WORKERS")
    if explicit:
        try:
            return max(1, int(explicit))
        except ValueError:
            pass

    cores = cpu_count()
    if running_on_vastai():
        return max(1, min(cores, 64))
    return max(1, min(cores, 32))


def enable_high_performance_mode() -> None:
    """Set conservative process-wide defaults before heavy Pandas/NumPy work."""
    workers = str(default_worker_count())
    threads = str(max(1, min(cpu_count(), int(workers))))
    defaults = {
        "EGGSHELL_HIGH_PERFORMANCE": "1",
        "EGGSHELL_WORKERS": workers,
        "OMP_NUM_THREADS": threads,
        "OPENBLAS_NUM_THREADS": threads,
        "MKL_NUM_THREADS": threads,
        "NUMEXPR_MAX_THREADS": threads,
        "NUMEXPR_NUM_THREADS": threads,
        "VECLIB_MAXIMUM_THREADS": threads,
        "MALLOC_ARENA_MAX": "4",
        "PYTHONMALLOC": "malloc",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def gpu_name() -> str:
    if not shutil.which("nvidia-smi"):
        return ""
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=name",
                "--format=csv,noheader",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
        )
        return ", ".join(line.strip() for line in out.splitlines() if line.strip())
    except Exception:
        return ""


def performance_diagnostics() -> dict[str, object]:
    enable_high_performance_mode()
    gpu = gpu_name()
    return {
        "cpu_threads": cpu_count(),
        "parallel_workers": default_worker_count(),
        "vastai": running_on_vastai(),
        "high_performance": os.environ.get("EGGSHELL_HIGH_PERFORMANCE") == "1",
        "gpu_detected": bool(gpu),
        "gpu_name": gpu or "None",
        "cuda_enabled": bool(os.environ.get("NVIDIA_VISIBLE_DEVICES", "")) or bool(gpu),
    }


def diagnostics_lines() -> list[str]:
    info = performance_diagnostics()
    return [
        "[PERFORMANCE ENGINE]",
        f"CPU Threads Used: {info['cpu_threads']}",
        f"GPU Detected: {info['gpu_name']}",
        f"CUDA Enabled: {info['cuda_enabled']}",
        f"Parallel Workers: {info['parallel_workers']}",
        f"Vast.ai Mode: {info['vastai']}",
        f"High Performance Mode: {info['high_performance']}",
    ]
