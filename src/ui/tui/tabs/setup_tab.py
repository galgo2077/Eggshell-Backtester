"""
AI tab — full lifecycle intelligent analysis panel.
Displays dual-stage analysis:
1. Pre-execution setup risks and scores
2. Post-backtest scoring, observations, and combined insights.
"""
from textual.app import ComposeResult
from textual.widgets import TabPane, Static, Collapsible, Select, Label
from textual.containers import VerticalScroll, Horizontal, Vertical

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

            with Vertical(id="ai-global-status-section", classes="ai-section"):
                yield Label("[bold dim]AI STATUS[/bold dim]", id="ai-status-header")
                yield Label("[dim]● IDLE[/dim]", id="ai-global-status", classes="ai-global-status")
            
            with Vertical(id="pre-execution-section", classes="ai-section"):
                yield Label("── PRE-EXECUTION ANALYSIS ──", classes="box-title")
                yield Static("", id="pre-exec-status", classes="setup-status")
                yield Static("", id="pre-exec-scores", classes="setup-scores")
                yield Static("", id="pre-exec-content", classes="setup-content")
                
            with Vertical(id="post-execution-section", classes="ai-section"):
                yield Label("── POST-EXECUTION ANALYSIS ──", classes="box-title")
                yield Static("", id="post-exec-status", classes="setup-status")
                yield Static("", id="post-exec-scores", classes="setup-scores")
                yield Static("", id="post-exec-content", classes="setup-content")
                
            with Collapsible(title="GLOSSARY", classes="indicator-collapsible", collapsed=True):
                for _term, _defn in _SETUP_GLOSSARY.items():
                    _gt = Static(f"[bold]▸ {_term}[/bold]", classes="glossary-term")
                    _gt.tooltip = _defn
                    yield _gt

    def update_pre_execution(self, scores_markup: str, content_markup: str):
        try:
            self.query_one("#pre-exec-status").update("")
            self.query_one("#pre-exec-scores").update(scores_markup)
            self.query_one("#pre-exec-content").update(content_markup)
        except Exception:
            pass

    def update_post_execution(self, status: str, scores_markup: str, content_markup: str):
        try:
            self.query_one("#post-exec-status").update(status)
            self.query_one("#post-exec-scores").update(scores_markup)
            self.query_one("#post-exec-content").update(content_markup)
        except Exception:
            pass

    def clear_post_execution(self):
        try:
            self.query_one("#post-exec-status").update("")
            self.query_one("#post-exec-scores").update("")
            self.query_one("#post-exec-content").update("")
        except Exception:
            pass

    def set_phase(self, phase_name: str, is_error: bool = False, is_warn: bool = False):
        try:
            lbl = self.query_one("#ai-global-status", Label)
            color = "red" if is_error else "yellow" if is_warn else "green"
            lbl.update(f"[{color}]● {phase_name}[/{color}]")
        except Exception:
            pass
