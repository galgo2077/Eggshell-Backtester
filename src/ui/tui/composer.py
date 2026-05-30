"""
BacktestApp — central TUI orchestrator.

Responsibilities:
  • Assemble all tabs and lay out the two-panel UI
  • Manage shared AppState
  • Route cross-tab events (strategy select → params rebuild, etc.)
  • Drive the backtest pipeline (data → signals → engine → results)
  • Persist / restore UI settings
  • Handle save/load backtest sessions
"""
import os
import json
import time
import webbrowser
from datetime import datetime
from threading import Thread

import pandas as pd

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual import on
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Header, Footer, Button, Label, Static, Input,
    Select, DataTable, TabbedContent, TabPane,
    Switch, Collapsible, ProgressBar, RichLog, Checkbox,
)

from binance_service.dataframe import Dataframe
from core.signal_logic import SignalLogic
from core.backtest_engine import BacktestEngine
from core.constants import STRATEGY_SCHEMAS
from analysis.modes import MONTE_CARLO, RANDOM_WALK, REAL_MARKET_BACKTEST, normalize_mode
from graphs.montecarlo_graphs import generate_montecarlo_graphs

from .theme.styles import APP_CSS
from .state.app_state import AppState
from .components.calendar import CalendarWidget
from .components.backtest_timer import BacktestTimer
from .components.modals import SaveNameModal, LoadBacktestModal, AllocModal, ChartUrlModal
from .utils.helpers import _REPORTS_ROOT, _chart_url, _tip, ensure_chart_server
from .utils.ollama import (
    _SETUP_MODEL, _ollama_model_available, _ollama_generate,
    _highlight_keywords, _list_ollama_models,
)
from ai.orchestrator import AIAnalysisOrchestrator
from .tabs.strategy_picker_tab import StrategyPickerTab
from .tabs.data_tab import DataTab
from .tabs.strategy_params_tab import StrategyParamsTab
from .tabs.risk_tab import RiskTab
from .tabs.trades_tab import TradesTab
from .tabs.chart_tab import ChartTab
from .tabs.stats_tab import StatsTab
from .tabs.pie_tab import PieTab
from .tabs.setup_tab import SetupTab
from .tabs.logs_tab import LogsTab
from .tabs.reasoning_tab import ReasoningTab, generate_eb_reasoning


CHART_LAYOUTS = {
    MONTE_CARLO: {
        "select": False,
        "buttons": {
            "open-chart-main": "mc_path_cloud",
            "open-chart-drawdowns": "mc_drawdown_distribution",
            "open-chart-returns": "mc_terminal_distribution",
            "open-chart-cash": "mc_3d",
            "open-chart-value": "mc_percentiles",
            "open-chart-underwater": "mc_percentiles",
            "open-chart-asset-trades": None,
        },
        "labels": {
            "open-chart-main": "SIMULATION PATH CLOUD",
            "open-chart-drawdowns": "DRAWDOWN DISTRIBUTION",
            "open-chart-returns": "TERMINAL VALUE DISTRIBUTION",
            "open-chart-cash": "3D SIMULATION SPACE",
            "open-chart-value": "PERCENTILE ENVELOPE",
            "open-chart-underwater": "CONFIDENCE BANDS",
        },
    },
    RANDOM_WALK: {
        "select": False,
        "buttons": {
            "open-chart-main": "rw_paths",
            "open-chart-drawdowns": "rw_drift_volatility",
            "open-chart-returns": "rw_drift_volatility",
            "open-chart-cash": None,
            "open-chart-value": "rw_paths",
            "open-chart-underwater": None,
            "open-chart-asset-trades": None,
        },
        "labels": {
            "open-chart-main": "STOCHASTIC PATHS",
            "open-chart-drawdowns": "VOLATILITY SPREAD",
            "open-chart-returns": "DRIFT ANALYSIS",
            "open-chart-value": "RANDOM TRAJECTORY CLOUD",
        },
    },
    REAL_MARKET_BACKTEST: {
        "select": True,
        "buttons": {
            "open-chart-main": "main",
            "open-chart-drawdowns": "drawdowns",
            "open-chart-returns": "returns",
            "open-chart-cash": "cash",
            "open-chart-value": "value",
            "open-chart-underwater": "underwater",
            "open-chart-asset-trades": "trades",
        },
        "labels": {},
    },
}


class BacktestApp(App):
    SETTINGS_FILE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
        "config", "ui_settings.json",
    )
    CSS = APP_CSS

    BINDINGS = [
        Binding("ctrl+q", "quit",         "QUIT"),
        Binding("ctrl+c", "quit",         "QUIT"),
        Binding("r",      "run",          "RUN SEQUENCE"),
        Binding("[",      "shrink_panel", "◀ SHRINK"),
        Binding("]",      "grow_panel",   "GROW ▶"),
    ]

    _PANEL_PRESETS = [25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75]
    _panel_idx: int = 4  # default → 45

    # ── Initialisation ────────────────────────────────────────────────────────

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.state = AppState()
        self._debug_path = os.path.join(os.path.dirname(self.SETTINGS_FILE), "debug_save.log")
        self._debug("__init__ done")

    # Convenience accessors that keep old call-sites working ─────────────────
    @property
    def _active_settings(self) -> dict:
        return self.state.active_settings

    @_active_settings.setter
    def _active_settings(self, v: dict):
        self.state.active_settings = v

    @property
    def _alloc_values(self) -> dict:
        return self.state.alloc_values

    @_alloc_values.setter
    def _alloc_values(self, v: dict):
        self.state.alloc_values = v

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.title = "EGGSHELL BACKTESTER PROBER version 1.2"
        self._debug("on_mount → scheduling _load_ui_settings")
        chart_base = ensure_chart_server()
        self._debug(f"chart server ready: {chart_base}")
        self.call_after_refresh(self._load_ui_settings)
        self.call_after_refresh(self._init_eb_tab_state)
        Thread(target=self._check_ollama_setup, daemon=True).start()
        Thread(target=self._warmup_inference_pool, daemon=True).start()

    def _init_eb_tab_state(self) -> None:
        try:
            strat = str(self.query_one("#strategy-select", Select).value)
            if strat != "ELLIOT_BOLLINGER":
                self.query_one("#results-tabs", TabbedContent).hide_tab("tab-reasoning-pane")
        except Exception:
            try:
                self.query_one("#results-tabs", TabbedContent).hide_tab("tab-reasoning-pane")
            except Exception:
                pass

    # ── Layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-layout"):
            # ── Left: config panel ────────────────────────────────────────────
            with Vertical(classes="btop-box", id="config-column"):
                yield Label("── EGGSHELL PROBER v1.2 ──", classes="box-title")
                with TabbedContent(id="config-tabs"):
                    yield StrategyPickerTab()
                    yield DataTab()
                    yield StrategyParamsTab()
                    yield RiskTab()

                with Vertical(id="config-footer"):
                    yield Label("READY", id="status-label")
                    yield Static("", id="mc-progress-panel")
                    yield ProgressBar(id="main-progress", total=100, show_eta=True)
                    with Horizontal(id="btn-row"):
                        yield Button("EXECUTE SEQUENCE (R)", id="run-btn", variant="primary")
                        yield Button("CANCEL", id="cancel-btn", variant="error")

                yield CalendarWidget(target_input_id="start-date-input", id="start-calendar", classes="hidden")
                yield CalendarWidget(target_input_id="end-date-input",   id="end-calendar",   classes="hidden")

            # ── Right: results / analytics panel ─────────────────────────────
            with Vertical(classes="btop-box", id="stats-column"):
                yield Label("── REAL-TIME ANALYTICS ──", classes="box-title")
                yield Label(
                    "[bold magenta]R[/bold magenta] RUN  "
                    "[dim]│[/dim]  "
                    "[bold magenta]\\[ / ][/bold magenta] RESIZE PANEL  "
                    "[dim]│[/dim]  "
                    "[bold magenta]Ctrl+Q[/bold magenta] QUIT",
                    id="top-shortcuts",
                )
                with Horizontal(id="stats-row"):
                    with Vertical(classes="stat-container"):
                        yield Label("TOTAL ROI")
                        yield Label("0.00%", id="stat-return", classes="stat-value")
                    with Vertical(classes="stat-container"):
                        yield Label("WIN RATE")
                        yield Label("0.0%", id="stat-winrate", classes="stat-value")
                    with Vertical(classes="stat-container"):
                        yield Label("TRADES")
                        yield Label("0", id="stat-trades", classes="stat-value")
                    with Vertical(classes="stat-container"):
                        yield Label("P&L")
                        yield Label("$0.00", id="stat-final", classes="stat-value")

                yield BacktestTimer()

                with TabbedContent(id="results-tabs"):
                    yield TradesTab()
                    yield ChartTab()
                    yield StatsTab()
                    yield PieTab()
                    yield SetupTab()
                    yield LogsTab()
                    yield ReasoningTab()
        yield Footer()

    # ── Strategy rebuild ──────────────────────────────────────────────────────

    def rebuild_strategy_and_risk_tabs(self, strategy_name: str) -> None:
        schema = STRATEGY_SCHEMAS.get(strategy_name, STRATEGY_SCHEMAS["EMA_CROSS"])
        try:
            container = self.query_one("#dynamic-strategy-container", VerticalScroll)
            container.remove_children()

            if strategy_name == "DUAL_STRATEGY":
                saved = self.state.active_settings
                try:
                    a_name = self.query_one("#opt_dual_strategy_strategy_a", Select).value or "EMA_CROSS"
                except Exception:
                    a_name = "EMA_CROSS"
                try:
                    b_name = self.query_one("#opt_dual_strategy_strategy_b", Select).value or "ELLIOT_BOLLINGER"
                except Exception:
                    b_name = "ELLIOT_BOLLINGER"

                slot = self.state.dual_active_slot
                name = a_name if slot == "a" else b_name

                btn_a = Button("◀ STRATEGY A", id="dual-slot-btn-a")
                btn_b = Button("STRATEGY B ▶",  id="dual-slot-btn-b")
                if slot == "a":
                    btn_a.add_class("active-slot")
                else:
                    btn_b.add_class("active-slot")
                container.mount(Horizontal(btn_a, btn_b, classes="sel-btn-row"))

                slot_schema = STRATEGY_SCHEMAS.get(name, {})
                for section_name, fields in slot_schema.items():
                    slot_widgets = []
                    for field_name, field_info in fields.items():
                        w_id = f"opt_dual_{slot}_{field_name}".lower()
                        val  = saved.get(w_id, field_info["default"])
                        slot_widgets.append(Label(field_info["label"]))
                        if field_info["type"] == "bool":
                            slot_widgets.append(Switch(value=bool(val), id=w_id))
                        else:
                            slot_widgets.append(Input(str(val), id=w_id))
                    if slot_widgets:
                        title = f"STRATEGY {slot.upper()} — {name.replace('_', ' ')} — {section_name}"
                        container.mount(Collapsible(*slot_widgets, title=title, classes="indicator-collapsible"))

                if slot == "a":
                    sl_val = saved.get("opt_dual_a_sl_stop",        "0.0")
                    tp_val = saved.get("opt_dual_a_tp_stop",        "0.0")
                    trail  = saved.get("opt_dual_a_sl_trail",       False)
                    exit_v = saved.get("opt_dual_a_stop_exit_price", "stop")
                    dual_stop_widgets = [
                        Label("STOP LOSS  (% from entry, 0 = off)"),
                        Input(str(sl_val), id="opt_dual_a_sl_stop"),
                        Horizontal(Label("TRAILING STOP"), Switch(bool(trail), id="opt_dual_a_sl_trail"), classes="inline-field"),
                        Label("TAKE PROFIT  (% from entry, 0 = off)"),
                        Input(str(tp_val), id="opt_dual_a_tp_stop"),
                        Label("STOP EXIT PRICE"),
                        Select(
                            [("Stop Price (exact)", "stop"), ("Close Price", "close"), ("Open Price (next bar)", "open")],
                            value=exit_v, id="opt_dual_a_stop_exit_price",
                        ),
                    ]
                    container.mount(Collapsible(*dual_stop_widgets, title="STOP ORDERS", classes="indicator-collapsible"))
                return

            saved = self.state.active_settings
            for section_name, fields in schema.items():
                if section_name == "RISK":
                    continue
                widgets = []
                for field_name, field_info in fields.items():
                    w_id = f"opt_{strategy_name}_{field_name}".lower()
                    val  = saved.get(w_id, field_info["default"])
                    widgets.append(Label(field_info["label"]))
                    if field_info["type"] == "bool":
                        widgets.append(Switch(value=bool(val), id=w_id))
                    else:
                        widgets.append(Input(str(val), id=w_id))
                if widgets:
                    container.mount(Collapsible(*widgets, title=f"{section_name} CONFIGURATION", classes="indicator-collapsible"))

            risk_extra = schema.get("RISK", {})
            if risk_extra:
                risk_widgets = []
                for field_name, field_info in risk_extra.items():
                    w_id = f"opt_{strategy_name}_{field_name}".lower()
                    val  = saved.get(w_id, field_info["default"])
                    risk_widgets.append(Label(field_info["label"]))
                    if field_info["type"] == "bool":
                        risk_widgets.append(Switch(value=bool(val), id=w_id))
                    else:
                        risk_widgets.append(Input(str(val), id=w_id))
                container.mount(Collapsible(*risk_widgets, title="RISK CONFIGURATION", classes="indicator-collapsible"))

            strat_lc = strategy_name.lower()
            sl_val   = saved.get(f"opt_{strat_lc}_sl_stop",        "0.0")
            tp_val   = saved.get(f"opt_{strat_lc}_tp_stop",        "0.0")
            trail    = saved.get(f"opt_{strat_lc}_sl_trail",       False)
            exit_v   = saved.get(f"opt_{strat_lc}_stop_exit_price", "stop")
            stop_widgets = [
                Label("STOP LOSS  (% from entry, 0 = off)"),
                Input(str(sl_val), id=f"opt_{strat_lc}_sl_stop"),
                Horizontal(Label("TRAILING STOP"), Switch(bool(trail), id=f"opt_{strat_lc}_sl_trail"), classes="inline-field"),
                Label("TAKE PROFIT  (% from entry, 0 = off)"),
                Input(str(tp_val), id=f"opt_{strat_lc}_tp_stop"),
                Label("STOP EXIT PRICE"),
                Select(
                    [("Stop Price (exact)", "stop"), ("Close Price", "close"), ("Open Price (next bar)", "open")],
                    value=exit_v, id=f"opt_{strat_lc}_stop_exit_price",
                ),
            ]
            container.mount(Collapsible(*stop_widgets, title="STOP ORDERS", classes="indicator-collapsible"))
        except Exception:
            pass

    def _collect_dual_slot_params(self, slot: str, strategy_name: str) -> dict:
        schema = STRATEGY_SCHEMAS.get(strategy_name, {})
        result = {}
        for section in schema.values():
            for field, info in section.items():
                w_id = f"opt_dual_{slot}_{field}".lower()
                try:
                    val = self.query_one(f"#{w_id}").value
                    if info["type"] == "bool":
                        result[field] = bool(val)
                    elif info["type"] == "int":
                        result[field] = int(val) if str(val).strip() else info["default"]
                    elif info["type"] == "float":
                        result[field] = float(val) if str(val).strip() else info["default"]
                except Exception:
                    result[field] = info["default"]
        return result

    # ── Cross-tab event routing ───────────────────────────────────────────────

    @on(Select.Changed, "#strategy-select")
    def on_strategy_changed(self, event: Select.Changed) -> None:
        if event.value:
            self.rebuild_strategy_and_risk_tabs(event.value)
            try:
                dual_panel = self.query_one("#dual-strategy-panel")
                if event.value == "DUAL_STRATEGY":
                    dual_panel.remove_class("hidden")
                else:
                    dual_panel.add_class("hidden")
            except Exception:
                pass
            self._update_eb_tab_visibility(str(event.value))

    def _update_eb_tab_visibility(self, strategy_name: str) -> None:
        is_eb = strategy_name == "ELLIOT_BOLLINGER"
        try:
            tabbed = self.query_one("#results-tabs", TabbedContent)
            if is_eb:
                tabbed.show_tab("tab-reasoning-pane")
            else:
                tabbed.hide_tab("tab-reasoning-pane")
        except Exception:
            pass
        try:
            logs_tab = self.query_one(LogsTab)
            if is_eb:
                logs_tab.start_ollama_monitor()
            else:
                logs_tab.stop_ollama_monitor()
        except Exception:
            pass

    @on(Select.Changed, "#opt_dual_strategy_strategy_a")
    def on_dual_a_changed(self, event: Select.Changed) -> None:
        if not event.value:
            return
        try:
            if self.query_one("#strategy-select", Select).value != "DUAL_STRATEGY":
                return
        except Exception:
            return
        self.rebuild_strategy_and_risk_tabs("DUAL_STRATEGY")

    @on(Select.Changed, "#opt_dual_strategy_strategy_b")
    def on_dual_b_changed(self, event: Select.Changed) -> None:
        if not event.value:
            return
        try:
            if self.query_one("#strategy-select", Select).value != "DUAL_STRATEGY":
                return
        except Exception:
            return
        self.rebuild_strategy_and_risk_tabs("DUAL_STRATEGY")

    @on(TabbedContent.TabActivated, "#config-tabs")
    def on_config_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if getattr(event.pane, "id", None) == "tab-risk-pane":
            self._rebuild_allocation_inputs(reset=False)
            try:
                self.query_one("#results-tabs", TabbedContent).active = "tab-pie"
            except Exception:
                pass

    @on(TabbedContent.TabActivated, "#results-tabs")
    def on_results_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        pane_id = getattr(event.pane, "id", None)
        if pane_id == "tab-pie":
            markup = self._draw_pie_chart()
            self.state.pie_markup = markup
            try:
                self.query_one("#assets-pie", Static).update(
                    markup or "[dim #555555]  Select 2+ assets to preview allocation.[/dim #555555]"
                )
            except Exception:
                pass
        elif pane_id == "tab-setup":
            self._refresh_setup_tab()

    @on(Select.Changed, "#ai-model-select")
    def on_ai_model_changed(self, event: Select.Changed) -> None:
        if event.value and str(event.value) != self.state.ai_model:
            self.state.ai_model        = str(event.value)
            self.state.ollama_setup_ok = True
            if self.state.last_results and not self.state.ai_analysis_running:
                self.state.ai_scores_markup = ""
                self.state.ai_report_markup = ""
                Thread(target=self._run_ai_analysis, daemon=True).start()

    @on(DataTable.HeaderSelected)
    def on_header_click(self, event: DataTable.HeaderSelected):
        current_asc = self.state.sort_states.get(event.column_key, True)
        new_asc     = not current_asc
        self.state.sort_states[event.column_key] = new_asc

        def sort_key(value):
            if not isinstance(value, str):
                return value
            clean = value.replace("$", "").replace("%", "")
            while "[" in clean and "]" in clean:
                start = clean.find("[")
                end   = clean.find("]") + 1
                clean = clean[:start] + clean[end:]
            try:
                return float(clean)
            except ValueError:
                return clean.lower()

        if event.data_table.row_count:
            event.data_table.sort(event.column_key, key=sort_key, reverse=not new_asc)

    # ── Global auto-save hooks ─────────────────────────────────────────────────

    @on(Input.Changed)
    def _on_input_changed(self, event: Input.Changed) -> None:
        self._debug(f"Input.Changed: {event.input.id}={event.value}")
        # Validate opt_ inputs (strategy param widgets in StrategyParamsTab)
        w_id = event.input.id or ""
        if w_id.startswith("opt_"):
            self._validate_opt_input(event)
        self._save()

    @on(Switch.Changed)
    def _on_switch_changed(self, event: Switch.Changed) -> None:
        self._debug(f"Switch.Changed: {event.switch.id}={event.value}")
        if event.switch.id == "vbt-sell-at-end":
            self._set_stop_widgets_disabled(event.value)
        self._save()

    @on(Select.Changed)
    def _on_select_changed(self, event: Select.Changed) -> None:
        self._debug(f"Select.Changed: {event.select.id}={event.value}")
        self._save()

    def _validate_opt_input(self, event: Input.Changed) -> None:
        w_id = event.input.id or ""
        val  = event.value.strip()
        inpt = event.input
        try:
            strategy_name = self.query_one("#strategy-select", Select).value
            prefix        = f"opt_{strategy_name.lower()}_"
            if not w_id.startswith(prefix):
                return
            field_key  = w_id[len(prefix):].upper()
            schema     = STRATEGY_SCHEMAS.get(strategy_name, {})
            field_info = None
            for section_fields in schema.values():
                if field_key in section_fields:
                    field_info = section_fields[field_key]
                    break
            if field_info is None:
                return
            if not val:
                raise ValueError("REQUIRED")
            if field_info["type"] == "int":
                int(val)
            elif field_info["type"] == "float":
                float(val)
            inpt.styles.color = "#00ff00"
        except Exception:
            inpt.styles.color = "#ff0000"

    def _set_stop_widgets_disabled(self, disabled: bool) -> None:
        _suffixes = ("_sl_stop", "_tp_stop", "_sl_trail", "_stop_exit_price")
        for widget in self.query("Input, Switch, Select"):
            wid = getattr(widget, "id", "") or ""
            if any(wid.endswith(sfx) for sfx in _suffixes):
                widget.disabled = disabled

    # ── Persist / restore ─────────────────────────────────────────────────────

    def _save(self):
        if self.state.loading:
            self._debug("_save SKIPPED (loading=True)")
            return
        if self.state.skip_save:
            self._debug("_save SKIPPED (skip_save=True)")
            return
        try:
            data = dict(self.state.active_settings)
            for w in self.query("Input, Select, Switch"):
                if w.id:
                    v = w.value
                    if v.__class__.__name__ == "NoSelection":
                        v = ""
                    data[w.id] = v
            for k, v in self.state.alloc_values.items():
                data[f"alloc-{k}"] = v
            data["assets"] = [
                str(cb.label) for cb in self.query("#asset-checkbox-container Checkbox") if cb.value
            ]
            self.state.active_settings = data
            tmp = self.SETTINGS_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, self.SETTINGS_FILE)
            self._debug(f"_save OK → {len(data)} keys written")
        except Exception as e:
            self._debug(f"_save EXCEPTION: {e}")
        self._saved_feedback()

    def _saved_feedback(self):
        try:
            lbl = self.query_one("#status-label", Label)
            lbl.update("✓ SAVED")
            if self.state.status_reset_timer:
                self.state.status_reset_timer.stop()
            self.state.status_reset_timer = self.set_timer(2.0, lambda: lbl.update("READY"))
        except Exception:
            pass

    def _load_ui_settings(self):
        default = list(STRATEGY_SCHEMAS.keys())[0] if STRATEGY_SCHEMAS else None
        if not os.path.exists(self.SETTINGS_FILE):
            self._debug("_load: no file → rebuild with defaults")
            self.rebuild_strategy_and_risk_tabs(default)
            self.state.skip_save = False
            return

        self.state.loading = True
        loaded: dict = {}
        try:
            with open(self.SETTINGS_FILE) as f:
                loaded = json.load(f)
            self.state.active_settings.update(loaded)
            self._debug(f"_load: read {len(loaded)} keys from file")
        except Exception as e:
            self._debug(f"_load: json load failed: {e}")

        try:
            strat = loaded.get("strategy-select", default)
            self._debug(f"_load: strategy={strat}")
            self.rebuild_strategy_and_risk_tabs(strat)
            try:
                dp = self.query_one("#dual-strategy-panel")
                (dp.remove_class if strat == "DUAL_STRATEGY" else dp.add_class)("hidden")
            except Exception:
                pass

            self.state.skip_save  = True
            restored_count = 0
            for w in self.query("Input, Select, Switch"):
                if w.id and w.id in loaded:
                    try:
                        w.value = loaded[w.id]
                        restored_count += 1
                    except Exception as e:
                        self._debug(f"_load: FAILED to restore {w.id}={loaded[w.id]!r}: {e}")
            self._debug(f"_load: restored {restored_count} widgets")

            saved = set(loaded.get("assets", ["BTCUSDT"]))
            for cb in self.query("#asset-checkbox-container Checkbox"):
                cb.value = str(cb.label) in saved
            self._rebuild_allocation_inputs(reset=False)
            self._debug("_load: done")
        except Exception as e:
            self._debug(f"_load: outer exception: {e}")
        finally:
            self.state.loading   = False
            self.state.skip_save = False
            try:
                sell_at_end_on = bool(self.query_one("#vbt-sell-at-end", Switch).value)
                if sell_at_end_on:
                    self._set_stop_widgets_disabled(True)
            except Exception:
                pass

    # ── Run button ─────────────────────────────────────────────────────────────

    @on(Button.Pressed, "#run-btn")
    def on_run_pressed(self) -> None:
        self._save()
        self.action_run()

    def action_run(self) -> None:
        params, error = self._collect_params()
        if error:
            self.notify(error, severity="error")
            return
        self.state.cancelled = False
        run_btn = self.query_one("#run-btn", Button)
        can_btn = self.query_one("#cancel-btn", Button)
        run_btn.disabled = True
        run_btn.label    = "PROCESSING..."
        can_btn.add_class("visible")
        progress = self.query_one("#main-progress", ProgressBar)
        progress.add_class("visible")
        progress.progress = 0
        self.query_one("#results-tabs", TabbedContent).active = "tab-logs"
        self.notify("INITIATING PORTFOLIO SEQUENCE...")
        self.query_one(BacktestTimer).start_timer()
        Thread(target=self._run_backtest, kwargs=params, daemon=True).start()

    # ── Parameter collection ──────────────────────────────────────────────────

    def _collect_params(self) -> tuple[dict | None, str | None]:
        try:
            try:
                _dsv        = self.query_one("#data-source-select", Select).value
                data_source = str(_dsv) if _dsv and _dsv.__class__.__name__ != "NoSelection" else "REAL"
            except Exception:
                data_source = "REAL"

            assets = [
                str(cb.label)
                for cb in self.query("#asset-checkbox-container Checkbox")
                if cb.value
            ]
            if not assets:
                if data_source == "REAL":
                    return None, "SELECT AT LEAST ONE ASSET, CAPTAIN."
                return None, "SELECT AT LEAST ONE SYNTHETIC SERIES, CAPTAIN."

            if data_source == "RANDOM_WALK":
                interval = str(self.query_one("#rw-interval-select", Select).value or "1h")
                try:
                    balance = float(self.query_one("#rw-balance-input", Input).value or "1000")
                except Exception:
                    balance = 1000.0
            elif data_source == "MONTE_CARLO":
                interval = str(self.query_one("#mc-interval-select", Select).value or "1h")
                try:
                    balance = float(self.query_one("#mc-balance-input", Input).value or "1000")
                except Exception:
                    balance = 1000.0
            else:
                interval = self.query_one("#interval-select", Select).value
                balance  = float(self.query_one("#balance-input", Input).value or "1000")

            size       = float(self.query_one("#size-input", Input).value or "20")
            start_date = self.query_one("#start-date-input", Input).value
            end_date   = self.query_one("#end-date-input", Input).value or None

            strategy_name = self.query_one("#strategy-select", Select).value
            adv_params    = {"STRATEGY": strategy_name}
            schema        = STRATEGY_SCHEMAS.get(strategy_name, STRATEGY_SCHEMAS["EMA_CROSS"])
            all_fields: dict = {}
            for section in ["STRATEGY", "RISK"]:
                all_fields.update(schema.get(section, {}))
            for field, info in all_fields.items():
                w_id = f"opt_{strategy_name}_{field}".lower()
                try:
                    val = self.query_one(f"#{w_id}").value
                    if info["type"] == "bool":
                        adv_params[field] = bool(val)
                    elif info["type"] == "int":
                        adv_params[field] = int(val) if str(val).strip() else info["default"]
                    elif info["type"] == "float":
                        adv_params[field] = float(val) if str(val).strip() else info["default"]
                    elif info["type"] == "str":
                        adv_params[field] = str(val) if val and val is not Select.BLANK else info["default"]
                except Exception:
                    if w_id in self.state.active_settings:
                        adv_params[field] = self.state.active_settings[w_id]
                    else:
                        adv_params[field] = info["default"]

            # Pass selected AI model to strategy so EB uses the TUI-selected model.
            adv_params["AI_MODEL"] = self.state.ai_model or "qwen2.5:0.5b"

            if strategy_name == "DUAL_STRATEGY":
                a_name = adv_params.get("STRATEGY_A", "EMA_CROSS")
                b_name = adv_params.get("STRATEGY_B", "ELLIOT_BOLLINGER")
                adv_params["PARAMS_A"] = self._collect_dual_slot_params("a", a_name)
                adv_params["PARAMS_B"] = self._collect_dual_slot_params("b", b_name)

            per_symbol_alloc = None
            if data_source == "REAL" and len(assets) >= 2:
                per_symbol_alloc = {
                    a: self.state.alloc_values.get(a, round(100.0 / len(assets), 2))
                    for a in assets
                }
                total_alloc = sum(per_symbol_alloc.values())
                if abs(total_alloc - 100.0) > 0.5:
                    return None, f"ALLOCATION MUST SUM TO 100% (CURRENTLY {total_alloc:.1f}%)"

            data_config: dict = {}
            if data_source == "RANDOM_WALK":
                try:
                    data_config = {
                        "n_bars":      int(self.query_one("#rw-n-bars",    Input).value or "1000"),
                        "start_price": float(self.query_one("#rw-start-price", Input).value or "100.0"),
                        "drift":       float(self.query_one("#rw-drift",    Input).value or "0.05"),
                        "volatility":  float(self.query_one("#rw-volatility", Input).value or "2.0"),
                        "seed":        int(self.query_one("#rw-seed",       Input).value or "-1"),
                    }
                except Exception:
                    data_config = {"n_bars": 1000, "start_price": 100.0, "drift": 0.05, "volatility": 2.0, "seed": -1}
            elif data_source == "MONTE_CARLO":
                try:
                    data_config = {
                        "n_sims":      int(self.query_one("#mc-n-sims",    Input).value or "50"),
                        "n_bars":      int(self.query_one("#mc-n-bars",    Input).value or "1000"),
                        "start_price": float(self.query_one("#mc-start-price", Input).value or "100.0"),
                        "drift":       float(self.query_one("#mc-drift",    Input).value or "0.05"),
                        "volatility":  float(self.query_one("#mc-volatility", Input).value or "2.0"),
                        "seed":        int(self.query_one("#mc-seed",       Input).value or "-1"),
                    }
                except Exception:
                    data_config = {"n_sims": 50, "n_bars": 1000, "start_price": 100.0, "drift": 0.05, "volatility": 2.0, "seed": -1}

            def _finput(widget_id, default=0.0):
                try:
                    return float(self.query_one(f"#{widget_id}", Input).value or str(default))
                except Exception:
                    return default

            def _sval(widget_id, default=""):
                try:
                    v = self.query_one(f"#{widget_id}", Select).value
                    return str(v) if v and v.__class__.__name__ != "NoSelection" else default
                except Exception:
                    return default

            _stop_exit_map = {"stop": 0, "close": 1, "open": 2}
            _opposite_map  = {"reverse": 4, "close": 3, "ignore": 0, "add": 1}
            _dir_map       = {"longonly": 0, "shortonly": 1, "both": 2}
            _conflict_map  = {"ignore": 0, "entry": 1, "exit": 2, "opposite": 4}

            try:
                cd_v     = self.query_one("#cooldown-input", Input).value
                cooldown = int(float(cd_v)) if cd_v and cd_v.strip() else 0
            except Exception:
                cooldown = 0

            strat_lc  = "dual_a" if str(strategy_name) == "DUAL_STRATEGY" else str(strategy_name).lower()
            sl_pct    = _finput(f"opt_{strat_lc}_sl_stop")
            tp_pct    = _finput(f"opt_{strat_lc}_tp_stop")
            try:
                sl_trail = bool(self.query_one(f"#opt_{strat_lc}_sl_trail", Switch).value)
            except Exception:
                sl_trail = False
            stop_exit = _sval(f"opt_{strat_lc}_stop_exit_price", "stop")

            vbt_params = {
                "fees":                _finput("vbt-fees")     / 100.0,
                "fixed_fees":          _finput("vbt-fixed-fees"),
                "slippage":            _finput("vbt-slippage") / 100.0,
                "sl_stop":             sl_pct / 100.0 if sl_pct > 0 else float("nan"),
                "sl_trail":            sl_trail,
                "tp_stop":             tp_pct / 100.0 if tp_pct > 0 else float("nan"),
                "stop_exit_price":     _stop_exit_map.get(stop_exit, 0),
                "allow_partial":       bool(self.query_one("#vbt-allow-partial", Switch).value),
                "lock_cash":           bool(self.query_one("#vbt-lock-cash",     Switch).value),
                "reject_prob":         _finput("vbt-reject-prob") / 100.0,
                "min_size":            _finput("vbt-min-size"),
                "max_size":            _finput("vbt-max-size") or float("inf"),
                "upon_opposite_entry": _opposite_map.get(_sval("vbt-upon-opposite-entry", "reverse"), 4),
                "direction":           _dir_map.get(_sval("vbt-direction", "longonly"), 0),
                "cash_sharing":        bool(self.query_one("#vbt-cash-sharing", Switch).value),
                "size_type":           _sval("vbt-size-type", "value"),
                "upon_long_conflict":  _conflict_map.get(_sval("vbt-conflict-mode", "ignore"), 0),
            }
            try:
                pyramiding  = bool(self.query_one("#vbt-accumulate",  Switch).value)
            except Exception:
                pyramiding = True
            try:
                sell_at_end = bool(self.query_one("#vbt-sell-at-end", Switch).value)
            except Exception:
                sell_at_end = False

            return {
                "assets": assets, "interval": interval, "balance": balance, "size": size,
                "start_date": start_date, "end_date": end_date, "adv_params": adv_params,
                "cooldown": cooldown, "accumulate": pyramiding,
                "per_symbol_alloc": per_symbol_alloc,
                "data_source": data_source, "data_config": data_config,
                "vbt_params": vbt_params,
                "sell_at_end": sell_at_end,
            }, None
        except ValueError as exc:
            return None, f"INVALID INPUT: {exc}"

    # ── Backtest execution ────────────────────────────────────────────────────

    def _generate_synthetic_df(
        self, assets: list, n_bars: int, start_price: float,
        drift_pct: float, vol_pct: float, seed: int, interval: str = "1h",
    ) -> pd.DataFrame:
        import numpy as np
        from datetime import timedelta
        freq_map  = {"15m": "15min", "1h": "1h", "4h": "4h", "1d": "1D"}
        freq      = freq_map.get(interval, "1h")
        secs_map  = {"15min": 900, "1h": 3600, "4h": 14400, "1D": 86400}
        step      = timedelta(seconds=secs_map.get(freq, 3600))
        base      = datetime(2020, 1, 1)
        timestamps = [base + i * step for i in range(n_bars)]
        parts = []
        for i, sym in enumerate(assets):
            sym_seed = (seed + i) if seed >= 0 else None
            rng      = np.random.default_rng(sym_seed)
            returns  = rng.normal(drift_pct / 100.0, vol_pct / 100.0, n_bars)
            close    = start_price * np.exp(np.cumsum(returns))
            noise    = rng.uniform(0.001, 0.008, n_bars)
            high     = close * (1.0 + noise)
            low      = close * (1.0 - noise)
            open_    = np.empty(n_bars)
            open_[0] = close[0]
            open_[1:] = close[:-1]
            volume = rng.uniform(100.0, 10000.0, n_bars)
            parts.append(pd.DataFrame({
                "timestamp": timestamps,
                "open": open_, "high": high, "low": low,
                "close": close, "volume": volume, "symbol": sym,
            }))
        return pd.concat(parts, ignore_index=True).sort_values("timestamp").set_index("timestamp")

    def _run_backtest(
        self, assets, interval, balance, size, start_date, end_date,
        adv_params, cooldown, accumulate, per_symbol_alloc=None,
        data_source="REAL", data_config=None, vbt_params=None, sell_at_end=False,
    ) -> None:
        _t0  = time.time()
        _pct = [0.0]
        setup_info = self._collect_setup_info()
        # Include strategy-specific params so AI prompts can explain each one.
        display_params = {
            k: v for k, v in adv_params.items()
            if k not in ("AI_MODEL", "PARAMS_A", "PARAMS_B") and not callable(v)
        }
        setup_info["adv_params"] = display_params
        self.state.last_setup_info = setup_info
        self.state.ai_scores_markup  = ""
        self.state.ai_report_markup  = ""
        self.state.ai_analysis_running = False

        def _elapsed() -> str:
            s = time.time() - _t0
            return f"{int(s // 60):02d}:{s % 60:04.1f}s"

        def _prog(v: float):
            _pct[0] = v
            self.app.call_from_thread(
                lambda _v=v: self.query_one("#main-progress", ProgressBar).update(progress=_v)
            )

        def _log(msg: str, level: str = "info", pause: float = 0.04):
            p = int(_pct[0])
            status_text = f"{p}% — {msg}"
            self.app.call_from_thread(lambda m=msg, l=level: self.log_status(m, l))
            self.app.call_from_thread(lambda s=status_text: self.query_one("#status-label", Label).update(s))
            time.sleep(pause)

        try:
            strategy_name = adv_params.get("STRATEGY", "EMA_CROSS")
            run_mode = normalize_mode(data_source)
            unit_label = "ASSET(S)" if run_mode == REAL_MARKET_BACKTEST else "SYNTHETIC SERIES"
            _prog(2); _log(f"[1/3] INITIATING — {len(assets)} {unit_label} / {interval} / {strategy_name}", pause=0.05)

            if strategy_name == "ELLIOT_BOLLINGER":
                self.app.call_from_thread(lambda: self.query_one(ReasoningTab).clear())

            if data_source == "RANDOM_WALK":
                cfg       = data_config or {}
                n_bars_rw = cfg.get("n_bars", 1000)
                _prog(10); _log(f"[1/3] GENERATING RANDOM WALK — {n_bars_rw} bars / {len(assets)} synthetic series", pause=0.04)
                market_df = self._generate_synthetic_df(
                    assets, n_bars_rw, cfg.get("start_price", 100.0),
                    cfg.get("drift", 0.05), cfg.get("volatility", 2.0),
                    cfg.get("seed", -1), interval,
                )
                _prog(40); _log(f"[1/3] RANDOM WALK READY — {len(market_df):,} rows — {_elapsed()}", "success", pause=0.06)

            elif data_source == "MONTE_CARLO":
                import numpy as _np
                cfg       = data_config or {}
                n_sims    = cfg.get("n_sims", 50)
                n_bars_mc = cfg.get("n_bars", 1000)
                base_seed = cfg.get("seed", -1)
                _prog(5); _log(f"[1/3] MONTE CARLO — {n_sims} paths × {n_bars_mc} bars / {len(assets)} synthetic series", pause=0.04)

                mc_results:   list = []
                _mc_t0:       float = time.time()
                _mc_rois:     list[float] = []
                _mc_last_ui:  list[float] = [0.0]
                n_cycles      = max(1, n_bars_mc // 100)   # 1 cycle = 100 bars
                _mc_sim_bar   = [0]   # current bar within the active sim
                _mc_sim_cycle = [0]   # current cycle within the active sim

                def _mc_panel(done: int, stage: str) -> None:
                    now = time.time()
                    if now - _mc_last_ui[0] < 0.08 and done < n_sims:
                        return
                    _mc_last_ui[0] = now

                    elapsed  = now - _mc_t0
                    speed    = done / elapsed if elapsed > 0 and done > 0 else 0.0
                    remain   = (n_sims - done) / speed if speed > 0 else 0.0
                    pct      = done / n_sims * 100 if n_sims > 0 else 0.0
                    bar_w    = 20
                    filled   = int(bar_w * pct / 100)
                    bar_vis  = "█" * filled + "░" * (bar_w - filled)

                    cur_bar   = _mc_sim_bar[0]
                    cur_cycle = _mc_sim_cycle[0]
                    cyc_left  = max(0, n_cycles - cur_cycle)

                    best_s  = f"[bold green]{max(_mc_rois):+.1f}%[/bold green]"   if _mc_rois else "[dim]—[/dim]"
                    worst_s = f"[bold red]{min(_mc_rois):+.1f}%[/bold red]"       if _mc_rois else "[dim]—[/dim]"
                    avg_s   = f"[bold]{sum(_mc_rois)/len(_mc_rois):+.1f}%[/bold]" if _mc_rois else "[dim]—[/dim]"

                    e_m, e_s = divmod(int(elapsed), 60)
                    r_m, r_s = divmod(int(remain),  60)
                    eta_str  = f"{r_m:02d}:{r_s:02d}" if speed > 0 else "--:--"
                    spd_s    = f"{speed:.1f}" if speed > 0 else "—"

                    panel = (
                        f"[bold dim]── MONTE CARLO PROGRESS ──[/bold dim]\n"
                        f"[cyan]{bar_vis}[/cyan] [bold]{pct:.1f}%[/bold]\n"
                        f"[dim]Current Path:[/dim]     [bold]{done + 1:,}[/bold] [dim]/ {n_sims:,}[/dim]"
                        f"  [dim]Paths Remaining:[/dim]  [bold]{max(0, n_sims - done):,}[/bold]\n"
                        f"[dim]Current Cycle:[/dim]    [bold]{cur_cycle}[/bold] [dim]/ {n_cycles}[/dim]"
                        f"  [dim]Cycles Remaining:[/dim] [bold]{cyc_left}[/bold]\n"
                        f"[dim]Current Bar:[/dim]      [bold]{cur_bar:,}[/bold] [dim]/ {n_bars_mc:,}[/dim]\n"
                        f"[dim]Speed:[/dim] [bold]{spd_s}[/bold][dim] paths/s[/dim]"
                        f"  [dim]Elapsed:[/dim] [bold]{e_m:02d}:{e_s:02d}[/bold]"
                        f"  [dim]ETA:[/dim] [bold cyan]{eta_str}[/bold cyan]\n"
                        f"[dim]Stage:[/dim] [italic]{stage}[/italic]\n"
                        f"[dim]Best:[/dim] {best_s}"
                        f"  [dim]Worst:[/dim] {worst_s}"
                        f"  [dim]Avg:[/dim] {avg_s}"
                    )
                    compact = (
                        f"MC {done + 1:,}/{n_sims:,} ({pct:.0f}%)"
                        f"  Cycle {cur_cycle}/{n_cycles}  Bar {cur_bar:,}/{n_bars_mc:,}"
                        f"  ETA {eta_str}"
                    )

                    def _apply(p=panel, c=compact, v=5 + pct * 0.85):
                        self.query_one("#mc-progress-panel", Static).update(p)
                        self.query_one("#status-label", Label).update(c)
                        self.query_one("#main-progress", ProgressBar).update(progress=v)
                    self.app.call_from_thread(_apply)

                # Show MC panel
                self.app.call_from_thread(
                    lambda: self.query_one("#mc-progress-panel", Static).add_class("visible")
                )
                _mc_panel(0, "Initialising simulation engine")

                # ── Determine worker count ────────────────────────────────────
                # Leave half the cores for Ollama + TUI; cap at 8 to stay sane.
                import threading as _threading
                from concurrent.futures import ThreadPoolExecutor as _TPE, as_completed as _as_completed
                _n_workers = min(8, max(1, (os.cpu_count() or 1) // 2))
                _mc_lock   = _threading.Lock()
                _done      = [0]

                # Params injected so EB skips per-block Ollama in MC sims
                _mc_adv = {**adv_params, "EGGSHELL_MC_MODE": True}

                def _run_one_mc_sim(sim_i: int):
                    if self.state.cancelled:
                        return None
                    sim_seed = (base_seed + sim_i) if base_seed >= 0 else -1
                    try:
                        sim_df = self._generate_synthetic_df(
                            assets, n_bars_mc, cfg.get("start_price", 100.0),
                            cfg.get("drift", 0.05), cfg.get("volatility", 2.0),
                            sim_seed, interval,
                        )
                        sim_signals = []
                        for sym in assets:
                            sym_df = sim_df[sim_df["symbol"] == sym]
                            if sym_df.empty:
                                continue
                            try:
                                sl = SignalLogic(sym_df, **_mc_adv)
                                sim_signals.append(sl.df)
                            except Exception:
                                continue
                        if not sim_signals:
                            return None
                        unified = pd.concat(sim_signals)
                        eng = BacktestEngine(
                            unified, initial_balance=balance, position_size_pct=size,
                            cooldown=cooldown, accumulate=accumulate,
                            per_symbol_alloc=per_symbol_alloc, vbt_params=vbt_params,
                            sell_at_end=sell_at_end,
                            simulation_mode="monte_carlo",
                            generate_charts=False,
                        )
                        return eng.run(), eng.trades
                    except Exception as exc:
                        if sim_i == 0:
                            self.app.call_from_thread(
                                lambda e=exc: self.log_status(f"[MC] SIM 1 error: {e}", "error")
                            )
                        return None

                _mc_milestone = max(1, n_sims // 10)
                with _TPE(max_workers=_n_workers) as _pool:
                    _futures = {_pool.submit(_run_one_mc_sim, i): i for i in range(n_sims)}
                    for _fut in _as_completed(_futures):
                        _result = _fut.result()
                        with _mc_lock:
                            _done[0] += 1
                            _d = _done[0]
                            if _result is not None:
                                mc_results.append(_result)
                                _mc_rois.append(_result[0]["total_return_pct"])
                        _mc_panel(_d, f"Parallel simulations  [{_n_workers} workers]")
                        if _mc_rois and _d % _mc_milestone == 0:
                            _b, _w, _a = max(_mc_rois), min(_mc_rois), sum(_mc_rois)/len(_mc_rois)
                            self.app.call_from_thread(
                                lambda d=_d, b=_b, w=_w, a=_a: self.log_status(
                                    f"[MC] {d}/{n_sims} | best {b:+.1f}% | worst {w:+.1f}% | avg {a:+.1f}%", "info"
                                )
                            )

                if not mc_results:
                    _log("MONTE CARLO: NO VALID RESULTS", "error", pause=0.04)
                    return

                rois = [r["total_return_pct"] for r, _ in mc_results]
                wrs  = [r["win_rate"]          for r, _ in mc_results]
                terminal_values = [r["final_balance"] for r, _ in mc_results]
                max_dds = [r["max_drawdown_pct"] for r, _ in mc_results]

                _mc_panel(n_sims, "Building confidence intervals")
                _log(f"[MC] ROI  min:{min(rois):+.2f}%  median:{_np.median(rois):+.2f}%  max:{max(rois):+.2f}%  σ:{_np.std(rois):.2f}%", "info", pause=0.04)
                _log(f"[MC] WIN RATE  min:{min(wrs):.1f}%  median:{_np.median(wrs):.1f}%  max:{max(wrs):.1f}%", "info", pause=0.04)
                _log(f"[MC] P(ROI>0) = {sum(1 for r in rois if r > 0) / len(rois) * 100:.1f}%  ({len(mc_results)}/{n_sims} valid sims)", "info", pause=0.04)

                _mc_panel(n_sims, "Generating Monte Carlo charts")
                sorted_mc = sorted(mc_results, key=lambda x: x[0]["total_return_pct"])
                med_results, _med_trades = sorted_mc[len(sorted_mc) // 2]
                proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
                charts_dir = os.path.join(proj_root, "reports", "charts")
                mc_charts = generate_montecarlo_graphs([r for r, _ in mc_results], charts_dir)
                prob_pos = sum(1 for r in rois if r > 0) / len(rois) * 100.0
                aggregate_results = {
                    **med_results,
                    "execution_mode": MONTE_CARLO,
                    "data_source": "MONTE_CARLO",
                    "total_return_pct": float(_np.median(rois)),
                    "win_rate": float(prob_pos),
                    "total_trades": len(mc_results),
                    "net_profit": float(_np.median(terminal_values) - balance),
                    "final_balance": float(_np.median(terminal_values)),
                    "max_drawdown_pct": float(_np.median(max_dds)),
                    "buy_hold_pct": 0.0,
                    "symbol_stats": {},
                    "charts": mc_charts,
                    "simulation_distribution": {
                        "valid_paths": len(mc_results),
                        "requested_paths": n_sims,
                        "min_return_pct": float(min(rois)),
                        "p05_return_pct": float(_np.percentile(rois, 5)),
                        "p25_return_pct": float(_np.percentile(rois, 25)),
                        "median_return_pct": float(_np.median(rois)),
                        "p75_return_pct": float(_np.percentile(rois, 75)),
                        "p95_return_pct": float(_np.percentile(rois, 95)),
                        "max_return_pct": float(max(rois)),
                        "std_return_pct": float(_np.std(rois)),
                        "probability_positive_pct": float(prob_pos),
                        "median_terminal_value": float(_np.median(terminal_values)),
                        "median_max_drawdown_pct": float(_np.median(max_dds)),
                    },
                }
                _mc_total_s  = time.time() - _mc_t0
                _mc_speed_f  = len(mc_results) / _mc_total_s if _mc_total_s > 0 else 0.0
                _mc_tm, _mc_ts = divmod(int(_mc_total_s), 60)
                _mc_summary = (
                    f"[bold dim]── MONTE CARLO COMPLETED ──[/bold dim]\n"
                    f"[dim]Simulations[/dim] [bold green]{len(mc_results):,}/{n_sims:,}[/bold green]\n"
                    f"[dim]Time[/dim] [bold]{_mc_tm:02d}:{_mc_ts:02d}[/bold]"
                    f"  [dim]Speed[/dim] [bold]{_mc_speed_f:.1f}[/bold][dim]/s[/dim]\n"
                    f"[dim]Best ROI[/dim]   [bold green]{max(rois):+.1f}%[/bold green]\n"
                    f"[dim]Worst ROI[/dim]  [bold red]{min(rois):+.1f}%[/bold red]\n"
                    f"[dim]Mean ROI[/dim]   [bold]{float(_np.mean(rois)):+.1f}%[/bold]\n"
                    f"[dim]Median ROI[/dim] [bold cyan]{float(_np.median(rois)):+.1f}%[/bold cyan]\n"
                    f"[dim]P(ROI>0)[/dim]   [bold]{sum(1 for r in rois if r > 0)/len(rois)*100:.0f}%[/bold]"
                )
                self.app.call_from_thread(
                    lambda s=_mc_summary: self.query_one("#mc-progress-panel", Static).update(s)
                )
                _prog(100)
                _log("[MC] COMPLETE — showing probabilistic distribution", "success", pause=0.06)
                self.state.run_final_status = (
                    f"[bold green]MC DONE — {len(mc_results)} sims | "
                    f"median ROI {_np.median(rois):+.2f}% | "
                    f"P(>0) {sum(1 for r in rois if r > 0)/len(rois)*100:.0f}%[/bold green]"
                )
                self.app.call_from_thread(self._update_results, aggregate_results, [], time.time() - _t0)
                return

            else:  # REAL
                _prog(5);  _log(f"[1/3] CONNECTING TO BINANCE — {start_date} → {end_date or 'NOW'}", pause=0.05)
                if self.state.cancelled:
                    return
                _prog(10); _log(f"[1/3] DOWNLOADING — {', '.join(assets)}", pause=0.04)

                def on_data_progress(pct: float, msg: str = None):
                    if self.state.cancelled:
                        return
                    _prog(10 + pct * 30)
                    if msg:
                        _log(f"[1/3] {msg}", pause=0.02)

                binance_df = Dataframe(
                    actives=assets, interval=interval,
                    start_date=start_date, end_date=end_date,
                    on_progress=on_data_progress,
                )
                if self.state.cancelled:
                    return
                market_df = binance_df.df
                _prog(40); _log(f"[1/3] DATA READY — {len(market_df):,} CANDLES / {len(assets)} PAIR(S) — {_elapsed()}", "success", pause=0.06)

            # ── Step 2/3: Signals ─────────────────────────────────────────────
            _prog(42); _log(f"[2/3] COMPUTING INDICATORS — {strategy_name}", pause=0.04)
            all_signals = []
            num_assets  = max(len(assets), 1)
            for asset_idx, symbol in enumerate(assets):
                if self.state.cancelled:
                    return
                symbol_df = market_df[market_df["symbol"] == symbol]
                if symbol_df.empty:
                    missing_label = symbol if run_mode == REAL_MARKET_BACKTEST else f"SYNTHETIC PATH {asset_idx + 1}"
                    _log(f"[2/3] NO DATA FOR {missing_label} — SKIPPED", "warning", pause=0.04)
                    continue
                base_pct = 44 + (asset_idx / num_assets) * 24
                _prog(base_pct)
                signal_label = symbol if run_mode == REAL_MARKET_BACKTEST else f"SYNTHETIC PATH {asset_idx + 1}"
                _log(f"[2/3] SIGNALS [{asset_idx + 1}/{num_assets}] — {signal_label} ({len(symbol_df):,} bars)", pause=0.04)

                def on_sub_progress(pct: float, msg: str = None, _idx=asset_idx):
                    if self.state.cancelled:
                        return
                    if pct is not None:
                        _prog(44 + (_idx / num_assets) * 24 + (24.0 / num_assets) * pct)
                    if msg:
                        _log(f"[2/3] {msg}", pause=0.02)

                sl = SignalLogic(symbol_df, on_progress=on_sub_progress, **adv_params)
                all_signals.append(sl.df)

                if strategy_name == "ELLIOT_BOLLINGER":
                    _eb_events = generate_eb_reasoning(symbol, symbol_df, sl.df)
                    for _ev in _eb_events:
                        self.app.call_from_thread(
                            lambda e=_ev: self.query_one(ReasoningTab).append_event(e)
                        )
                    if _eb_events and sl.df is not None and "buy" in sl.df.columns:
                        _buy_pct = float(sl.df["buy"].sum()) / max(len(sl.df), 1) * 100
                        _conf = min(95.0, 50.0 + _buy_pct * 5)
                        self.app.call_from_thread(
                            lambda c=_conf: self.query_one(ReasoningTab).set_confidence(
                                "Signal confidence", c
                            )
                        )

            if not all_signals:
                _log("NO MARKET DATA TO PROCESS", "error", pause=0.04)
                self.app.call_from_thread(lambda: self.notify("NO DATA FOUND.", severity="error"))
                return

            unified_signals = pd.concat(all_signals)
            total_buys  = int(unified_signals["buy"].sum())  if "buy"  in unified_signals.columns else 0
            total_sells = int(unified_signals["sell"].sum()) if "sell" in unified_signals.columns else 0
            _prog(70); _log(f"[2/3] SIGNALS READY — {total_buys} BUY / {total_sells} SELL — {_elapsed()}", "success", pause=0.06)
            if self.state.cancelled:
                return

            # ── Step 3/3: Engine ──────────────────────────────────────────────
            _prog(72); _log("[3/3] INITIALIZING VECTORBT ENGINE...", pause=0.05)
            _prog(74); _log(f"[3/3] BALANCE ${balance:,.2f} | SIZE {size:.1f}%", pause=0.05)

            _sim_mode = "real_market_backtest" if data_source == "REAL" else "random_walk"
            engine    = BacktestEngine(
                unified_signals, initial_balance=balance, position_size_pct=size,
                cooldown=cooldown, accumulate=accumulate, per_symbol_alloc=per_symbol_alloc,
                vbt_params=vbt_params, sell_at_end=sell_at_end,
                simulation_mode=_sim_mode,
            )

            def on_engine_progress(pct: float, msg: str = None):
                if self.state.cancelled:
                    return
                _prog(76 + pct * 24)
                if msg:
                    _log(f"[3/3] {msg}", pause=0.03)

            results = engine.run(on_progress=on_engine_progress)
            if self.state.cancelled:
                return

            elapsed_total = time.time() - _t0
            trades_n = len(engine.trades)
            roi      = results.get("total_return_pct", 0.0)
            _prog(100)
            _log(f"[3/3] BACKTEST COMPLETE — {trades_n} TRADES | ROI {roi:+.2f}% | {elapsed_total:.1f}s", "success", pause=0.06)
            self.state.run_final_status = f"[bold green]DONE — {trades_n} TRADES | ROI {roi:+.2f}% | {elapsed_total:.1f}s[/bold green]"
            self.app.call_from_thread(self._update_results, results, engine.trades, elapsed_total)

        except Exception as e:
            import traceback
            self.app.call_from_thread(lambda: self.log_status(f"CRITICAL ERROR: {e}", "error"))
            self.state.run_final_status = f"[bold red]ERROR — {e}[/bold red]"
            proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            err_dir   = os.path.join(proj_root, "reports", "errors")
            os.makedirs(err_dir, exist_ok=True)
            with open(os.path.join(err_dir, "error.log"), "a") as f:
                f.write(f"{datetime.now()}: {e}\n{traceback.format_exc()}\n")
            self.app.call_from_thread(lambda: self.notify(f"SYSTEM FAILURE: {e}", severity="error"))
        finally:
            self.app.call_from_thread(self._reset_ui)

    def _reset_ui(self):
        run_btn = self.query_one("#run-btn", Button)
        can_btn = self.query_one("#cancel-btn", Button)
        run_btn.disabled = False
        run_btn.label    = "EXECUTE SEQUENCE (R)"
        can_btn.remove_class("visible")
        self.query_one("#main-progress", ProgressBar).remove_class("visible")
        self.query_one(BacktestTimer).stop_timer()
        self.query_one("#mc-progress-panel", Static).remove_class("visible")
        self.query_one("#mc-progress-panel", Static).update("")
        final = self.state.run_final_status
        self.query_one("#status-label", Label).update(final if final else "READY")
        self.state.run_final_status = None

    # ── Results update ────────────────────────────────────────────────────────

    def _update_results(self, results: dict, trades: list, elapsed: float = 0.0) -> None:
        mode = normalize_mode(results.get("execution_mode") or results.get("data_source") or self.state.last_setup_info.get("data_source"))
        roi     = results["total_return_pct"]
        wr      = results["win_rate"]
        pnl_val = results["net_profit"]

        roi_label = self.query_one("#stat-return", Label)
        roi_label.update(f"{roi:.2f}%")
        roi_label.styles.color = "#ff0000" if roi < 0 else "#00ff00"

        wr_label = self.query_one("#stat-winrate", Label)
        wr_label.update(f"{wr:.1f}%")
        wr_label.styles.color = "#ff0000" if wr < 40 else "#00ff00"

        self.query_one("#stat-trades", Label).update(str(results["total_trades"]))
        pnl_label = self.query_one("#stat-final", Label)
        pnl_label.update(f"${pnl_val:.2f}")
        pnl_label.styles.color = "#ff0000" if pnl_val < 0 else "#00ff00"

        self.query_one(BacktestTimer).stop_timer(elapsed if elapsed else None)

        # Automatically trigger POST-EXECUTION analysis
        if not self.state.ai_analysis_running:
            Thread(target=self._run_ai_analysis, daemon=True).start()

        # Trades / scenario table
        table = self.query_one("#trades-table", DataTable)
        table.clear()
        if mode == MONTE_CARLO:
            dist = results.get("simulation_distribution", {})
            for label, value in [
                ("P05", dist.get("p05_return_pct", 0.0)),
                ("P25", dist.get("p25_return_pct", 0.0)),
                ("MEDIAN", dist.get("median_return_pct", roi)),
                ("P75", dist.get("p75_return_pct", 0.0)),
                ("P95", dist.get("p95_return_pct", 0.0)),
            ]:
                color = "#00ff00" if value >= 0 else "#ff0000"
                table.add_row("SIMULATION", "[cyan]PATH[/cyan]", label, "-", "-", "-", "-", f"[{color}]{value:+.2f}%[/]", "-")
        elif mode == RANDOM_WALK:
            for t in trades:
                color = "#00ff00" if t["profit_pct"] > 0 else "#ff0000"
                table.add_row(
                    t["buy_time"].strftime("%Y-%m-%d"),
                    "[cyan]SYN[/cyan]",
                    "PATH",
                    f"${t['investment']:.2f}",
                    f"{t['quantity']:.4f}",
                    f"{t['buy_price']:.2f}",
                    f"{t['sell_price']:.2f}",
                    f"[{color}]{t['profit_pct']:.2f}%[/]",
                    f"[{color}]{t.get('account_profit_pct', 0.0):.2f}%[/]",
                )
        else:
            for t in trades:
                color        = "#00ff00" if t["profit_pct"] > 0 else "#ff0000"
                type_display = "[green]LONG[/green]"
                table.add_row(
                    t["buy_time"].strftime("%Y-%m-%d"),
                    type_display,
                    t["symbol"],
                    f"${t['investment']:.2f}",
                    f"{t['quantity']:.4f}",
                    f"{t['buy_price']:.2f}",
                    f"{t['sell_price']:.2f}",
                    f"[{color}]{t['profit_pct']:.2f}%[/]",
                    f"[{color}]{t.get('account_profit_pct', 0.0):.2f}%[/]",
                )

        # Extended metrics
        full_stats    = results.get("full_stats", {})
        metrics_lines = []
        for k, v in full_stats.items():
            k_clean = str(k).replace("[", "(").replace("]", ")").upper()
            k_str   = k_clean[:22].ljust(23)
            if isinstance(v, float):
                if "(%)" in k:
                    col = "green" if v > 0 else "red" if v < 0 else "white"
                    metrics_lines.append(f"[dim]{k_str}[/dim][{col}]{v:+.2f}%[/{col}]")
                else:
                    metrics_lines.append(f"[dim]{k_str}[/dim][white]{v:.4f}[/white]")
            elif isinstance(v, int):
                metrics_lines.append(f"[dim]{k_str}[/dim][yellow]{v}[/yellow]")
            else:
                metrics_lines.append(f"[dim]{k_str}[/dim][cyan]{v}[/cyan]")

        h       = results.get("avg_hold_hours", 0)
        hold_str = f"{h:.1f}h" if h < 48 else f"{h / 24:.1f}d"
        net_c   = "green" if results["net_profit"] >= 0 else "red"
        avg_t   = results.get("avg_trade_pct", 0)
        avg_c   = "green" if avg_t >= 0 else "red"
        if mode == MONTE_CARLO:
            dist = results.get("simulation_distribution", {})
            metrics_lines.extend([
                "",
                "── MONTE CARLO DISTRIBUTION ──",
                f"[dim]{'VALID PATHS'.ljust(22)}[/dim][yellow]{dist.get('valid_paths', 0)}/{dist.get('requested_paths', 0)}[/yellow]",
                f"[dim]{'P(TERMINAL > START)'.ljust(22)}[/dim][cyan]{dist.get('probability_positive_pct', wr):.1f}%[/cyan]",
                f"[dim]{'P05 / MED / P95'.ljust(22)}[/dim][white]{dist.get('p05_return_pct', 0.0):+.2f}% / {dist.get('median_return_pct', roi):+.2f}% / {dist.get('p95_return_pct', 0.0):+.2f}%[/white]",
                f"[dim]{'RETURN STD DEV'.ljust(22)}[/dim][white]{dist.get('std_return_pct', 0.0):.2f}%[/white]",
            ])
        elif mode == RANDOM_WALK:
            metrics_lines.extend([
                "",
                "── RANDOM WALK METRICS ──",
                f"[dim]{'SYNTHETIC RETURN'.ljust(22)}[/dim][{net_c}]{roi:+.2f}%[/{net_c}]",
                f"[dim]{'AVG SIGNAL EVENT'.ljust(22)}[/dim][{avg_c}]{avg_t:+.2f}%[/{avg_c}]",
                f"[dim]{'AVG SYNTHETIC HOLD'.ljust(22)}[/dim][cyan]{hold_str}[/cyan]",
            ])
        else:
            metrics_lines.extend([
                "",
                "── EGGSHELL METRICS ──",
                f"[dim]{'NET PROFIT'.ljust(22)}[/dim][{net_c}]${results['net_profit']:,.2f}[/{net_c}]",
                f"[dim]{'AVG TRADE'.ljust(22)}[/dim][{avg_c}]{avg_t:+.2f}%[/{avg_c}]",
                f"[dim]{'AVG HOLD TIME'.ljust(22)}[/dim][cyan]{hold_str}[/cyan]",
            ])
        self.query_one("#ext-metrics-content", Static).update("\n".join(metrics_lines))

        self.state.charts = results.get("charts", {})

        # Per-symbol breakdown
        sym_table = self.query_one("#symbol-table", DataTable)
        sym_table.clear()
        try:
            sym_title = self.query_one("#sym-breakdown Label", Label)
            if mode == MONTE_CARLO:
                sym_title.update("── SIMULATION PATHS ──")
            elif mode == RANDOM_WALK:
                sym_title.update("── STOCHASTIC PATH ──")
            else:
                sym_title.update("── PER SYMBOL ──")
        except Exception:
            pass
        if mode == MONTE_CARLO:
            dist = results.get("simulation_distribution", {})
            sym_table.add_row("PATHS", str(dist.get("valid_paths", 0)), f"{dist.get('probability_positive_pct', wr):.1f}%", f"[cyan]{dist.get('median_return_pct', roi):+.2f}%[/]")
        elif mode == RANDOM_WALK:
            sym_table.add_row("SYNTH", str(results.get("total_trades", 0)), f"{wr:.1f}%", f"[cyan]{roi:+.2f}%[/]")
        else:
            for sym, s in sorted(results.get("symbol_stats", {}).items()):
                wr_s = s["wins"] / s["trades"] * 100 if s["trades"] else 0
                col  = "#00ff00" if s["total_pct"] >= 0 else "#ff0000"
                sym_table.add_row(
                    sym.replace("USDT", ""),
                    str(s["trades"]),
                    f"{wr_s:.1f}%",
                    f"[{col}]{s['total_pct']:+.2f}%[/]",
                )

        self.state.last_results = results
        self.state.last_trades  = trades
        self.query_one("#save-btn", Button).add_class("visible")
        Thread(target=self._run_ai_analysis, daemon=True).start()

        symbols      = sorted(set(t["symbol"] for t in trades)) if mode == REAL_MARKET_BACKTEST else []
        asset_select = self.query_one("#asset-chart-select", Select)
        asset_select.set_options([("ALL ASSETS", "__ALL__")] + [(s, s) for s in symbols])
        asset_select.value = "__ALL__"
        asset_select.set_class(mode == REAL_MARKET_BACKTEST, "visible")
        self._apply_asset_filter("__ALL__")

        self.state.pie_markup = self._draw_pie_chart()
        self.notify("PORTFOLIO SEQUENCE COMPLETE.", severity="information")
        self.query_one("#results-tabs", TabbedContent).active = "tab-stats"

    # ── Pie chart ─────────────────────────────────────────────────────────────

    def _draw_pie_chart(self) -> str:
        import math
        results = self.state.last_results
        mode = normalize_mode(
            (results or {}).get("execution_mode")
            or (results or {}).get("data_source")
            or self.state.last_setup_info.get("data_source")
        )
        if mode == MONTE_CARLO:
            dist = (results or {}).get("simulation_distribution", {})
            if not results:
                return "\n[dim #555555]  Run Monte Carlo to see simulation distribution summaries.[/dim #555555]"
            return (
                "\n[bold #facc15]  -- MONTE CARLO DISTRIBUTION --[/bold #facc15]\n"
                f"  [dim]Valid paths[/dim]          [yellow]{dist.get('valid_paths', 0)}/{dist.get('requested_paths', 0)}[/yellow]\n"
                f"  [dim]Positive terminal[/dim]    [cyan]{dist.get('probability_positive_pct', 0.0):.1f}%[/cyan]\n"
                f"  [dim]Return p05[/dim]           [white]{dist.get('p05_return_pct', 0.0):+.2f}%[/white]\n"
                f"  [dim]Return median[/dim]        [white]{dist.get('median_return_pct', results.get('total_return_pct', 0.0)):+.2f}%[/white]\n"
                f"  [dim]Return p95[/dim]           [white]{dist.get('p95_return_pct', 0.0):+.2f}%[/white]\n"
                f"  [dim]Return std dev[/dim]       [white]{dist.get('std_return_pct', 0.0):.2f}%[/white]\n"
                "\n[dim #555555]  Asset allocation is intentionally hidden in Monte Carlo mode.[/dim #555555]"
            )
        if mode == RANDOM_WALK:
            if not results:
                return "\n[dim #555555]  Run Random Walk to see stochastic path summaries.[/dim #555555]"
            return (
                "\n[bold #22d3ee]  -- RANDOM WALK STOCHASTIC MODEL --[/bold #22d3ee]\n"
                f"  [dim]Synthetic return[/dim]     [cyan]{results.get('total_return_pct', 0.0):+.2f}%[/cyan]\n"
                f"  [dim]Synthetic events[/dim]     [yellow]{results.get('total_trades', 0)}[/yellow]\n"
                f"  [dim]Max path drawdown[/dim]    [white]{results.get('max_drawdown_pct', 0.0):.2f}%[/white]\n"
                f"  [dim]Profit factor[/dim]        [white]{results.get('profit_factor', 0.0):.2f}[/white]\n"
                "\n[dim #555555]  Real asset allocation is intentionally hidden in Random Walk mode.[/dim #555555]"
            )
        COLORS  = ["#818cf8", "#34d399", "#fb7185", "#fbbf24", "#22d3ee", "#a78bfa", "#f97316", "#84cc16"]
        try:
            live_assets = [str(cb.label) for cb in self.query("#asset-checkbox-container Checkbox") if cb.value]
        except Exception:
            live_assets = []

        if not results:
            if len(live_assets) < 2:
                return "\n[dim #555555]  Run a backtest to see the asset pie.[/dim #555555]"
            symbols   = sorted(live_assets)
            sym_stats = {}
        else:
            sym_stats = results.get("symbol_stats", {})
            symbols   = sorted(sym_stats.keys())
            if not symbols:
                return "\n[dim #555555]  No trades recorded.[/dim #555555]"

        alloc: dict[str, float] = {
            sym: self.state.alloc_values.get(sym, 100.0 / len(symbols))
            for sym in symbols
        }
        total_a = sum(alloc.values()) or 1.0
        bounds  = [0.0]
        for sym in symbols:
            bounds.append(bounds[-1] + (alloc[sym] / total_a) * 2 * math.pi)

        W, H   = 36, 18
        DW, DH = W * 2, H * 4
        cx, cy = (DW - 1) / 2.0, (DH - 1) / 2.0
        r      = min(DW, DH) / 2.0 - 1.5
        DOT_BITS = [
            (0, 0, 0), (0, 1, 1), (0, 2, 2), (0, 3, 6),
            (1, 0, 3), (1, 1, 4), (1, 2, 5), (1, 3, 7),
        ]

        def sector_at(dc: int, dr: int) -> int:
            ddx = (dc - cx) / r
            ddy = (dr - cy) / r
            if ddx * ddx + ddy * ddy > 1.0:
                return -1
            angle = math.atan2(ddy, ddx) + math.pi
            for i in range(len(symbols)):
                if angle < bounds[i + 1]:
                    return i
            return len(symbols) - 1

        rows: list[str] = []
        for row in range(H):
            parts: list[str] = []
            for col in range(W):
                bits: int = 0
                votes: dict[int, int] = {}
                for dc, dr, bit in DOT_BITS:
                    sec = sector_at(col * 2 + dc, row * 4 + dr)
                    if sec >= 0:
                        bits |= (1 << bit)
                        votes[sec] = votes.get(sec, 0) + 1
                if bits == 0:
                    parts.append(" ")
                else:
                    dom     = max(votes, key=votes.get)
                    col_str = COLORS[dom % len(COLORS)]
                    parts.append(f"[{col_str}]{chr(0x2800 + bits)}[/{col_str}]")
            rows.append("".join(parts))

        sep        = "[#1f2937]" + "─" * 52 + "[/#1f2937]"
        is_preview = not bool(sym_stats)
        header_lbl = "── PORTFOLIO PREVIEW ──" if is_preview else "── ASSET ALLOCATION PIE ──"
        try:
            _size_type = str(self.query_one("#vbt-size-type", Select).value)
        except Exception:
            _size_type = "percent"
        _bud_unit = "%" if _size_type == "percent" else "$"
        _bud_col  = f"BUD{_bud_unit}/T"

        tbl = [
            "",
            f"[bold #00ffff]  {'SYM':<7} {'ALLOC':>6}  {_bud_col:>6}  {'P&L%':>8}  {'WIN%':>6}  {'TRADES':>6}[/bold #00ffff]",
            sep,
        ]
        for i, sym in enumerate(symbols):
            s       = sym_stats.get(sym, {})
            col_str = COLORS[i % len(COLORS)]
            a       = alloc.get(sym, 100.0 / len(symbols))
            try:
                bud_str = self.query_one("#size-input", Input).value + _bud_unit
            except Exception:
                bud_str = "-"
            pnl  = s.get("total_pct", 0.0)
            t    = s.get("trades", 0)
            wr   = s.get("wins", 0) / t * 100 if t else 0.0
            pc   = "green" if pnl >= 0 else ("dim" if is_preview else "red")
            short = sym.replace("USDT", "")
            pnl_col = f"[dim #555555]{'--':>7}[/dim #555555]" if is_preview else f"[{pc}]{pnl:+7.2f}%[/{pc}]"
            wr_col  = f"[dim #555555]{'--':>5}[/dim #555555]" if is_preview else f"[cyan]{wr:5.1f}%[/cyan]"
            t_col   = f"[dim #555555]{'--':>5}[/dim #555555]" if is_preview else f"[white]{t:5d}[/white]"
            tbl.append(
                f"  [{col_str}]⣿[/{col_str}] [white]{short:<7}[/white]"
                f" [yellow]{a:5.1f}%[/yellow]"
                f"  [magenta]{bud_str:>5}[/magenta]"
                f"  {pnl_col}  {wr_col}  {t_col}"
            )
        tbl.append(sep)
        if is_preview:
            tbl.append("[dim #555555]  Run backtest to populate P&L stats.[/dim #555555]")

        header = f"\n[bold #00ffff]  {header_lbl}[/bold #00ffff]\n"
        return header + "\n".join(rows) + "\n" + "\n".join(tbl)

    def _refresh_pie_live(self) -> None:
        try:
            markup             = self._draw_pie_chart()
            self.state.pie_markup = markup
            tc = self.query_one("#results-tabs", TabbedContent)
            if getattr(tc, "active", None) == "tab-pie":
                self.query_one("#assets-pie", Static).update(markup)
        except Exception:
            pass

    # ── Allocation helpers ────────────────────────────────────────────────────

    def _rebuild_allocation_inputs(self, reset: bool = True) -> None:
        try:
            data_source = str(self.query_one("#data-source-select", Select).value or "REAL")
            if normalize_mode(data_source) != REAL_MARKET_BACKTEST:
                self.query_one("#alloc-section").remove_class("visible")
                self.query_one("#portfolio-mode-badge", Static).add_class("hidden")
                self.state.alloc_values = {}
                return
            assets        = [str(cb.label) for cb in self.query("#asset-checkbox-container Checkbox") if cb.value]
            alloc_section = self.query_one("#alloc-section")
            badge         = self.query_one("#portfolio-mode-badge", Static)
            if len(assets) < 2:
                alloc_section.remove_class("visible")
                badge.add_class("hidden")
                self.state.alloc_values = {}
                return
            alloc_section.add_class("visible")
            badge.remove_class("hidden")
            badge.update(f"⬡  PORTFOLIO MODE — {len(assets)} ASSETS")
            n        = len(assets)
            base_pct = round(100.0 / n, 2)
            pcts     = [base_pct] * (n - 1) + [round(100.0 - base_pct * (n - 1), 2)]
            if reset:
                self.state.alloc_values = {a: p for a, p in zip(assets, pcts)}
            else:
                for asset, default_pct in zip(assets, pcts):
                    if asset not in self.state.alloc_values:
                        self.state.alloc_values[asset] = float(
                            self.state.active_settings.get(f"alloc-{asset}", default_pct)
                        )
            self._update_alloc_total()
        except Exception:
            pass

    def _update_alloc_total(self) -> None:
        try:
            total = sum(self.state.alloc_values.values())
            lbl   = self.query_one("#alloc-total", Label)
            lbl.update(f"TOTAL: {total:.1f}%")
            if abs(total - 100.0) < 0.1:
                lbl.remove_class("invalid")
            else:
                lbl.add_class("invalid")
        except Exception:
            pass

    # ── Chart helpers ─────────────────────────────────────────────────────────

    def _apply_asset_filter(self, value) -> None:
        mode = normalize_mode(
            self.state.last_results.get("execution_mode")
            or self.state.last_results.get("data_source")
            or self.state.last_setup_info.get("data_source")
        )
        layout = CHART_LAYOUTS.get(mode, CHART_LAYOUTS[REAL_MARKET_BACKTEST])
        is_all       = (value is Select.BLANK or value == "__ALL__")
        charts       = self.state.charts
        default_labels = {
            "open-chart-main": "FULL PORTFOLIO CHART",
            "open-chart-drawdowns": "TOP DRAWDOWNS CHART",
            "open-chart-returns": "CUMULATIVE RETURNS",
            "open-chart-cash": "CASH FLOW BALANCE",
            "open-chart-value": "PORTFOLIO VALUE",
            "open-chart-underwater": "UNDERWATER CHART (DEEP DIVE)",
            "open-chart-asset-trades": "ASSET TRADES CHART",
        }
        chart_btns = [
            "open-chart-main", "open-chart-drawdowns", "open-chart-returns",
            "open-chart-cash", "open-chart-value", "open-chart-underwater",
            "open-chart-asset-trades",
        ]
        for btn_id in chart_btns:
            try:
                btn = self.query_one(f"#{btn_id}", Button)
                btn.label = layout.get("labels", {}).get(btn_id, default_labels.get(btn_id, btn.label))
                key = layout["buttons"].get(btn_id)
                requires_asset = btn_id == "open-chart-asset-trades" and mode == REAL_MARKET_BACKTEST
                visible = bool(key and charts and os.path.exists(charts.get(key, "")))
                if requires_asset:
                    btn.disabled = is_all
                if visible:
                    btn.add_class("visible")
                else:
                    btn.remove_class("visible")
            except Exception:
                pass
        try:
            self.query_one("#asset-chart-select", Select).set_class(bool(layout.get("select")), "visible")
        except Exception:
            pass

    def _open_chart(self, file_path: str, anchor: str = "") -> None:
        if not file_path or not os.path.exists(file_path):
            self.notify("Chart file not found.", severity="warning")
            return
        url = _chart_url(file_path, anchor)
        if self._try_copy_to_clipboard(url):
            self.notify("URL copied to clipboard!", severity="information", timeout=3)
        self.push_screen(ChartUrlModal(url))

    @staticmethod
    def _try_copy_to_clipboard(text: str) -> bool:
        import subprocess
        for cmd, stdin in [
            (["wl-copy"],                                      text.encode()),
            (["xclip", "-selection", "clipboard"],             text.encode()),
            (["xsel", "--clipboard", "--input"],               text.encode()),
        ]:
            try:
                subprocess.run(cmd, input=stdin, check=True, timeout=2, capture_output=True)
                return True
            except Exception:
                pass
        try:
            import pyperclip
            pyperclip.copy(text)
            return True
        except Exception:
            pass
        return False

    # ── Global button handler ─────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "cancel-btn":
            self.action_cancel()
        elif bid == "save-btn":
            def _after_name(name: str | None) -> None:
                if name is not None:
                    self._save_backtest(name)
            self.push_screen(SaveNameModal(), _after_name)
        elif bid == "load-btn":
            proj_root   = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
            results_dir = os.path.join(proj_root, "reports", "results")
            def _after_load(folder: str | None) -> None:
                if folder:
                    self._load_backtest(folder)
            self.push_screen(LoadBacktestModal(results_dir), _after_load)
        elif bid == "open-chart-asset-trades":
            symbol     = self.query_one("#asset-chart-select", Select).value
            trades_path = self.state.charts.get("trades", "")
            if trades_path and os.path.exists(trades_path):
                anchor = symbol if symbol and symbol not in (Select.BLANK, "__ALL__") else ""
                self._open_chart(trades_path, anchor)
            else:
                self.notify("TRADES CHART NOT GENERATED.", severity="warning")
        elif bid and bid.startswith("open-chart-"):
            mode = normalize_mode(
                self.state.last_results.get("execution_mode")
                or self.state.last_results.get("data_source")
                or self.state.last_setup_info.get("data_source")
            )
            chart_type = CHART_LAYOUTS.get(mode, CHART_LAYOUTS[REAL_MARKET_BACKTEST])["buttons"].get(bid)
            if self.state.charts and chart_type in self.state.charts:
                self._open_chart(self.state.charts[chart_type])
            else:
                self.notify(f"Chart '{chart_type}' not generated.", severity="warning")

    # ── Save / Load backtest session ──────────────────────────────────────────

    def _save_backtest(self, name: str = "") -> None:
        import shutil, csv
        results = self.state.last_results
        trades  = self.state.last_trades
        if not results:
            self.notify("NO BACKTEST TO SAVE.", severity="warning")
            return

        proj_root   = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name   = name if name else timestamp
        results_dir = os.path.join(proj_root, "reports", "results")
        candidate   = os.path.join(results_dir, base_name)
        if os.path.exists(candidate):
            base_name = f"{base_name}_{timestamp}"
            candidate = os.path.join(results_dir, base_name)
        save_dir   = candidate
        charts_out = os.path.join(save_dir, "charts")
        os.makedirs(charts_out, exist_ok=True)

        saved_charts  = {}
        source_charts = results.get("charts", {})
        for key, src_path in source_charts.items():
            if src_path and os.path.exists(src_path):
                dst = os.path.join(charts_out, os.path.basename(src_path))
                shutil.copy2(src_path, dst)
                saved_charts[key] = dst

        stats_path = os.path.join(save_dir, "stats.txt")
        mode = normalize_mode(results.get("execution_mode") or results.get("data_source"))
        with open(stats_path, "w") as f:
            f.write("EGGSHELL BACKTESTER PROBER version 1.2 — RESULTS SNAPSHOT\n")
            f.write(f"Saved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Execution mode: {mode}\n")
            f.write("=" * 50 + "\n\n")
            for label, val in [
                ("TOTAL ROI", f"{results['total_return_pct']:+.2f}%"),
                ("WIN RATE",  f"{results['win_rate']:.1f}%"),
                ("TOTAL TRADES", str(results["total_trades"])),
                ("NET PROFIT",   f"${results['net_profit']:,.2f}"),
                ("FINAL BALANCE", f"${results['final_balance']:,.2f}"),
                ("MAX DRAWDOWN", f"{results['max_drawdown_pct']:.2f}%"),
                ("SHARPE RATIO", f"{results['sharpe_ratio']:.4f}"),
            ]:
                f.write(f"{label:<28}{val}\n")
            f.write("\n── FULL VECTORBT STATS ──\n")
            for k, v in results.get("full_stats", {}).items():
                f.write(f"{str(k)[:28]:<28}{v}\n")
            if mode == MONTE_CARLO:
                f.write("\n── MONTE CARLO DISTRIBUTION ──\n")
                for k, v in results.get("simulation_distribution", {}).items():
                    f.write(f"{k[:28]:<28}{v}\n")
            elif mode == RANDOM_WALK:
                f.write("\n── RANDOM WALK SYNTHETIC SUMMARY ──\n")
                f.write("Synthetic stochastic model summary.\n")
            else:
                f.write("\n── PER-SYMBOL BREAKDOWN ──\n")
                for sym, s in sorted(results.get("symbol_stats", {}).items()):
                    wr_s = s["wins"] / s["trades"] * 100 if s["trades"] else 0
                    f.write(f"{sym:<14} trades={s['trades']:>4}  winrate={wr_s:5.1f}%  total={s['total_pct']:+.2f}%\n")

        trades_path = os.path.join(save_dir, "trades.csv")
        if trades:
            fieldnames = ["symbol", "buy_time", "sell_time", "buy_price", "sell_price",
                          "quantity", "investment", "profit_pct", "account_profit_pct", "profit_usd"]
            with open(trades_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(trades)

        links_path = os.path.join(save_dir, "charts_links.html")
        with open(links_path, "w") as f:
            f.write("<!DOCTYPE html><html><head><meta charset='utf-8'>")
            f.write("<title>Backtest Charts</title>")
            f.write("<style>body{background:#0a0a0a;color:#eee;font-family:monospace;padding:2em;}")
            f.write("h1{color:#00ffff;}a{color:#ff8800;display:block;margin:.5em 0;font-size:1.1em;}</style>")
            f.write("</head><body>")
            f.write(f"<h1>EGGSHELL BACKTESTER PROBER version 1.2 — {timestamp}</h1>")
            labels = {"main": "Full Portfolio Chart", "trades": "Trades Chart",
                      "drawdowns": "Top Drawdowns", "returns": "Cumulative Returns",
                      "cash": "Cash Flow Balance", "value": "Portfolio Value",
                      "underwater": "Underwater Chart",
                      "mc_path_cloud": "Monte Carlo Path Cloud",
                      "mc_percentiles": "Monte Carlo Percentile Envelope",
                      "mc_terminal_distribution": "Monte Carlo Terminal Distribution",
                      "mc_drawdown_distribution": "Monte Carlo Drawdown Distribution",
                      "mc_3d": "Monte Carlo 3D Simulation Space",
                      "rw_paths": "Random Walk Stochastic Paths",
                      "rw_drift_volatility": "Random Walk Drift / Volatility"}
            for key, dst in saved_charts.items():
                f.write(f'<a href="file://{dst}">{labels.get(key, key.title())}</a>')
            f.write("</body></html>")

        import json as _json
        def _ser(obj):
            if isinstance(obj, dict):  return {k: _ser(v) for k, v in obj.items()}
            if isinstance(obj, list):  return [_ser(v) for v in obj]
            if hasattr(obj, "isoformat"): return str(obj)
            if isinstance(obj, float) and obj != obj: return None
            return obj
        snap = {k: v for k, v in results.items()
                if k not in ("equity_history", "returns_history", "drawdown_history",
                             "price_history", "timestamp_history")}
        snap["charts"] = saved_charts
        with open(os.path.join(save_dir, "results.json"), "w") as f:
            _json.dump(_ser(snap), f)

        self.notify(f"SAVED → reports/results/{base_name}", severity="information")
        self.log_status(f"BACKTEST SAVED: {save_dir}", "success")

    def _load_backtest(self, folder_name: str) -> None:
        import json as _json
        proj_root  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        save_dir   = os.path.join(proj_root, "reports", "results", folder_name)
        charts_dir = os.path.join(save_dir, "charts")
        if not os.path.exists(save_dir):
            self.notify("BACKTEST FOLDER NOT FOUND.", severity="error")
            return

        results: dict = {}
        results_path  = os.path.join(save_dir, "results.json")
        if os.path.exists(results_path):
            try:
                with open(results_path) as f:
                    results = _json.load(f)
            except Exception:
                pass

        if not results.get("charts"):
            chart_files = {
                "main":       "real_market_portfolio_report.html",
                "trades":     "real_market_trades.html",
                "underwater": "real_market_underwater.html",
                "value":      "real_market_value.html",
                "drawdowns":  "real_market_drawdowns.html",
                "returns":    "real_market_returns.html",
                "cash":       "real_market_cash.html",
                "mc_path_cloud": "montecarlo_path_cloud.html",
                "mc_percentiles": "montecarlo_percentile_envelope.html",
                "mc_terminal_distribution": "montecarlo_terminal_distribution.html",
                "mc_drawdown_distribution": "montecarlo_drawdown_distribution.html",
                "mc_3d": "montecarlo_3d_simulation_space.html",
                "rw_paths": "random_walk_stochastic_paths.html",
                "rw_drift_volatility": "random_walk_drift_volatility.html",
            }
            results["charts"] = {
                k: os.path.join(charts_dir, v)
                for k, v in chart_files.items()
                if os.path.exists(os.path.join(charts_dir, v))
            }

        for key in ("total_return_pct", "win_rate", "total_trades", "net_profit", "final_balance",
                    "max_drawdown_pct", "avg_hold_hours", "sharpe_ratio", "sortino_ratio",
                    "calmar_ratio", "profit_factor", "best_trade", "worst_trade",
                    "avg_trade_pct", "avg_win_pct", "avg_loss_pct", "buy_hold_pct"):
            results.setdefault(key, 0.0)
        results.setdefault("symbol_stats", {})
        results.setdefault("full_stats",   {})

        trades: list[dict] = []
        trades_csv = os.path.join(save_dir, "trades.csv")
        if os.path.exists(trades_csv):
            try:
                df_t = pd.read_csv(trades_csv)
                for _, row in df_t.iterrows():
                    trades.append({
                        "symbol":             str(row["symbol"]),
                        "buy_time":           pd.to_datetime(row["buy_time"]),
                        "sell_time":          pd.to_datetime(row["sell_time"]),
                        "buy_price":          float(row["buy_price"]),
                        "sell_price":         float(row["sell_price"]),
                        "profit_pct":         float(row["profit_pct"]),
                        "account_profit_pct": float(row.get("account_profit_pct") or 0),
                        "profit_usd":         float(row["profit_usd"]),
                        "investment":         float(row["investment"]),
                        "quantity":           float(row["quantity"]),
                        "reason":             "Buy Sig -> Sell Sig",
                    })
            except Exception:
                pass

        if not results["symbol_stats"] and trades:
            for t in trades:
                s = results["symbol_stats"].setdefault(t["symbol"], {"trades": 0, "wins": 0, "total_pct": 0.0})
                s["trades"] += 1
                if t["profit_pct"] > 0:
                    s["wins"] += 1
                s["total_pct"] += t["profit_pct"]

        self._update_results(results, trades)
        self.log_status(f"[bold cyan]── LOADED: {folder_name} ──[/bold cyan]", "info")
        self.notify(f"LOADED: {folder_name}", severity="information")

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_cancel(self) -> None:
        self.state.cancelled = True
        self.query_one("#status-label", Label).update("[bold red]ABORTING SEQUENCE...[/bold red]")
        self.log_status("ABORTING BACKTEST BY USER REQUEST", "warning")
        self.notify("ABORTING BACKTEST...", severity="warning")

    def _apply_panel_width(self) -> None:
        w = self._PANEL_PRESETS[self._panel_idx]
        self.query_one("#config-column").styles.width = w
        self.notify(f"Panel width: {w}ch", timeout=1.2, severity="information")

    def action_shrink_panel(self) -> None:
        if self._panel_idx > 0:
            self._panel_idx -= 1
            self._apply_panel_width()

    def action_grow_panel(self) -> None:
        if self._panel_idx < len(self._PANEL_PRESETS) - 1:
            self._panel_idx += 1
            self._apply_panel_width()

    # ── Logging ───────────────────────────────────────────────────────────────

    def log_status(self, msg: str, level: str = "info") -> None:
        colors   = {"info": "cyan", "warning": "yellow", "error": "red", "success": "green"}
        color    = colors.get(level, "white")
        log      = self.query_one("#main-log", RichLog)
        time_str = datetime.now().strftime("%H:%M:%S")
        log.write(f"[[dim]{time_str}[/dim]] [[b {color}]{level.upper()}[/b {color}]] {msg}")

    def _debug(self, msg: str) -> None:
        try:
            with open(self._debug_path, "a") as f:
                import time as _t
                f.write(f"[{_t.strftime('%H:%M:%S')}] {msg}\n")
        except Exception:
            pass

    # ── Static helpers ────────────────────────────────────────────────────────

    # ── AI tab ────────────────────────────────────────────────────────────────

    def _check_ollama_setup(self) -> None:
        """Check Ollama availability on startup and populate the model selector."""
        models    = _list_ollama_models()
        # Any installed model is sufficient — do NOT require "plutus" specifically.
        available = len(models) > 0
        self.state.ollama_setup_ok = available
        if models:
            # Keep whatever is currently selected if it's still valid; else default
            default = self.state.ai_model if self.state.ai_model in models else models[0]
            self.state.ai_model = default
            opts = [(m, m) for m in models]
            def _populate(o=opts, d=default):
                try:
                    sel = self.query_one("#ai-model-select", Select)
                    sel.set_options(o)
                    sel.value = d
                except Exception:
                    pass
            self.call_from_thread(_populate)
            # Advise on GPU utilization based on model size
            def _log_model_advice(m=default, ms=models):
                self.log_status(f"[AI] Ollama ready — model: {m}", "success")
                # Rough size heuristic from model name
                name_lower = m.lower()
                is_small = any(x in name_lower for x in ("0.5b", "1b", "1.5b", "0.5", "0.6"))
                is_large = any(x in name_lower for x in ("7b", "8b", "13b", "14b", "70b", "plutus"))
                if is_small:
                    self.log_status(
                        f"[GPU] {m} is a sub-1B model — GPU util ceiling ~25-35%. "
                        "For higher utilization select a 7B+ model (e.g. plutus, llama3.2).",
                        "warning"
                    )
                elif is_large:
                    self.log_status(
                        f"[GPU] {m} is a 7B+ model — expect 60-80% GPU utilization during inference.",
                        "info"
                    )
            self.call_from_thread(_log_model_advice)
        else:
            self.call_from_thread(
                lambda: self.log_status("[AI] Ollama OFFLINE — no models found. AI analysis disabled.", "error")
            )
            def _hide_tab():
                try:
                    self.query_one(SetupTab).add_class("hidden")
                    self.query_one("#results-tabs", TabbedContent).remove_pane("tab-setup")
                except Exception:
                    pass
            self.call_from_thread(_hide_tab)

    def _collect_setup_info(self) -> dict:
        def _sv(wid, default=""):
            try:
                v = self.query_one(f"#{wid}").value
                return default if str(v) in ("NoSelection", "") else str(v)
            except Exception:
                return default
        def _fv(wid, default=0.0):
            try: return float(self.query_one(f"#{wid}").value)
            except Exception: return default
        def _bv(wid, default=False):
            try: return bool(self.query_one(f"#{wid}", Switch).value)
            except Exception: return default

        assets = [str(cb.label) for cb in self.query("#asset-checkbox-container Checkbox") if cb.value]
        ds     = _sv("data-source-select", "REAL")
        mode   = normalize_mode(ds)
        if ds == "RANDOM_WALK":
            interval = _sv("rw-interval-select", "1h")
            balance = _fv("rw-balance-input", 1000.0)
            context_assets = []
        elif ds == "MONTE_CARLO":
            interval = _sv("mc-interval-select", "1h")
            balance = _fv("mc-balance-input", 1000.0)
            context_assets = []
        else:
            interval = _sv("interval-select", "1h")
            balance = _fv("balance-input", 1000.0)
            context_assets = assets or ["BTCUSDT"]
        return {
            "strategy":     _sv("strategy-select", "EMA_CROSS"),
            "assets":       context_assets,
            "interval":     interval,
            "balance":      balance,
            "budget":       _fv("size-input",      20.0),
            "start_date":   _sv("start-date-input", "2023-01-01"),
            "end_date":     _sv("end-date-input",  ""),
            "cooldown":     int(_fv("cooldown-input", 0)),
            "pyramiding":   _bv("vbt-accumulate",  True),
            "cash_sharing": _bv("vbt-cash-sharing", True),
            "sell_at_end":  _bv("vbt-sell-at-end",  False),
            "data_source":  ds,
            "execution_mode": mode,
            "commission":   _fv("vbt-fees",        0.0),
            "slippage":     _fv("vbt-slippage",    0.0),
            "fixed_fee":    _fv("vbt-fixed-fees",  0.0),
            "n_bars":       int(_fv("rw-n-bars" if ds == "RANDOM_WALK" else "mc-n-bars", 1000)),
            "drift":        _fv("rw-drift"      if ds == "RANDOM_WALK" else "mc-drift",     0.05),
            "volatility":   _fv("rw-volatility" if ds == "RANDOM_WALK" else "mc-volatility", 2.0),
            "n_sims":       int(_fv("mc-n-sims", 50)),
            "allocation":   dict(self.state.alloc_values),
        }

    def _run_setup_analysis(self) -> None:
        setup_info = self._collect_setup_info()
        import json
        setup_hash = hash(json.dumps(setup_info, sort_keys=True))
        if getattr(self.state, "last_setup_hash", None) == setup_hash:
            return
        
        self.state.last_setup_hash = setup_hash
        self.state.last_setup_info = setup_info

        def _do_analysis():
            try:
                setup_tab = self.query_one(SetupTab)
                self.app.call_from_thread(lambda: setup_tab.set_phase("SETUP ANALYSIS"))

                setup_analysis = AIAnalysisOrchestrator.analyze_setup(setup_info)
                self.state.last_setup_risks = setup_analysis.get("risks", [])

                scores_markup = AIAnalysisOrchestrator.build_scores_markup(setup_analysis["scores"], is_setup=True)

                enhanced_text = ""
                model = self.state.ai_model

                if not self.state.ollama_setup_ok:
                    self.app.call_from_thread(lambda: setup_tab.set_phase("FAILED", is_error=True))
                    self.app.call_from_thread(lambda: self.log_status("[AI] SETUP skipped — ollama_setup_ok=False (no models?)", "warning"))
                    enhanced_text = "[red]AI ERROR REPORT[/red]\nAI model unavailable."
                elif model:
                    self.app.call_from_thread(lambda m=model: self.log_status(f"[AI REQUEST START] setup analysis → {m}", "info"))
                    self.app.call_from_thread(lambda m=model: setup_tab.update_pre_execution("", f"[dim]⏳ Streaming from {m}…[/dim]"))
                    try:
                        prompt = AIAnalysisOrchestrator.build_setup_prompt(setup_info)

                        token_buf: list[str] = []
                        _last_flush          = [0.0]

                        def _on_token(tok: str) -> None:
                            token_buf.append(tok)
                            now = __import__("time").monotonic()
                            if now - _last_flush[0] >= 0.3:
                                _last_flush[0] = now
                                partial = "".join(token_buf).strip()
                                if partial:
                                    partial_markup = AIAnalysisOrchestrator.build_full_markup(
                                        {}, [], setup_info, setup_analysis["risks"], [],
                                        partial + "[blink]▋[/blink]",
                                        is_setup=True
                                    )
                                    self.app.call_from_thread(
                                        lambda sm=scores_markup, fm=partial_markup:
                                            self.query_one(SetupTab).update_pre_execution(sm, fm)
                                        if True else None
                                    )

                        try:
                            from .utils.inference_pool import pool
                            pool.start(model=model, n_workers=2)
                            fut = pool.submit(prompt, model=model, on_token=_on_token)
                            self.app.call_from_thread(lambda: self.log_status("[AI REQUEST SENT] setup prompt queued to InferencePool", "info"))
                            raw = fut.result()  # no timeout — let Ollama finish naturally
                            enhanced_text = raw.strip() if raw else "".join(token_buf).strip()
                            self.app.call_from_thread(lambda n=len(enhanced_text): self.log_status(f"[AI RESPONSE RECEIVED] setup — {n} chars", "success"))
                        except Exception as pool_exc:
                            self.app.call_from_thread(lambda e=pool_exc: self.log_status(f"[AI] InferencePool failed ({e}), falling back to direct call", "warning"))
                            raw = _ollama_generate(prompt, model=model, on_token=_on_token)
                            enhanced_text = raw.strip() if raw else "".join(token_buf).strip()
                            self.app.call_from_thread(lambda n=len(enhanced_text): self.log_status(f"[AI RESPONSE RECEIVED] setup (direct) — {n} chars", "success"))

                    except Exception as e:
                        self.app.call_from_thread(lambda: setup_tab.set_phase("FAILED", is_error=True))
                        self.app.call_from_thread(lambda err=e: self.log_status(f"[AI REQUEST FAILED] setup: {err}", "error"))
                        enhanced_text = f"[red]AI ERROR REPORT[/red]\n{e}"

                if "AI ERROR REPORT" not in enhanced_text:
                    self.app.call_from_thread(lambda: setup_tab.set_phase("SETUP ANALYSIS COMPLETE"))

                content_markup = AIAnalysisOrchestrator.build_full_markup(
                    {}, [], setup_info, setup_analysis["risks"], [], enhanced_text, is_setup=True
                )
                
                self.app.call_from_thread(lambda: setup_tab.update_pre_execution(scores_markup, content_markup))

            except Exception:
                try:
                    setup_tab = self.query_one(SetupTab)
                    self.app.call_from_thread(lambda: setup_tab.update_pre_execution("", "Setup analysis unavailable."))
                    self.app.call_from_thread(lambda: setup_tab.set_phase("FAILED", is_error=True))
                except Exception:
                    pass

        Thread(target=_do_analysis, daemon=True).start()

    def _refresh_setup_tab(self) -> None:
        """Called when the AI tab is activated. Only triggers a fresh setup analysis if hash changed."""
        self._run_setup_analysis()

    def _warmup_inference_pool(self) -> None:
        """
        Seed the InferencePool KV-cache prefix on app startup.

        Runs in a background daemon thread from on_mount(). Waits briefly for
        _check_ollama_setup (started concurrently) to discover and set the correct
        model before seeding the KV-cache — avoids warming up "plutus" when the
        user has a different model installed.
        """
        import time as _time
        # Let _check_ollama_setup populate ai_model before we start.
        # It runs one HTTP request to /api/tags — typically < 200 ms.
        deadline = _time.monotonic() + 10.0
        while _time.monotonic() < deadline:
            m = self.state.ai_model
            if m and m != _SETUP_MODEL:
                break
            _time.sleep(0.25)
        try:
            from .utils.inference_pool import pool
            models = _list_ollama_models()
            if not models:
                return
            model = self.state.ai_model if self.state.ai_model in models else models[0]
            pool.start(model=model, n_workers=2)
            pool.warmup(model=model)
            self._debug(f"InferencePool warmed up — KV-cache prefix seeded [{model}]")
            self.call_from_thread(
                lambda m=model: self.log_status(f"[AI] InferencePool ready — KV-cache warm [{m}]", "info")
            )
        except Exception as exc:
            self._debug(f"InferencePool warmup skipped: {exc}")

    def _run_ai_analysis(self) -> None:
        """
        Background worker: compute scores, detect patterns, call Ollama via
        the InferencePool with live streaming token output to the UI.

        v2 changes
        ----------
        - Submits the prompt to InferencePool instead of calling _ollama_generate
          directly, so the pool's persistent workers handle the request without
          spawning a new HTTP connection each time.
        - Tokens stream live to the AI tab as they arrive — the user sees output
          start in < 1 second after the backtest completes.
        - Falls back to direct _ollama_generate() if InferencePool is unavailable.
        """
        if self.state.ai_analysis_running:
            return
        self.state.ai_analysis_running = True
        
        def _set_status(msg: str):
            try:
                self.query_one(SetupTab).update_post_execution(msg, "", "")
            except Exception:
                pass

        self.call_from_thread(lambda: (
            self.query_one(SetupTab).set_phase("RESULT ANALYSIS RUNNING"),
            _set_status("[dim]⏳ Analyzing backtest…[/dim]"),
        ))

        try:
            results    = self.state.last_results
            trades     = self.state.last_trades
            setup_info = self.state.last_setup_info

            # Run rule-based orchestrator (fast — no GPU)
            post_analysis = AIAnalysisOrchestrator.analyze_results(results, trades, setup_info)
            scores   = post_analysis["scores"]
            patterns = post_analysis["patterns"]
            recs     = post_analysis["recommendations"]

            setup_risks       = getattr(self.state, "last_setup_risks", [])
            combined_feedback = AIAnalysisOrchestrator.generate_combined_feedback(setup_risks, patterns)
            scores_markup     = AIAnalysisOrchestrator.build_scores_markup(scores, setup_info)

            enhanced_text = ""
            model = self.state.ai_model

            if not self.state.ollama_setup_ok:
                self.call_from_thread(lambda: self.query_one(SetupTab).set_phase("FAILED", is_error=True))
                self.call_from_thread(lambda: self.log_status("[AI] RESULT ANALYSIS skipped — ollama_setup_ok=False (no models?)", "warning"))
                enhanced_text = "[red]AI ERROR REPORT[/red]\nAI model unavailable."
            elif model:
                self.call_from_thread(lambda m=model: self.log_status(f"[AI REQUEST START] result analysis → {m}", "info"))
                self.call_from_thread(
                    lambda m=model: _set_status(f"[dim]⏳ Streaming from {m}…[/dim]")
                )
                try:
                    prompt = AIAnalysisOrchestrator.build_analysis_prompt(results, trades, setup_info)

                    token_buf: list[str] = []
                    _last_flush          = [0.0]

                    def _on_token(tok: str) -> None:
                        token_buf.append(tok)
                        now = __import__("time").monotonic()
                        if now - _last_flush[0] >= 0.3:
                            _last_flush[0] = now
                            partial = "".join(token_buf).strip()
                            if partial:
                                partial_markup = AIAnalysisOrchestrator.build_full_markup(
                                    results, trades, setup_info, patterns, recs,
                                    partial + "[blink]▋[/blink]",
                                    is_setup=False, combined_feedback=combined_feedback,
                                )
                                self.call_from_thread(
                                    lambda sm=scores_markup, fm=partial_markup:
                                        self.query_one(SetupTab).update_post_execution("", sm, fm)
                                    if True else None
                                )

                    try:
                        from .utils.inference_pool import pool
                        pool.start(model=model, n_workers=2)
                        fut = pool.submit(prompt, model=model, on_token=_on_token)
                        self.call_from_thread(lambda: self.log_status("[AI REQUEST SENT] result prompt queued to InferencePool", "info"))
                        raw = fut.result()  # no timeout — let Ollama finish naturally
                        enhanced_text = raw.strip() if raw else "".join(token_buf).strip()
                        self.call_from_thread(lambda n=len(enhanced_text): self.log_status(f"[AI RESPONSE RECEIVED] result — {n} chars", "success"))
                    except Exception as pool_exc:
                        self.call_from_thread(lambda e=pool_exc: self.log_status(f"[AI] InferencePool failed ({e}), falling back to direct call", "warning"))
                        raw = _ollama_generate(prompt, model=model, on_token=_on_token)
                        enhanced_text = raw.strip() if raw else "".join(token_buf).strip()
                        self.call_from_thread(lambda n=len(enhanced_text): self.log_status(f"[AI RESPONSE RECEIVED] result (direct) — {n} chars", "success"))

                except Exception as e:
                    self.call_from_thread(lambda: self.query_one(SetupTab).set_phase("FAILED", is_error=True))
                    enhanced_text = f"[red]AI ERROR REPORT[/red]\n{e}"

            if "AI ERROR REPORT" not in enhanced_text:
                self.call_from_thread(lambda: self.query_one(SetupTab).set_phase("RESULT ANALYSIS COMPLETE"))

            report_markup = AIAnalysisOrchestrator.build_full_markup(
                results, trades, setup_info, patterns, recs, enhanced_text,
                is_setup=False, combined_feedback=combined_feedback
            )

            self.state.ai_scores_markup = scores_markup
            self.state.ai_report_markup = report_markup

            def _update(sm=scores_markup, fm=report_markup):
                try:
                    self.query_one(SetupTab).update_post_execution("", sm, fm)
                except Exception:
                    pass
            self.call_from_thread(_update)

        except Exception as e:
            self.call_from_thread(lambda: self.query_one(SetupTab).set_phase("FAILED", is_error=True))
        finally:
            self.state.ai_analysis_running = False
