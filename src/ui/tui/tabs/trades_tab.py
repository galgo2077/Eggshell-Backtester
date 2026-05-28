"""Trades tab — results panel. Shows the trade history DataTable."""
from textual.app import ComposeResult
from textual.widgets import TabPane, DataTable


class TradesTab(TabPane):
    def __init__(self, **kwargs):
        super().__init__("TRADES", id="tab-trades", **kwargs)

    def compose(self) -> ComposeResult:
        table = DataTable(id="trades-table", cursor_type="row")
        table.add_columns("DATE", "TYPE", "SYMBOL", "INVESTED", "QTY", "BUY", "SELL", "TRADE %", "ACCT %")
        yield table
