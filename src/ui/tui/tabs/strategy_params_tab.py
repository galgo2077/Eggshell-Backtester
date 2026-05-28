"""
Strategy Parameters tab — left config panel, third tab.
Hosts the dynamic strategy widget container rebuilt by the composer
whenever the active strategy changes.
Dual-strategy slot buttons are also handled here.
"""
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import TabPane, Button
from textual import on


class StrategyParamsTab(TabPane):
    def __init__(self, **kwargs):
        super().__init__("STRATEGY", **kwargs)

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="dynamic-strategy-container")

    # Dual-strategy slot buttons live inside the dynamic container
    @on(Button.Pressed, "#dual-slot-btn-a")
    def on_dual_slot_a(self) -> None:
        self.app.state.dual_active_slot = "a"
        self.app.rebuild_strategy_and_risk_tabs("DUAL_STRATEGY")

    @on(Button.Pressed, "#dual-slot-btn-b")
    def on_dual_slot_b(self) -> None:
        self.app.state.dual_active_slot = "b"
        self.app.rebuild_strategy_and_risk_tabs("DUAL_STRATEGY")
