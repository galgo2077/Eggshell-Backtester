"""
AI tab — post-backtest intelligent analysis panel.
Displays scoring, pattern observations, recommendations, and an optional
Ollama-enhanced narrative after each backtest run.
Content is rebuilt automatically when a backtest completes, and re-displayed
when the tab is activated.
"""
from textual.app import ComposeResult
from textual.widgets import TabPane, Static, Collapsible, Select, Label
from textual.containers import VerticalScroll, Horizontal

from ..utils.ollama import _SETUP_GLOSSARY, _SETUP_MODEL


class SetupTab(TabPane):
    def __init__(self, **kwargs):
        super().__init__("AI", id="tab-setup", **kwargs)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="setup-scroll"):
            with Horizontal(id="ai-model-row"):
                yield Label("MODEL", id="ai-model-label")
                yield Select(
                    [(_SETUP_MODEL, _SETUP_MODEL)],
                    value=_SETUP_MODEL,
                    id="ai-model-select",
                    allow_blank=False,
                )
            yield Static("", id="setup-status",  classes="setup-status")
            yield Static("", id="setup-scores",  classes="setup-scores")
            yield Static("", id="setup-content", classes="setup-content")
            with Collapsible(title="GLOSSARY", classes="indicator-collapsible", collapsed=True):
                for _term, _defn in _SETUP_GLOSSARY.items():
                    _gt = Static(f"[bold]▸ {_term}[/bold]", classes="glossary-term")
                    _gt.tooltip = _defn
                    yield _gt
