"""Stats tab — results panel. Extended metrics and per-symbol breakdown table."""
from textual.app import ComposeResult
from textual.widgets import TabPane, Label, DataTable, Static
from textual.containers import Horizontal, Vertical, VerticalScroll


class StatsTab(TabPane):
    def __init__(self, **kwargs):
        super().__init__("STATS", id="tab-stats", **kwargs)

    def compose(self) -> ComposeResult:
        with Horizontal(classes="chart-info-row"):
            with VerticalScroll(id="ext-metrics"):
                yield Label("── EXTENDED METRICS ──", classes="box-title")
                yield Static("", id="ext-metrics-content")
            with Vertical(id="sym-breakdown"):
                yield Label("── PER SYMBOL ──", classes="box-title")
                sym_table = DataTable(id="symbol-table", cursor_type="row")
                sym_table.add_columns("SYMBOL", "TRADES", "WIN RATE", "TOTAL %")
                yield sym_table
