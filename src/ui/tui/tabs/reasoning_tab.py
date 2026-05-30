"""
Reasoning tab — Elliot Bollinger live decision explainer.
Only shown when strategy == ELLIOT_BOLLINGER.
"""
from __future__ import annotations

from datetime import datetime
from textual.app import ComposeResult
from textual.widgets import TabPane, RichLog, Static
from textual.containers import Vertical


class ReasoningTab(TabPane):
    def __init__(self, **kwargs):
        super().__init__("REASONING", id="tab-reasoning-pane", **kwargs)

    def compose(self) -> ComposeResult:
        with Vertical(id="reasoning-outer"):
            yield Static(
                "[bold cyan]── ELLIOT BOLLINGER — LIVE DECISION LOG ──[/bold cyan]\n"
                "[dim]Wave structure · Bollinger position · Signal rationale[/dim]",
                id="reasoning-header",
            )
            yield Static("", id="reasoning-confidence")
            yield RichLog(id="reasoning-log", highlight=True, markup=True, wrap=True)

    def on_mount(self) -> None:
        self._show_waiting()

    # ── State helpers ─────────────────────────────────────────────────────────

    def _show_waiting(self) -> None:
        try:
            log = self.query_one("#reasoning-log", RichLog)
            log.clear()
            log.write(
                "[dim]Waiting for backtest to start — "
                "reasoning events will appear here once Elliot Bollinger runs.[/dim]"
            )
        except Exception:
            pass

    def _show_computing(self) -> None:
        try:
            log = self.query_one("#reasoning-log", RichLog)
            log.clear()
            log.write("[dim]▶ Computing Elliot Bollinger reasoning events…[/dim]")
        except Exception:
            pass

    # ── Public API (call from thread-safe context) ────────────────────────────

    def append_event(self, msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        try:
            log = self.query_one("#reasoning-log", RichLog)
            # First real event clears the placeholder text
            log.write(f"[[dim]{ts}[/dim]] {msg}")
        except Exception:
            pass

    def set_confidence(self, label: str, pct: float) -> None:
        color = "green" if pct >= 70 else ("yellow" if pct >= 45 else "red")
        try:
            self.query_one("#reasoning-confidence", Static).update(
                f"[dim]{label}[/dim] [{color}][bold]{pct:.0f}%[/bold][/{color}]"
            )
        except Exception:
            pass

    def clear(self) -> None:
        """Called by composer just before a backtest starts."""
        self._show_computing()
        try:
            self.query_one("#reasoning-confidence", Static).update("")
        except Exception:
            pass

    def show_error(self, msg: str) -> None:
        try:
            log = self.query_one("#reasoning-log", RichLog)
            log.clear()
            log.write(f"[red]Reasoning unavailable: {msg}[/red]")
        except Exception:
            pass


# ── Signal reasoning generator ────────────────────────────────────────────────

def generate_eb_reasoning(symbol: str, sym_df, signals_df) -> list[str]:
    """
    Build a list of Rich-markup reasoning strings from the signal DataFrame.
    Uses price-derived Bollinger and trend approximations — no Ollama calls.
    Always returns at least one event (diagnostic or data).
    """
    events: list[str] = []

    if signals_df is None or signals_df.empty:
        events.append(f"[yellow][REASONING] {symbol}: signals_df is empty — no signals to analyse.[/yellow]")
        return events

    if "close" not in signals_df.columns:
        events.append(
            f"[yellow][REASONING] {symbol}: 'close' column missing from signals_df "
            f"(columns: {list(signals_df.columns)[:8]})[/yellow]"
        )
        return events

    try:
        import pandas as pd
        closes = signals_df["close"]
        buys   = signals_df.get("buy",  pd.Series(False, index=signals_df.index))
        sells  = signals_df.get("sell", pd.Series(False, index=signals_df.index))

        ema20   = closes.ewm(span=20, adjust=False).mean()
        ema50   = closes.ewm(span=50, adjust=False).mean()
        std20   = closes.rolling(20, min_periods=1).std().fillna(0)
        upper   = ema20 + 2 * std20
        lower   = ema20 - 2 * std20

        n_buys  = int(buys.sum())
        n_sells = int(sells.sum())
        n_bars  = len(closes)
        avg_close = float(closes.mean())

        # ── Asset-level summary ──────────────────────────────────────────────
        trend_label = (
            "uptrend"   if float(ema20.iloc[-1]) > float(ema50.iloc[-1])
            else "downtrend" if float(ema20.iloc[-1]) < float(ema50.iloc[-1])
            else "sideways"
        )
        vol_level = "expanding" if float(std20.iloc[-1]) > float(std20.mean()) else "contracting"
        events.append(
            f"[bold cyan]── {symbol} ──[/bold cyan]\n"
            f"  [dim]Bars analysed:[/dim] {n_bars:,}  "
            f"[dim]Avg close:[/dim] {avg_close:.4f}\n"
            f"  [dim]Trend:[/dim] {trend_label}  "
            f"[dim]Volatility:[/dim] {vol_level}\n"
            f"  [dim]Signals generated:[/dim] [green]{n_buys} long[/green]  "
            f"[magenta]{n_sells} exit[/magenta]"
        )

        if n_buys == 0 and n_sells == 0:
            events.append(
                f"[yellow]  No signals for {symbol}.\n"
                "  Possible causes: trend too weak, volatility outside Bollinger threshold,\n"
                "  or wave pivot structure not confirmed.\n"
                "  Check BOLLINGER_SD_RATIO and FAST_EMA parameters.[/yellow]"
            )
            return events

        # ── Per-signal reasoning (first 20 per direction) ────────────────────
        buy_idx  = signals_df.index[buys].tolist()
        sell_idx = signals_df.index[sells].tolist()

        def _bb_position(idx) -> tuple[str, float]:
            c = float(closes.loc[idx])
            u = float(upper.loc[idx])
            l = float(lower.loc[idx])
            band_width = u - l
            pos = (c - l) / band_width if band_width > 0 else 0.5
            if pos < 0.25:  return "near lower band (oversold zone)", 82.0
            if pos < 0.45:  return "below middle band (mean-reversion zone)", 65.0
            if pos < 0.65:  return "near middle band (neutral)", 50.0
            if pos < 0.85:  return "above middle band (momentum zone)", 68.0
            return "near upper band (extension zone)", 75.0

        def _wave_hint(idx, direction: str) -> str:
            i = signals_df.index.get_loc(idx)
            window = closes.iloc[max(0, i - 10) : i + 1]
            if len(window) < 5:
                return "Wave structure: insufficient history"
            swings = sum(
                1 for k in range(1, len(window) - 1)
                if (window.iloc[k] > window.iloc[k-1] and window.iloc[k] > window.iloc[k+1])
                or (window.iloc[k] < window.iloc[k-1] and window.iloc[k] < window.iloc[k+1])
            )
            if direction == "long":
                return ("Wave structure: impulse + retracement detected — continuation probable"
                        if swings >= 3 else "Wave structure: early impulse — entry near wave base")
            else:
                return ("Wave structure: 5-wave extension likely complete — exit confirmed"
                        if swings >= 4 else "Wave structure: momentum slowing — protective exit")

        for idx in buy_idx[:20]:
            bb_desc, conf = _bb_position(idx)
            wave_hint = _wave_hint(idx, "long")
            trend_ctx = (
                "aligned with trend (EMA stack)" if float(ema20.loc[idx]) > float(ema50.loc[idx])
                else "counter-trend — higher risk"
            )
            events.append(
                f"[bold green]LONG SETUP — {symbol}[/bold green]\n"
                f"  [dim]Bollinger:[/dim] {bb_desc}\n"
                f"  [dim]{wave_hint}[/dim]\n"
                f"  [dim]Trend:[/dim] {trend_ctx}\n"
                f"  [dim]Confidence:[/dim] [green]{conf:.0f}%[/green]  "
                f"[dim]Close:[/dim] {float(closes.loc[idx]):.4f}"
            )

        if len(buy_idx) > 20:
            events.append(f"[dim]  … {len(buy_idx) - 20} additional long signals (not shown)[/dim]")

        for idx in sell_idx[:20]:
            bb_desc, _ = _bb_position(idx)
            wave_hint = _wave_hint(idx, "exit")
            events.append(
                f"[bold magenta]EXIT SIGNAL — {symbol}[/bold magenta]\n"
                f"  [dim]Bollinger:[/dim] {bb_desc}\n"
                f"  [dim]{wave_hint}[/dim]\n"
                f"  [dim]Close:[/dim] {float(closes.loc[idx]):.4f}"
            )

        if len(sell_idx) > 20:
            events.append(f"[dim]  … {len(sell_idx) - 20} additional exit signals (not shown)[/dim]")

    except Exception as exc:
        events.append(f"[red][REASONING ERROR] {exc}[/red]")

    return events
