"""Pie tab — results panel. Braille-dot asset allocation pie chart."""
from textual.app import ComposeResult
from textual.widgets import TabPane, Static
from textual.containers import VerticalScroll


class PieTab(TabPane):
    def __init__(self, **kwargs):
        super().__init__("PIE", id="tab-pie", **kwargs)

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static("", id="assets-pie")
