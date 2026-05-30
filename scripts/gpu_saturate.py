#!/usr/bin/env python3
"""
Eggshell GPU Saturation Engine v2.0
Aggressively saturates GPU compute via concurrent Ollama inference streams.

Root-cause fix (v2): all prompts share a common prefix so Ollama's KV-cache
prefix-caching kicks in after the first request — subsequent prompt-eval phases
become ~0 ms instead of the 5-9 s cold-start overhead seen on unique prompts.
Workers are staggered on startup so they are always in different generation
phases, avoiding synchronised idle gaps.

Usage:
    gpu-saturate                        # aggressive mode, 60 s
    gpu-saturate --mode maximum         # max workers, max context, unlimited tokens
    gpu-saturate --mode light           # gentle ramp-up
    gpu-saturate --duration 120         # run 2 minutes
    gpu-saturate --workers 16           # pin worker count (disable auto-scale)
    gpu-saturate --model qwen2.5:7b     # specific model
    gpu-saturate --target-util 90       # GPU % target for adaptive scaler
    gpu-saturate --no-scale             # fixed worker count
    gpu-saturate --no-warmup            # skip warmup phase
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

try:
    import aiohttp
except ImportError:
    print("aiohttp required — run: pip install aiohttp")
    sys.exit(1)

try:
    from rich import box
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.rule import Rule
except ImportError:
    print("rich required — run: pip install rich")
    sys.exit(1)

console = Console()
VERSION    = "2.0.0"
OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

# ── Benchmark modes ───────────────────────────────────────────────────────────

@dataclass
class Mode:
    key:          str
    label:        str
    init_workers: int
    max_workers:  int
    num_ctx:      int
    num_predict:  int   # -1 = unlimited
    req_timeout:  int   # seconds per request before cancel
    target_util:  int   # % GPU utilization target

MODES: dict[str, Mode] = {
    "light": Mode(
        "light", "LIGHT",
        init_workers=2, max_workers=6,
        num_ctx=2048,  num_predict=512,
        req_timeout=90, target_util=60,
    ),
    "balanced": Mode(
        "balanced", "BALANCED",
        init_workers=4, max_workers=10,
        num_ctx=4096,  num_predict=1024,
        req_timeout=120, target_util=75,
    ),
    "aggressive": Mode(
        "aggressive", "AGGRESSIVE",
        init_workers=8, max_workers=20,
        num_ctx=8192,  num_predict=2048,
        req_timeout=180, target_util=85,
    ),
    "maximum": Mode(
        "maximum", "MAXIMUM SATURATION",
        init_workers=12, max_workers=32,
        num_ctx=16384, num_predict=-1,
        req_timeout=300, target_util=95,
    ),
}


# ── Prompts with a shared prefix for Ollama KV-cache reuse ───────────────────
#
# All prompts start with the SAME prefix paragraph. After the first request
# warms the KV cache for this prefix, every subsequent worker request pays
# near-zero prompt-eval overhead — Ollama detects the prefix match and skips
# recomputation. The unique suffix is what drives different generation output.

_PREFIX = (
    "You are an elite quantitative researcher and systems architect with "
    "decades of experience building high-performance financial systems, GPU "
    "computing infrastructure, and machine learning pipelines. Your task is "
    "to write an exhaustive, technically precise response with complete code "
    "implementations, mathematical derivations where relevant, and detailed "
    "explanations for every component. Do not summarize — write everything out "
    "in full. Begin immediately:\n\n"
)

_SUFFIXES = [
    (
        "Implement a complete, production-quality Python library for Monte Carlo "
        "simulation of financial derivatives. Include: Geometric Brownian Motion "
        "and Heston stochastic volatility path generators, European/American/"
        "barrier/Asian/lookback option pricing, full Greeks (delta gamma theta "
        "vega rho) via finite differences and pathwise methods, variance reduction "
        "(antithetic variates, control variates, importance sampling), portfolio "
        "VaR and CVaR, Sharpe/Sortino/Calmar ratios. Write 800+ lines of "
        "fully working, type-annotated Python with docstrings and unit tests."
    ),
    (
        "Design and implement a complete distributed database engine from scratch. "
        "Include: B+-tree with insert/delete/range-scan and page-level latching, "
        "write-ahead log (WAL) with group commit and checkpointing, MVCC with "
        "timestamp ordering and garbage collection, buffer pool manager (LRU-K "
        "eviction, dirty page tracking, force/steal policy), cost-based query "
        "planner with statistics and join order enumeration, full SQL parser for "
        "SELECT/INSERT/UPDATE/DELETE/JOIN, consistent hashing for sharding, "
        "Raft consensus (leader election, log replication, snapshotting). "
        "Write 900+ lines of complete, correct, commented Python."
    ),
    (
        "Derive from first principles the complete mathematical theory of "
        "transformer neural networks. Cover: scaled dot-product attention "
        "(prove why sqrt(d_k) prevents gradient vanishing), multi-head attention, "
        "positional encoding (sinusoidal, RoPE, ALiBi — derive each), "
        "layer normalisation forward and backward pass, full backpropagation "
        "through the stack, memory and compute complexity analysis per layer, "
        "flash attention memory savings, grouped query attention, sliding window "
        "attention. Write every equation, proof, and derivation in full detail."
    ),
    (
        "Build a complete algorithmic trading system. Components: (1) L2 order "
        "book with price-time priority matching engine, (2) market data feed "
        "handler with tick normalisation and gap detection, (3) strategy framework "
        "supporting momentum, mean-reversion, statistical arb, pairs trading, "
        "market making with adverse selection, (4) risk engine with real-time "
        "position limits, parametric VaR, historical CVaR, max drawdown circuit "
        "breakers, concentration limits, (5) portfolio optimizer with "
        "mean-variance (Markowitz), Black-Litterman, risk parity, min-CVaR, "
        "(6) backtester with transaction costs, market impact (Almgren-Chriss), "
        "tick-level slippage. Write 900+ lines of complete working code."
    ),
    (
        "Implement a complete optimising compiler for a statically typed language. "
        "Include: (1) lexer with full tokenisation and error recovery, (2) "
        "recursive descent parser with typed AST and operator precedence, (3) "
        "semantic analyser with Hindley-Milner type inference, (4) symbol table "
        "with nested scope resolution, (5) SSA-form IR construction, (6) "
        "optimisation passes: constant folding, dead code elimination, CSE, "
        "LICM, inlining, (7) register allocation with graph coloring (Chaitin), "
        "(8) x86-64 assembly codegen with System V ABI, (9) ELF binary output "
        "with relocation. Write 900+ lines of fully working code with tests."
    ),
]

_PROMPTS = [_PREFIX + s for s in _SUFFIXES]


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class WorkerState:
    id:            int
    status:        str   = "STARTING"
    tokens_req:    int   = 0
    tokens_total:  int   = 0
    requests:      int   = 0
    tps:           float = 0.0
    errors:        int   = 0
    req_start:     float = 0.0
    prefill_ms:    float = 0.0   # last prompt-eval duration


@dataclass
class GPUSnapshot:
    util:       float = 0.0
    vram_used:  int   = 0
    vram_total: int   = 0
    temp:       int   = 0
    power:      float = 0.0


# ── GPU Monitor ───────────────────────────────────────────────────────────────

class GPUMonitor:
    """Background thread samples pynvml at 2 Hz with idle-time tracking."""

    def __init__(self):
        self._snap        = GPUSnapshot()
        self._lock        = threading.Lock()
        self._running     = False
        self._thread      = threading.Thread(target=self._loop, daemon=True)
        self._hist:  deque[float] = deque(maxlen=40)
        self._idle_n      = 0   # samples where GPU% < 20 (true idle)
        self._total_n     = 0
        try:
            import pynvml
            pynvml.nvmlInit()
            self._h    = pynvml.nvmlDeviceGetHandleByIndex(0)
            self._nvml = pynvml
            self._ok   = True
        except Exception:
            self._ok = False

    def start(self): self._running = True;  self._thread.start()
    def stop(self):  self._running = False

    def snap(self) -> GPUSnapshot:
        with self._lock:
            return self._snap

    def avg_util(self) -> float:
        with self._lock:
            h = list(self._hist)
        return sum(h) / len(h) if h else 0.0

    def idle_pct(self) -> float:
        with self._lock:
            return (self._idle_n / self._total_n * 100) if self._total_n > 0 else 0.0

    def _loop(self):
        while self._running:
            if self._ok:
                try:
                    n    = self._nvml
                    h    = self._h
                    util = n.nvmlDeviceGetUtilizationRates(h).gpu
                    mem  = n.nvmlDeviceGetMemoryInfo(h)
                    temp = n.nvmlDeviceGetTemperature(h, n.NVML_TEMPERATURE_GPU)
                    try:    pwr = n.nvmlDeviceGetPowerUsage(h) / 1000.0
                    except: pwr = 0.0
                    s = GPUSnapshot(
                        util=float(util),
                        vram_used=mem.used >> 20,
                        vram_total=mem.total >> 20,
                        temp=temp, power=pwr,
                    )
                    with self._lock:
                        self._snap = s
                        self._hist.append(float(util))
                        self._total_n += 1
                        if util < 20:
                            self._idle_n += 1
                except Exception:
                    pass
            time.sleep(0.5)


# ── Throughput tracker ────────────────────────────────────────────────────────

class ThroughputTracker:
    """Rolling 30-second token rate with prefill-latency tracking."""

    def __init__(self):
        self._lock           = threading.Lock()
        self.total_tokens    = 0
        self.total_requests  = 0
        self._window: deque[tuple[float, int]] = deque(maxlen=600)
        self._prefill_times: deque[float] = deque(maxlen=50)

    def record(self, tokens: int):
        with self._lock:
            self.total_tokens += tokens
            self._window.append((time.monotonic(), tokens))

    def done(self, prefill_ms: float = 0.0):
        with self._lock:
            self.total_requests += 1
            if prefill_ms > 0:
                self._prefill_times.append(prefill_ms)

    def tps(self) -> float:
        with self._lock:
            now = time.monotonic()
            win = [(t, n) for t, n in self._window if now - t <= 30]
            if len(win) < 2:
                return 0.0
            span = win[-1][0] - win[0][0]
            return sum(n for _, n in win) / span if span > 0 else 0.0

    def avg_prefill_ms(self) -> float:
        with self._lock:
            if not self._prefill_times:
                return 0.0
            return sum(self._prefill_times) / len(self._prefill_times)


# ── Saturation Engine ─────────────────────────────────────────────────────────

class SaturationEngine:

    def __init__(
        self,
        mode:        Mode,
        model:       str,
        duration:    int,
        pin_workers: Optional[int],
        target_util: Optional[int],
        no_scale:    bool,
        no_warmup:   bool,
    ):
        self.mode        = mode
        self.model       = model
        self.duration    = duration
        self.pin_workers = pin_workers
        self.target_util = target_util or mode.target_util
        self.no_scale    = no_scale
        self.no_warmup   = no_warmup

        self._running    = False
        self._gpu        = GPUMonitor()
        self._tracker    = ThroughputTracker()
        self._workers: dict[int, WorkerState] = {}
        self._nwid       = 0
        self._prompt_idx = 0
        self._log_buf: deque[str] = deque(maxlen=6)
        self._start_ts   = 0.0

    # ── helpers ───────────────────────────────────────────────────────────────

    def _next_prompt(self) -> str:
        p = _PROMPTS[self._prompt_idx % len(_PROMPTS)]
        self._prompt_idx += 1
        return p

    def _log(self, msg: str):
        self._log_buf.append(f"[dim]{time.strftime('%H:%M:%S')}[/dim]  {msg}")

    def _bar(self, v: float, m: float, w: int = 22, c: str = "green") -> str:
        f = max(0, min(w, int(v / m * w))) if m > 0 else 0
        return f"[{c}]{'█' * f}[/{c}][dim]{'░' * (w - f)}[/dim]"

    # ── worker ────────────────────────────────────────────────────────────────

    async def _worker(self, wid: int, stagger_sec: float = 0.0):
        if stagger_sec > 0:
            await asyncio.sleep(stagger_sec)

        state   = self._workers[wid]
        state.status = "WARMING"
        timeout = aiohttp.ClientTimeout(total=self.mode.req_timeout)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            while self._running:
                prompt = self._next_prompt()
                payload = {
                    "model":      self.model,
                    "prompt":     prompt,
                    "stream":     True,
                    "keep_alive": -1,     # keep model in VRAM permanently
                    "options": {
                        "num_ctx":     self.mode.num_ctx,
                        "num_predict": self.mode.num_predict,
                        "num_batch":   512,  # prompt-eval batch size (explicit)
                    },
                }

                state.status    = "PREFILL"
                state.tokens_req = 0
                state.req_start  = time.perf_counter()
                first_token_at   = 0.0

                try:
                    async with session.post(
                        f"{OLLAMA_URL}/api/generate", json=payload
                    ) as resp:
                        while True:
                            line = await resp.content.readline()
                            if not line:
                                break
                            if not self._running:
                                break
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                data = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if data.get("done"):
                                # capture Ollama's own prompt-eval timing
                                pe_ns = data.get("prompt_eval_duration", 0)
                                if pe_ns > 0:
                                    state.prefill_ms = pe_ns / 1e6
                                break
                            # first token marks transition from PREFILL → GENERATE
                            if state.tokens_req == 0:
                                first_token_at = time.perf_counter()
                                state.status   = "GENERATING"
                            state.tokens_req   += 1
                            state.tokens_total += 1
                            self._tracker.record(1)
                            elapsed = time.perf_counter() - (first_token_at or state.req_start)
                            if elapsed > 0:
                                state.tps = state.tokens_req / elapsed

                except asyncio.TimeoutError:
                    state.errors += 1
                    self._log(f"W{wid:02d} timeout ({self.mode.req_timeout}s)")
                except aiohttp.ClientError:
                    state.errors += 1
                    state.status = "ERROR"
                    self._log(f"W{wid:02d} connection error — retrying in 3s")
                    await asyncio.sleep(3)
                    continue
                except Exception as e:
                    state.errors += 1
                    state.status = "ERROR"
                    self._log(f"W{wid:02d} {str(e)[:55]}")
                    await asyncio.sleep(2)
                    continue

                state.requests += 1
                self._tracker.done(prefill_ms=state.prefill_ms)
                state.status = "IDLE"

    def _spawn(self, stagger: float = 0.0) -> int:
        wid = self._nwid
        self._nwid += 1
        self._workers[wid] = WorkerState(id=wid)
        asyncio.create_task(self._worker(wid, stagger_sec=stagger))
        return wid

    # ── adaptive scaler ───────────────────────────────────────────────────────

    async def _scaler(self):
        await asyncio.sleep(12)   # give warmup + initial workers time to ramp
        consecutive_low = 0

        while self._running:
            await asyncio.sleep(5)
            if self.no_scale or self.pin_workers:
                continue

            avg  = self._gpu.avg_util()
            n    = len(self._workers)
            maxw = self.mode.max_workers

            if avg < self.target_util - 10 and n < maxw:
                wid = self._spawn(stagger=0)
                self._log(
                    f"[yellow]GPU {avg:.0f}% < target {self.target_util}% "
                    f"→ +W{wid:02d}  workers {n+1}/{maxw}[/yellow]"
                )
                consecutive_low = 0
            elif avg >= self.target_util:
                consecutive_low = 0
            else:
                consecutive_low += 1
                if consecutive_low == 3 and n >= maxw:
                    self._log(
                        "[yellow]GPU below target at max workers "
                        "— model may be too small for full saturation[/yellow]"
                    )

    # ── display ───────────────────────────────────────────────────────────────

    def _render(self) -> Panel:
        gpu  = self._gpu.snap()
        avg  = self._gpu.avg_util()
        idle = self._gpu.idle_pct()
        tps  = self._tracker.tps()
        pfms = self._tracker.avg_prefill_ms()
        now  = time.time()
        done = self.duration - (now - self._start_ts)

        uc   = "green" if avg >= self.target_util else ("yellow" if avg >= 50 else "red")
        ic   = "green" if idle < 10 else ("yellow" if idle < 30 else "red")
        vp   = (gpu.vram_used / gpu.vram_total * 100) if gpu.vram_total else 0
        vc   = "green" if vp < 85 else "yellow"

        if avg >= self.target_util:
            sat = "[bold green]● SATURATED[/bold green]"
        elif avg >= 60:
            sat = "[yellow]◐ LOADING[/yellow]"
        else:
            sat = "[red]○ UNDERUTILIZED[/red]"

        cpu_bottleneck = (
            self._tracker.total_tokens > 500
            and avg < 35
            and len(self._workers) >= self.mode.max_workers
        )

        lines: list[str] = [
            f"  [bold cyan]⚡ GPU SATURATION ENGINE[/bold cyan]  "
            f"[dim]v{VERSION}[/dim]  ·  [bold]{self.mode.label}[/bold]  ·  {sat}",
            "",
            f"  GPU Util   {self._bar(avg,  100, 22, uc)}  [{uc}]{avg:5.1f}%[/{uc}]"
            f"  [dim]target {self.target_util}%[/dim]",
            f"  GPU Idle   {self._bar(idle, 100, 22, ic)}  [{ic}]{idle:5.1f}%[/{ic}]"
            f"  [dim](< 10% = excellent)[/dim]",
            f"  VRAM       {self._bar(vp,   100, 22, vc)}  [{vc}]{gpu.vram_used:,}[/{vc}]"
            f"[dim]/{gpu.vram_total:,} MB[/dim]",
            f"  Temp [dim]{gpu.temp}°C[/dim]    Power [dim]{gpu.power:.0f} W[/dim]    "
            f"Prefill avg [dim]{pfms:.0f} ms[/dim]    "
            f"CPU bottleneck: {'[red]YES[/red]' if cpu_bottleneck else '[green]NO[/green]'}",
            "",
            f"  [bold]Throughput[/bold]  [green]{tps:8.1f} tok/s[/green]"
            f"  Total [white]{self._tracker.total_tokens:,}[/white] tokens"
            f"  Requests [white]{self._tracker.total_requests}[/white]",
            f"  Model [cyan]{self.model}[/cyan]"
            f"  ctx [cyan]{self.mode.num_ctx:,}[/cyan]"
            f"  workers [cyan]{len(self._workers)}[/cyan]/[dim]{self.mode.max_workers}[/dim]"
            f"  [dim]{max(0, done):.0f}s remaining[/dim]",
            "",
            "  [bold]Workers[/bold]",
        ]

        ws = sorted(self._workers.values(), key=lambda w: w.id)
        for w in ws[:14]:
            sc = {
                "GENERATING": "green", "PREFILL": "cyan",
                "IDLE": "dim", "WARMING": "yellow",
                "ERROR": "red", "STARTING": "yellow",
            }.get(w.status, "dim")
            wb = self._bar(min(w.tps, 400), 400, 14, "cyan")
            pfill = f"[dim]pf:{w.prefill_ms:.0f}ms[/dim]" if w.prefill_ms > 0 else ""
            lines.append(
                f"  W{w.id:02d}  [{sc}]{w.status:<11}[/{sc}]  {wb}"
                f"  [cyan]{w.tps:6.1f}[/cyan][dim] t/s[/dim]"
                f"  [dim]req:{w.requests} err:{w.errors}[/dim]  {pfill}"
            )
        if len(ws) > 14:
            lines.append(f"  [dim]  … and {len(ws)-14} more workers[/dim]")

        if self._log_buf:
            lines += ["", "  [bold]Events[/bold]"]
            for m in list(self._log_buf)[-4:]:
                lines.append(f"  {m}")

        recs = []
        if avg < 40 and len(self._workers) >= self.mode.max_workers:
            recs.append("[yellow]Model too small for full saturation — try a larger model[/yellow]")
        if vp > 88:
            recs.append("[red]VRAM near capacity — reduce num_ctx or worker count[/red]")
        if cpu_bottleneck:
            recs.append("[yellow]CPU bottleneck — set OLLAMA_NUM_PARALLEL=16 and restart Ollama[/yellow]")
        if idle > 30 and pfms > 1000:
            recs.append(f"[yellow]High prefill latency ({pfms:.0f} ms) — prefix caching not active yet, warming[/yellow]")
        if recs:
            lines += ["", "  [bold yellow]Recommendations[/bold yellow]"]
            lines += [f"  → {r}" for r in recs]

        return Panel("\n".join(lines), border_style="cyan", box=box.HEAVY)

    # ── warmup ────────────────────────────────────────────────────────────────

    async def _warmup(self):
        """
        Send one request with the shared prompt prefix to seed Ollama's KV-cache
        prefix store. After this, all workers see ~0 ms prefill for the prefix.
        Also forces CUDA kernel compilation so the first real request is fast.
        """
        self._log("[cyan]Warmup: seeding KV-cache prefix...[/cyan]")
        payload = {
            "model":      self.model,
            "prompt":     _PREFIX + "Briefly explain what GPU computing is.",
            "stream":     True,
            "keep_alive": -1,
            "options": {
                "num_ctx":     min(self.mode.num_ctx, 4096),
                "num_predict": 30,
                "num_batch":   512,
            },
        }
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{OLLAMA_URL}/api/generate", json=payload
                ) as resp:
                    tokens = 0
                    t0 = time.perf_counter()
                    async for line in resp.content:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            d = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if d.get("done"):
                            break
                        tokens += 1
                    elapsed = time.perf_counter() - t0
            self._log(
                f"[green]Warmup done — {tokens} tokens in {elapsed:.1f}s"
                f"  ({tokens/elapsed:.0f} tok/s)[/green]"
            )
        except Exception as e:
            self._log(f"[yellow]Warmup failed (non-fatal): {e}[/yellow]")

    # ── model resolution ──────────────────────────────────────────────────────

    async def _pick_model(self) -> Optional[str]:
        if self.model != "auto":
            return self.model
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=5)
            ) as s:
                async with s.get(f"{OLLAMA_URL}/api/tags") as r:
                    models = [m["name"] for m in (await r.json()).get("models", [])]
        except Exception:
            return None
        if not models:
            return None
        for hint in ["70b", "34b", "13b", "7b", "3b", "1b", "0.5b"]:
            for m in models:
                if hint in m.lower():
                    return m
        return models[0]

    # ── main run loop ─────────────────────────────────────────────────────────

    async def run(self):
        self._running  = True
        self._start_ts = time.time()
        self._gpu.start()

        model = await self._pick_model()
        if not model:
            console.print(
                "[red]No Ollama models found.[/red]  "
                "Pull a model first (e.g. [bold]ollama pull qwen2.5:0.5b[/bold])"
            )
            self._gpu.stop()
            return
        self.model = model
        self._log(f"Model: [cyan]{self.model}[/cyan]")

        # Warmup: seed KV-cache prefix + force CUDA kernel compilation
        if not self.no_warmup:
            await self._warmup()

        # Spawn initial workers with staggered start times so they are always
        # in different phases of the request lifecycle — avoids synchronised
        # idle gaps when all workers finish and restart at the same moment.
        n = self.pin_workers or self.mode.init_workers
        stagger_interval = 1.5 / max(n, 1)   # spread over 1.5 s window
        for i in range(n):
            self._spawn(stagger=i * stagger_interval)
        self._log(
            f"Launched {n} workers staggered over {stagger_interval*n:.1f}s  "
            f"(max {self.mode.max_workers})"
        )

        asyncio.create_task(self._scaler())

        with Live(self._render(), refresh_per_second=2, console=console) as live:
            while self._running:
                elapsed = time.time() - self._start_ts
                if elapsed >= self.duration:
                    break
                live.update(self._render())
                await asyncio.sleep(0.5)

        self._running = False
        self._gpu.stop()

        # ── final report ──────────────────────────────────────────────────────
        gpu   = self._gpu.snap()
        avg   = self._gpu.avg_util()
        idle  = self._gpu.idle_pct()
        pfms  = self._tracker.avg_prefill_ms()

        console.print()
        console.print(Rule("[bold cyan]SATURATION COMPLETE[/bold cyan]"))
        console.print(f"  Total tokens      : [green]{self._tracker.total_tokens:,}[/green]")
        console.print(f"  Total requests    : {self._tracker.total_requests}")
        console.print(f"  Avg throughput    : [green]{self._tracker.tps():.1f} tok/s[/green]")
        console.print(f"  Avg GPU util      : {avg:.1f}%")
        console.print(
            f"  GPU idle time     : "
            + ("[green]" if idle < 10 else "[yellow]" if idle < 25 else "[red]")
            + f"{idle:.1f}%"
            + ("[/green]" if idle < 10 else "[/yellow]" if idle < 25 else "[/red]")
            + "  (target < 10%)"
        )
        console.print(f"  Avg prefill (ms)  : {pfms:.0f} ms"
                      + ("  [green](KV-cache hits active)[/green]" if pfms < 50 else
                         "  [yellow](cache miss — warmup needed)[/yellow]"))
        console.print(f"  Final VRAM        : {gpu.vram_used:,} / {gpu.vram_total:,} MB")
        console.print(f"  Workers used      : {len(self._workers)}")
        console.print()


# ── Benchmark comparison ─────────────────────────────────────────────────────

@dataclass
class _PhaseResult:
    label:         str
    avg_util:      float
    idle_pct:      float
    tokens_sec:    float
    prefill_ms:    float
    requests_min:  float


async def _run_comparison_phase(
    engine: SaturationEngine,
    label: str,
    duration: int,
) -> _PhaseResult:
    """Run a single saturation phase and return metrics."""
    console.print(f"\n  [bold cyan]Phase: {label}[/bold cyan]  [dim]({duration}s)[/dim]")
    await engine.run()

    avg_util     = engine._gpu.avg_util()
    idle_pct     = engine._gpu.idle_pct()
    tps          = engine._tracker.tps()
    prefill_ms   = engine._tracker.avg_prefill_ms()
    reqs         = engine._tracker.total_requests
    requests_min = reqs / (duration / 60.0) if duration > 0 else 0.0

    return _PhaseResult(
        label        = label,
        avg_util     = avg_util,
        idle_pct     = idle_pct,
        tokens_sec   = tps,
        prefill_ms   = prefill_ms,
        requests_min = requests_min,
    )


async def run_benchmark_comparison(
    model:    str,
    mode_key: str,
    duration: int,
) -> None:
    """
    Run two consecutive saturation phases and print a side-by-side comparison:

    BEFORE  — unique prompts, no prefix sharing, no warmup, serial dispatch.
              Simulates the original burst-idle scheduling pattern.

    AFTER   — shared KV prefix, warmup, staggered workers.
              Demonstrates the optimized continuous-compute pattern.
    """
    mode = MODES[mode_key]

    console.print(Rule("[bold yellow]⚡ BENCHMARK COMPARISON MODE[/bold yellow]"))
    console.print(
        "  Runs two phases and compares GPU utilization metrics.\n"
        "  [bold]BEFORE[/bold]: unique prompts / no warmup / no prefix sharing\n"
        "  [bold]AFTER[/bold]:  shared KV prefix / warmup / staggered workers\n"
    )

    # ── BEFORE phase: simulate old behavior ───────────────────────────────────────
    # Use unique prompts (no shared prefix) so Ollama cannot reuse the KV cache.
    # This reproduces the cold-prefill burst-idle pattern.
    global _PROMPTS
    _original_prompts = list(_PROMPTS)
    # Temporarily replace prompts with unique, non-prefixed variants
    _PROMPTS = [s for s in _SUFFIXES]  # suffixes only, no common prefix

    before_engine = SaturationEngine(
        mode        = mode,
        model       = model,
        duration    = duration,
        pin_workers = mode.init_workers,
        target_util = None,
        no_scale    = True,    # fixed workers so comparison is fair
        no_warmup   = True,    # no warmup = cold cache every request
    )
    before = await _run_comparison_phase(before_engine, "BEFORE (cold cache, unique prompts)", duration)

    # ── Restore optimized prompts ───────────────────────────────────────────
    _PROMPTS = _original_prompts

    # Brief cooldown between phases
    console.print("\n  [dim]Cooling down 5s before AFTER phase...[/dim]")
    await asyncio.sleep(5)

    # ── AFTER phase: optimized scheduling ─────────────────────────────────
    after_engine = SaturationEngine(
        mode        = mode,
        model       = model,
        duration    = duration,
        pin_workers = mode.init_workers,
        target_util = None,
        no_scale    = True,
        no_warmup   = False,   # warmup seeds KV prefix cache
    )
    after = await _run_comparison_phase(after_engine, "AFTER  (shared prefix, warmed KV cache)", duration)

    # ── Comparison table ─────────────────────────────────────────────
    from rich.table import Table

    def _delta_str(before_val: float, after_val: float, higher_is_better: bool = True) -> str:
        delta = after_val - before_val
        if higher_is_better:
            color = "green" if delta > 0 else ("red" if delta < 0 else "dim")
        else:
            color = "green" if delta < 0 else ("red" if delta > 0 else "dim")
        sign = "+" if delta >= 0 else ""
        return f"[{color}]{sign}{delta:.1f}[/{color}]"

    def _pct_delta(before_val: float, after_val: float, higher_is_better: bool = True) -> str:
        delta = after_val - before_val
        if higher_is_better:
            color = "green" if delta > 0 else ("red" if delta < 0 else "dim")
        else:
            color = "green" if delta < 0 else ("red" if delta > 0 else "dim")
        sign = "+" if delta >= 0 else ""
        return f"[{color}]{sign}{delta:.1f}pp[/{color}]"

    tbl = Table(
        title="[bold cyan]⚡ GPU PIPELINE OPTIMIZATION — BEFORE vs AFTER[/bold cyan]",
        show_header=True,
        header_style="bold magenta",
        border_style="cyan",
        box=box.HEAVY,
    )
    tbl.add_column("Metric",          style="dim",   width=26)
    tbl.add_column("BEFORE",          justify="right", width=14)
    tbl.add_column("AFTER",           justify="right", width=14)
    tbl.add_column("Δ Delta",         justify="right", width=14)
    tbl.add_column("Target",          justify="right", width=14)

    rows = [
        ("GPU util avg %",
         f"{before.avg_util:.1f}%", f"{after.avg_util:.1f}%",
         _pct_delta(before.avg_util, after.avg_util, True),
         "[green]> 70%[/green]"),
        ("GPU idle %",
         f"{before.idle_pct:.1f}%", f"{after.idle_pct:.1f}%",
         _pct_delta(before.idle_pct, after.idle_pct, False),
         "[green]< 15%[/green]"),
        ("Tokens / sec",
         f"{before.tokens_sec:.1f}", f"{after.tokens_sec:.1f}",
         _delta_str(before.tokens_sec, after.tokens_sec, True),
         "[green]> 200[/green]"),
        ("Prefill latency (ms)",
         f"{before.prefill_ms:.0f}", f"{after.prefill_ms:.0f}",
         _delta_str(before.prefill_ms, after.prefill_ms, False),
         "[green]< 50[/green]"),
        ("Requests / min",
         f"{before.requests_min:.1f}", f"{after.requests_min:.1f}",
         _delta_str(before.requests_min, after.requests_min, True),
         "[green]> 30[/green]"),
    ]
    for row in rows:
        tbl.add_row(*row)

    console.print()
    console.print(tbl)

    # Summary verdict
    util_improvement = after.avg_util - before.avg_util
    idle_reduction   = before.idle_pct - after.idle_pct
    if util_improvement > 30 and idle_reduction > 40:
        verdict = "[bold green]✔ SIGNIFICANT improvement — GPU pipeline fully optimized[/bold green]"
    elif util_improvement > 10 or idle_reduction > 20:
        verdict = "[yellow]◐ PARTIAL improvement — some gains achieved[/yellow]"
    else:
        verdict = "[red]○ Minimal improvement — check model size and VRAM availability[/red]"

    console.print(f"\n  {verdict}\n")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        prog="gpu-saturate",
        description="Eggshell GPU Saturation Engine — maximize GPU inference utilization",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument("--mode", choices=list(MODES), default="aggressive",
                    help="Saturation intensity")
    ap.add_argument("--duration",    type=int,   default=60,    metavar="SEC")
    ap.add_argument("--model",       default="auto",            metavar="NAME")
    ap.add_argument("--workers",     type=int,   default=None,  metavar="N",
                    help="Pin worker count (disables auto-scaling)")
    ap.add_argument("--target-util", type=int,   default=None,  metavar="PCT")
    ap.add_argument("--no-scale",    action="store_true",
                    help="Disable adaptive worker scaling")
    ap.add_argument("--no-warmup",   action="store_true",
                    help="Skip KV-cache warmup phase")
    ap.add_argument("--benchmark-compare", action="store_true",
                    help=(
                        "Run a BEFORE/AFTER benchmark comparison showing the impact of "
                        "shared KV prefix caching and staggered worker startup. "
                        "Each phase runs for --duration seconds."
                    ))
    args = ap.parse_args()

    # ── Benchmark comparison mode ──────────────────────────────────────────────
    if args.benchmark_compare:
        async def _compare():
            # Resolve model first
            dummy = SaturationEngine(
                mode=MODES[args.mode], model=args.model, duration=1,
                pin_workers=1, target_util=None, no_scale=True, no_warmup=True,
            )
            model = await dummy._pick_model()
            if not model:
                console.print("[red]No Ollama models found.[/red]")
                return
            await run_benchmark_comparison(
                model    = model,
                mode_key = args.mode,
                duration = args.duration,
            )
        try:
            asyncio.run(_compare())
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped.[/yellow]")
        return

    # ── Normal saturation mode ─────────────────────────────────────────────────
    mode = MODES[args.mode]
    console.print(Rule(f"[bold cyan]⚡ GPU SATURATION ENGINE  v{VERSION}[/bold cyan]"))
    console.print(
        f"  Mode [bold]{mode.label}[/bold]   "
        f"workers {args.workers or mode.init_workers}→{mode.max_workers}   "
        f"ctx {mode.num_ctx:,}   "
        f"predict {mode.num_predict if mode.num_predict > 0 else '∞'}   "
        f"duration {args.duration}s"
    )
    console.print()

    engine = SaturationEngine(
        mode=mode,
        model=args.model,
        duration=args.duration,
        pin_workers=args.workers,
        target_util=args.target_util,
        no_scale=args.no_scale,
        no_warmup=args.no_warmup,
    )

    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped.[/yellow]")


if __name__ == "__main__":
    main()
