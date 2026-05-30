"""
Eggshell GPU Telemetry — lightweight background metrics collector.

Thread-safe. Samples pynvml at 2 Hz. Tracks:
  - GPU utilization %          (rolling 40-sample average)
  - GPU idle %                 (% samples where util < IDLE_THRESHOLD)
  - VRAM used / total (MB)
  - Temperature (°C) and power draw (W)
  - tokens/sec                 (fed by InferencePool)
  - avg prefill latency (ms)   (KV-cache hit indicator: < 50 ms = cache hit)

Usage
-----
    from core.gpu_telemetry import telemetry

    telemetry.start()          # idempotent — safe to call multiple times
    snap = telemetry.snapshot()
    print(snap.util_pct, snap.idle_pct, snap.tokens_sec)
    telemetry.stop()
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


# ── Thresholds ────────────────────────────────────────────────────────────────

IDLE_THRESHOLD   = 20   # % GPU util below which a sample counts as "idle"
SAMPLE_INTERVAL  = 0.5  # seconds between NVML polls (2 Hz)
HISTORY_SAMPLES  = 40   # rolling window for avg_util and idle_pct


# ── Snapshot dataclass ────────────────────────────────────────────────────────

@dataclass
class GPUSnapshot:
    """Immutable point-in-time GPU metrics."""
    util_pct:     float = 0.0   # instantaneous GPU utilization %
    avg_util_pct: float = 0.0   # rolling average over last HISTORY_SAMPLES
    idle_pct:     float = 0.0   # % of samples that were idle (< IDLE_THRESHOLD)
    vram_used_mb: int   = 0
    vram_total_mb: int  = 0
    vram_free_mb:  int  = 0
    temp_c:       int   = 0
    power_w:      float = 0.0
    tokens_sec:   float = 0.0   # tokens/sec fed by InferencePool
    prefill_ms:   float = 0.0   # avg prompt-eval latency (low = KV-cache hit)
    gpu_ok:       bool  = False  # True when pynvml is available


# ── GPUTelemetry ──────────────────────────────────────────────────────────────

class GPUTelemetry:
    """
    Singleton background sampler.

    Do not instantiate directly — use the module-level ``telemetry`` singleton.
    """

    def __init__(self) -> None:
        self._lock           = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running        = False

        # Rolling history
        self._util_hist: deque[float] = deque(maxlen=HISTORY_SAMPLES)
        self._idle_n     = 0
        self._total_n    = 0

        # Latest raw values
        self._snap = GPUSnapshot()

        # Inference metrics (pushed from InferencePool)
        self._token_window: deque[tuple[float, int]] = deque(maxlen=600)
        self._prefill_times: deque[float]            = deque(maxlen=50)

        # NVML handle
        self._nvml = None
        self._handle = None
        self._init_nvml()

    # ── NVML setup ────────────────────────────────────────────────────────────

    def _init_nvml(self) -> None:
        try:
            import pynvml
            pynvml.nvmlInit()
            self._handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            mem = pynvml.nvmlDeviceGetMemoryInfo(self._handle)
            self._nvml = pynvml
            with self._lock:
                self._snap = GPUSnapshot(
                    vram_total_mb=mem.total >> 20,
                    gpu_ok=True,
                )
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start background sampling thread. Idempotent."""
        with self._lock:
            if self._running:
                return
            self._running = True
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="eggshell-gpu-telemetry"
        )
        self._thread.start()

    def stop(self) -> None:
        """Signal the sampling thread to stop. Non-blocking."""
        with self._lock:
            self._running = False

    def snapshot(self) -> GPUSnapshot:
        """Return a copy of the latest metrics. Thread-safe."""
        with self._lock:
            return GPUSnapshot(**self._snap.__dict__)

    def avg_util(self) -> float:
        """Rolling average GPU utilization %."""
        with self._lock:
            h = list(self._util_hist)
        return sum(h) / len(h) if h else 0.0

    def idle_pct(self) -> float:
        """% of samples where GPU util < IDLE_THRESHOLD."""
        with self._lock:
            return (self._idle_n / self._total_n * 100) if self._total_n else 0.0

    # ── Inference metrics ingestion (called by InferencePool) ─────────────────

    def record_tokens(self, count: int) -> None:
        """Record N newly generated tokens. Called per token or per chunk."""
        with self._lock:
            self._token_window.append((time.monotonic(), count))

    def record_prefill(self, ms: float) -> None:
        """Record the prompt-eval duration for one request."""
        if ms > 0:
            with self._lock:
                self._prefill_times.append(ms)

    def tokens_per_sec(self) -> float:
        """Rolling 30-second tokens/sec."""
        with self._lock:
            now = time.monotonic()
            win = [(t, n) for t, n in self._token_window if now - t <= 30]
        if len(win) < 2:
            return 0.0
        span = win[-1][0] - win[0][0]
        return sum(n for _, n in win) / span if span > 0 else 0.0

    def avg_prefill_ms(self) -> float:
        """Average prompt-eval latency over last 50 requests."""
        with self._lock:
            if not self._prefill_times:
                return 0.0
            return sum(self._prefill_times) / len(self._prefill_times)

    # ── Background sampling loop ───────────────────────────────────────────────

    def _loop(self) -> None:
        while True:
            with self._lock:
                if not self._running:
                    break

            if self._nvml is not None:
                try:
                    n    = self._nvml
                    h    = self._handle
                    util = n.nvmlDeviceGetUtilizationRates(h).gpu
                    mem  = n.nvmlDeviceGetMemoryInfo(h)
                    temp = n.nvmlDeviceGetTemperature(h, n.NVML_TEMPERATURE_GPU)
                    try:
                        pwr = n.nvmlDeviceGetPowerUsage(h) / 1000.0
                    except Exception:
                        pwr = 0.0

                    tps   = self.tokens_per_sec()
                    pfms  = self.avg_prefill_ms()

                    with self._lock:
                        self._util_hist.append(float(util))
                        self._total_n += 1
                        if util < IDLE_THRESHOLD:
                            self._idle_n += 1

                        avg   = sum(self._util_hist) / len(self._util_hist)
                        idle  = (self._idle_n / self._total_n * 100)

                        self._snap = GPUSnapshot(
                            util_pct      = float(util),
                            avg_util_pct  = avg,
                            idle_pct      = idle,
                            vram_used_mb  = mem.used  >> 20,
                            vram_total_mb = mem.total >> 20,
                            vram_free_mb  = mem.free  >> 20,
                            temp_c        = temp,
                            power_w       = pwr,
                            tokens_sec    = tps,
                            prefill_ms    = pfms,
                            gpu_ok        = True,
                        )
                except Exception:
                    pass

            time.sleep(SAMPLE_INTERVAL)


# ── Module-level singleton ────────────────────────────────────────────────────

#: Global telemetry instance. Import and call ``telemetry.start()`` once.
telemetry = GPUTelemetry()
