import time

from textual.widgets import Static


class BacktestTimer(Static):
    """Live elapsed-time bar below the 4 stat boxes."""

    def __init__(self) -> None:
        super().__init__("LAST RUN  ──  —", id="backtest-timer")
        self._t0: float | None = None
        self._ticker = None

    # ── public API ────────────────────────────────────────────────────────────

    def start_timer(self) -> None:
        self._t0 = time.time()
        self.styles.color = "#ff00ff"
        self.update("RUNNING  ──  0.00s")
        self._ticker = self.set_interval(0.1, self._tick)

    def stop_timer(self, elapsed: float | None = None) -> None:
        if self._ticker is None and self._t0 is None:
            return  # already stopped — don't overwrite display
        if self._ticker:
            self._ticker.stop()
            self._ticker = None
        secs = elapsed if elapsed is not None else (time.time() - self._t0 if self._t0 else 0.0)
        self._t0 = None
        self.styles.color = "#555555"
        self.update(f"LAST RUN  ──  {self._fmt(secs)}")

    # ── internals ─────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        if self._t0 is not None:
            self.update(f"RUNNING  ──  {self._fmt(time.time() - self._t0)}")

    @staticmethod
    def _fmt(seconds: float) -> str:
        if seconds < 60:
            return f"{seconds:.2f}s"
        m = int(seconds // 60)
        s = seconds % 60
        return f"{m}m {s:.1f}s"
