"""
Chart tab — results panel.
Save/Load backtest buttons, per-asset filter, and HTML chart launchers.
Asset filter change delegates to the composer (_apply_asset_filter).
"""
from textual.app import ComposeResult
from textual.widgets import TabPane, Button, Select
from textual.containers import Vertical
from textual import on


class ChartTab(TabPane):
    def __init__(self, **kwargs):
        super().__init__("CHART", id="tab-chart", **kwargs)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Button("SAVE BACKTEST",    id="save-btn")
            yield Button("LOAD BACKTEST",    id="load-btn")
            yield Select([],                 id="asset-chart-select", prompt="SELECT ASSET")
            yield Button("FULL PORTFOLIO CHART",           id="open-chart-main",       variant="success",  classes="chart-btn")
            yield Button("TOP DRAWDOWNS CHART",            id="open-chart-drawdowns",  variant="error",    classes="chart-btn")
            yield Button("CUMULATIVE RETURNS",             id="open-chart-returns",    variant="success",  classes="chart-btn")
            yield Button("CASH FLOW BALANCE",              id="open-chart-cash",       variant="primary",  classes="chart-btn")
            yield Button("PORTFOLIO VALUE",                id="open-chart-value",      variant="default",  classes="chart-btn")
            yield Button("UNDERWATER CHART (DEEP DIVE)",   id="open-chart-underwater", variant="warning",  classes="chart-btn")
            yield Button("ASSET TRADES CHART",             id="open-chart-asset-trades", variant="primary", classes="chart-btn")

    @on(Select.Changed, "#asset-chart-select")
    def on_asset_filter_changed(self, event: Select.Changed) -> None:
        self.app._apply_asset_filter(event.value)
