"""
Eggshell Persistent Inference Worker Pool
==========================================

Eliminates GPU idle gaps during Ollama inference by maintaining a pool of
persistent worker threads that continuously loop: submit → stream → next.

Root-cause fix
--------------
The GPU burst-idle pattern has two causes:

1. **Cold KV-cache prefill**: every unique prompt pays 5–9 s of prompt-eval
   before the first token is generated. Fix: all prompts share a common system
   prefix so Ollama's KV-cache prefix-store hits after the first warmup call —
   subsequent prefill drops to < 50 ms.

2. **Sequential single-request dispatch**: the TUI submits one blocking request
   per backtest, then waits. Fix: the pool maintains N workers that always have
   a request in-flight; the next prompt is queued before the current one finishes.

Design
------
    InferencePool (singleton via `pool` module attribute)
    ├── warmup()         — seed KV prefix cache; call once at startup
    ├── submit()         — queue a single prompt → Future[str]
    ├── submit_batch()   — queue many prompts → list[Future[str]]
    ├── _worker_loop()   — persistent thread: drain queue, stream tokens
    └── _scaler()        — periodic: spawn workers if GPU is underutilized

Thread safety
-------------
    submit() / submit_batch() are thread-safe.
    warmup() is idempotent and can be called from any thread.
    InferencePool can be imported safely from the TUI main thread; it does not
    start any threads until start() is called.

Usage
-----
    from ui.tui.utils.inference_pool import pool

    pool.start(model="qwen2.5:0.5b")   # call once at app startup
    fut = pool.submit("Explain Sharpe ratio.")
    text = fut.result()                # blocks until done
    pool.stop()                        # clean shutdown
"""
from __future__ import annotations

import json
import os
import queue
import threading
import time
import urllib.request
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import Callable, Optional


# ── Configuration ─────────────────────────────────────────────────────────────

OLLAMA_URL       = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
_DEFAULT_MODEL   = os.environ.get("EGGSHELL_AI_MODEL", "plutus")

# Workers
_INIT_WORKERS    = 2    # workers to launch on start()
_MAX_WORKERS     = 8    # cap; raise if GPU has > 8 GB VRAM free
_SCALE_INTERVAL  = 8.0  # seconds between adaptive-scaler checks
_IDLE_THRESHOLD  = 25   # GPU% below which the scaler adds a worker

# Ollama request options
_NUM_CTX         = 4096
_NUM_PREDICT     = -1     # unlimited; the AI analysis prompt should run to completion
_NUM_BATCH       = 512    # prompt-eval micro-batch size

# Shared prefix for KV-cache reuse
# All prompts MUST begin with this string so Ollama's prefix-cache store matches.
# After one warmup request, every subsequent worker skips the 5–9 s prefill.
_KV_PREFIX = (
    "You are a quant trading analyst. Plain text only, no markdown, no bullet points.\n\n"
)


# ── Internal dataclasses ──────────────────────────────────────────────────────

@dataclass
class _Request:
    prompt:     str
    model:      str
    future:     "Future[str]"
    on_token:   Optional[Callable[[str], None]] = None
    priority:   int = 0   # lower = higher priority (heapq not used; FIFO is fine for now)


@dataclass
class _WorkerStats:
    wid:         int
    status:      str  = "IDLE"      # IDLE | PREFILL | GENERATING | ERROR
    tokens_req:  int  = 0
    tokens_total:int  = 0
    requests:    int  = 0
    errors:      int  = 0
    tps:         float = 0.0
    prefill_ms:  float = 0.0


# ── InferencePool ─────────────────────────────────────────────────────────────

class InferencePool:
    """
    Persistent pool of inference workers that keep Ollama's GPU compute busy.

    Instantiate once and call start() before submitting prompts.
    """

    def __init__(self) -> None:
        self._model:         str             = _DEFAULT_MODEL
        self._queue:         queue.Queue[_Request] = queue.Queue()
        self._workers:       dict[int, _WorkerStats] = {}
        self._lock           = threading.Lock()
        self._running        = False
        self._warmed_up      = False
        self._wid_counter    = 0
        self._scaler_thread: Optional[threading.Thread] = None
        self._warmup_lock    = threading.Lock()

        # Telemetry integration (optional — silently skipped if unavailable)
        self._telemetry = None
        try:
            from core.gpu_telemetry import telemetry as _t
            self._telemetry = _t
        except Exception:
            pass

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self, model: Optional[str] = None, n_workers: int = _INIT_WORKERS) -> None:
        """
        Start the worker pool.

        Parameters
        ----------
        model :
            Ollama model name. Defaults to EGGSHELL_AI_MODEL env var or "plutus".
        n_workers :
            Initial number of persistent workers. Adaptive scaler may add more.
        """
        with self._lock:
            if self._running:
                return
            self._running = True
            if model:
                self._model = model

        if self._telemetry:
            self._telemetry.start()

        # Stagger worker launch so workers are always in different request phases,
        # avoiding synchronised idle gaps when all workers finish simultaneously.
        stagger = 1.5 / max(n_workers, 1)
        for i in range(n_workers):
            self._spawn_worker(stagger_sec=i * stagger)

        # Adaptive scaler
        self._scaler_thread = threading.Thread(
            target=self._scaler_loop, daemon=True, name="eggshell-pool-scaler"
        )
        self._scaler_thread.start()

    def stop(self) -> None:
        """Signal all workers to stop after their current request finishes."""
        with self._lock:
            self._running = False
        # Unblock any waiting workers
        for _ in range(len(self._workers) + 2):
            self._queue.put_nowait(
                _Request(prompt="", model=self._model, future=Future())
            )

    def warmup(self, model: Optional[str] = None) -> None:
        """
        Seed Ollama's KV-cache prefix store with _KV_PREFIX.

        After this call, all workers pay < 50 ms for prompt-eval instead of 5–9 s.
        Safe to call from any thread; subsequent calls are no-ops.
        """
        with self._warmup_lock:
            if self._warmed_up:
                return

        m = model or self._model
        warmup_prompt = _KV_PREFIX + "Reply with one word: READY"
        payload = json.dumps({
            "model":      m,
            "prompt":     warmup_prompt,
            "stream":     True,
            "keep_alive": -1,
            "options": {
                "num_ctx":     _NUM_CTX,
                "num_predict": 5,
                "num_batch":   _NUM_BATCH,
            },
        }).encode()
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for raw_line in resp:
                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if d.get("done"):
                        pe_ns = d.get("prompt_eval_duration", 0)
                        if self._telemetry and pe_ns > 0:
                            self._telemetry.record_prefill(pe_ns / 1e6)
                        break
        except Exception:
            pass  # non-fatal; workers will just pay cold prefill cost

        with self._warmup_lock:
            self._warmed_up = True

    def submit(
        self,
        prompt: str,
        model: Optional[str] = None,
        on_token: Optional[Callable[[str], None]] = None,
        priority: int = 0,
    ) -> "Future[str]":
        """
        Queue a prompt for inference. Returns immediately with a Future.

        Parameters
        ----------
        prompt :
            The full prompt text. If it does not already start with _KV_PREFIX,
            the prefix is prepended automatically to ensure KV-cache hits.
        model :
            Override the pool's default model for this request.
        on_token :
            Optional callback invoked with each streamed token string.
            Called from a worker thread — must be thread-safe.
        priority :
            Reserved for future priority queue support (currently ignored).

        Returns
        -------
        Future[str]
            ``.result()`` blocks until generation is complete.
        """
        if not prompt.startswith(_KV_PREFIX):
            prompt = _KV_PREFIX + prompt

        fut: Future[str] = Future()
        self._queue.put_nowait(_Request(
            prompt=prompt,
            model=model or self._model,
            future=fut,
            on_token=on_token,
            priority=priority,
        ))
        return fut

    def submit_batch(
        self,
        prompts: list[str],
        model: Optional[str] = None,
        priority: int = 0,
    ) -> list["Future[str]"]:
        """
        Queue multiple prompts at once. Returns a list of Futures in order.

        Submitting the whole batch at once lets workers overlap: worker 0
        starts on prompt[0] while worker 1 starts on prompt[1], etc.
        """
        return [self.submit(p, model=model, priority=priority) for p in prompts]

    def worker_stats(self) -> list[_WorkerStats]:
        with self._lock:
            return list(self._workers.values())

    def queue_depth(self) -> int:
        return self._queue.qsize()

    # ── Worker ────────────────────────────────────────────────────────────────

    def _spawn_worker(self, stagger_sec: float = 0.0) -> int:
        with self._lock:
            wid = self._wid_counter
            self._wid_counter += 1
            self._workers[wid] = _WorkerStats(wid=wid)

        t = threading.Thread(
            target=self._worker_loop,
            args=(wid, stagger_sec),
            daemon=True,
            name=f"eggshell-infer-{wid:02d}",
        )
        t.start()
        return wid

    def _worker_loop(self, wid: int, stagger_sec: float) -> None:
        """Persistent worker: drain queue, stream tokens, repeat."""
        if stagger_sec > 0:
            time.sleep(stagger_sec)

        while True:
            with self._lock:
                if not self._running:
                    break
                stats = self._workers.get(wid)
                if stats:
                    stats.status = "IDLE"

            try:
                req = self._queue.get(timeout=2.0)
            except queue.Empty:
                continue

            # Sentinel for shutdown
            if not req.prompt:
                break

            with self._lock:
                stats = self._workers.get(wid)
                if stats:
                    stats.status     = "PREFILL"
                    stats.tokens_req = 0

            self._stream_request(wid, req)

    def _stream_request(self, wid: int, req: _Request) -> None:
        """Send one streaming request to Ollama and collect the response."""
        payload = json.dumps({
            "model":      req.model,
            "prompt":     req.prompt,
            "stream":     True,
            "keep_alive": -1,     # keep model in VRAM between requests
            "options": {
                "num_ctx":     _NUM_CTX,
                "num_predict": _NUM_PREDICT,
                "num_batch":   _NUM_BATCH,
            },
        }).encode()

        http_req = urllib.request.Request(
            f"{OLLAMA_URL}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        chunks:   list[str] = []
        t_start             = time.perf_counter()
        first_token_at      = 0.0

        try:
            with urllib.request.urlopen(http_req, timeout=None) as resp:
                for raw_line in resp:
                    # Check for shutdown between lines
                    with self._lock:
                        if not self._running:
                            break
                        stats = self._workers.get(wid)

                    line = raw_line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if data.get("done"):
                        # Capture Ollama's own prompt-eval duration (nanoseconds)
                        pe_ns = data.get("prompt_eval_duration", 0)
                        if pe_ns > 0 and self._telemetry:
                            self._telemetry.record_prefill(pe_ns / 1e6)
                        if stats:
                            stats.prefill_ms = pe_ns / 1e6
                        break

                    tok = data.get("response", "")
                    if not tok:
                        continue

                    if first_token_at == 0.0:
                        first_token_at = time.perf_counter()
                        with self._lock:
                            if stats:
                                stats.status = "GENERATING"

                    chunks.append(tok)

                    # Update stats
                    with self._lock:
                        if stats:
                            stats.tokens_req   += 1
                            stats.tokens_total += 1
                            elapsed = time.perf_counter() - first_token_at
                            if elapsed > 0:
                                stats.tps = stats.tokens_req / elapsed

                    # Feed telemetry
                    if self._telemetry:
                        self._telemetry.record_tokens(1)

                    # Stream to caller
                    if req.on_token:
                        try:
                            req.on_token(tok)
                        except Exception:
                            pass

            result = "".join(chunks)
            req.future.set_result(result)

            with self._lock:
                if (stats := self._workers.get(wid)):
                    stats.requests += 1
                    stats.status    = "IDLE"

        except Exception as exc:
            try:
                req.future.set_exception(exc)
            except Exception:
                pass
            with self._lock:
                if (stats := self._workers.get(wid)):
                    stats.errors += 1
                    stats.status  = "ERROR"

    # ── Adaptive scaler ───────────────────────────────────────────────────────

    def _scaler_loop(self) -> None:
        """
        Periodically check GPU utilization and spawn additional workers if the
        GPU is underutilized and the worker cap has not been reached.

        Also prevents VRAM overload by respecting the max-worker cap.
        """
        time.sleep(15)  # let initial workers warm up before scaling

        while True:
            with self._lock:
                if not self._running:
                    break
            time.sleep(_SCALE_INTERVAL)

            if not self._telemetry:
                continue

            snap  = self._telemetry.snapshot()
            n     = len(self._workers)
            vram_pct = (snap.vram_used_mb / snap.vram_total_mb * 100) if snap.vram_total_mb else 0

            # Don't scale if VRAM is getting tight
            if vram_pct > 85:
                continue

            # Spawn one more worker if GPU is underutilized
            if snap.avg_util_pct < _IDLE_THRESHOLD and n < _MAX_WORKERS:
                self._spawn_worker(stagger_sec=0)


# ── Module-level singleton ────────────────────────────────────────────────────

#: Global inference pool. Call ``pool.start()`` once, then ``pool.submit()``.
pool = InferencePool()
