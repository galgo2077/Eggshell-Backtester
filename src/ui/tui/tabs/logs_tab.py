"""Logs tab — results panel. Scrollable rich log output."""
from textual.app import ComposeResult
from textual.widgets import TabPane, RichLog


class LogsTab(TabPane):
    def __init__(self, **kwargs):
        super().__init__("LOGS", id="tab-logs", **kwargs)

    def compose(self) -> ComposeResult:
        yield RichLog(id="main-log", highlight=True, markup=True)
