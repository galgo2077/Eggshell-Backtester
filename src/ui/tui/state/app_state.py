"""
Centralized application state container.
BacktestApp holds one AppState instance; all mutable runtime state lives here.
This separates rendering logic from state mutation.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AppState:
    # Settings persistence
    active_settings: dict   = field(default_factory=dict)
    alloc_values: dict      = field(default_factory=dict)
    skip_save: bool         = True
    loading: bool           = False

    # Run state
    cancelled: bool         = False
    run_final_status: Any   = None

    # Strategy UI
    dual_active_slot: str   = "a"

    # Ollama
    ollama_setup_ok: bool   = False

    # Results (populated after a backtest)
    last_results: dict      = field(default_factory=dict)
    last_trades: list       = field(default_factory=list)
    last_setup_info: dict   = field(default_factory=dict)
    charts: dict            = field(default_factory=dict)
    pie_markup: str         = ""

    # AI analysis cache (rebuilt after each backtest)
    ai_scores_markup: str       = ""
    ai_report_markup: str       = ""
    ai_analysis_running: bool   = False
    ai_model: str               = "plutus"

    # DataTable sort directions keyed by column key
    sort_states: dict       = field(default_factory=dict)

    # Timer handle for "SAVED" feedback (set by composer, None when idle)
    status_reset_timer: Any = None
