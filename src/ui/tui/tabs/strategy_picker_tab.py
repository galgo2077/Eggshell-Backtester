"""
Strategy Picker tab — left config panel, first tab.
Renders the strategy selector dropdown and the dual-strategy sub-panel.
Strategy parameter rebuilding is handled by the composer (cross-tab concern).
"""
from textual.app import ComposeResult
from textual.widgets import TabPane, Label, Select
from textual.containers import Vertical, VerticalScroll

from core.constants import STRATEGY_SCHEMAS
from ..utils.helpers import _tip


class StrategyPickerTab(TabPane):
    def __init__(self, **kwargs):
        super().__init__("STRATEGY", **kwargs)

    def compose(self) -> ComposeResult:
        _sub    = [(k.replace("_", " ").title(), k) for k in STRATEGY_SCHEMAS.keys() if k != "DUAL_STRATEGY"]
        _sub_b  = _sub[1][1] if len(_sub) > 1 else _sub[0][1]

        with VerticalScroll(id="strategy-picker-scroll"):
            yield Label("CHOOSE ACTIVE STRATEGY", classes="box-subtitle")
            yield Select(
                [(k.replace("_", " ").title(), k) for k in STRATEGY_SCHEMAS.keys()],
                value=list(STRATEGY_SCHEMAS.keys())[0] if STRATEGY_SCHEMAS else None,
                id="strategy-select",
            )
            with Vertical(id="dual-strategy-panel", classes="hidden"):
                yield Label("SIGNAL CONDITION")
                yield Select(
                    [("AND  — Both signals required", "AND"), ("OR  — Either signal triggers", "OR")],
                    value="AND", id="opt_dual_strategy_condition",
                )
                yield Label("STRATEGY A")
                yield Select(_sub, value="EMA_CROSS", id="opt_dual_strategy_strategy_a")
                yield Label("STRATEGY B")
                yield Select(_sub, value=_sub_b, id="opt_dual_strategy_strategy_b")

    def on_mount(self) -> None:
        self.call_after_refresh(self._fix_scroll_height)

    def on_show(self) -> None:
        self.call_after_refresh(self._fix_scroll_height)

    def _fix_scroll_height(self) -> None:
        try:
            scroll = self.query_one("#strategy-picker-scroll", VerticalScroll)
            scroll.styles.height = "1fr"
            scroll.styles.overflow_y = "scroll"
            scroll.styles.overflow_x = "hidden"
            scroll.refresh(layout=True)
        except Exception:
            pass
