from binance_service.dataframe import Dataframe
from core.signal_logic import SignalLogic
from core.backtest_engine import BacktestEngine
from core.constants import DataframeConstantsBinance, STRATEGY_SCHEMAS

import os
import calendar
import webbrowser
from datetime import datetime, date
from textual.app import App, ComposeResult
from textual.widget import Widget
from textual.containers import Horizontal, Vertical, Grid, VerticalScroll
from textual.widgets import (Header, Footer, Button, Static, Label, Input,
                             Select, DataTable, TabbedContent, TabPane,
                             Switch, SelectionList, Collapsible, ProgressBar, Checkbox, RichLog)
from textual.widgets.selection_list import Selection
from textual import on
from textual.binding import Binding
from textual import work
from threading import Thread
import pandas as pd

import inspect


class CalendarWidget(Static):
    def __init__(self, target_input_id: str, **kwargs):
        super().__init__(**kwargs)
        self.target_input_id = target_input_id
        self.current_year = datetime.now().year
        self.current_month = datetime.now().month
        self._pfx = target_input_id.replace("-", "_")

    def compose(self) -> ComposeResult:
        with Vertical(classes="cal-container"):
            with Horizontal(classes="cal-header"):
                yield Button("<", id=f"cal-prev-{self._pfx}")
                yield Label("", id=f"cal-label-{self._pfx}", classes="cal-month-label")
                yield Button(">", id=f"cal-next-{self._pfx}")
                yield Button("X", id=f"cal-close-{self._pfx}", classes="cal-close-btn")
            yield Grid(id=f"cal-grid-{self._pfx}", classes="cal-grid")

    def on_mount(self) -> None:
        self.update_calendar()

    def update_calendar(self):
        self.query_one(f"#cal-label-{self._pfx}", Label).update(
            f"{calendar.month_name[self.current_month]} {self.current_year}"
        )
        grid = self.query_one(f"#cal-grid-{self._pfx}", Grid)
        grid.remove_children()
        for day_name in ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]:
            grid.mount(Label(day_name, classes="day-header"))
        for week in calendar.monthcalendar(self.current_year, self.current_month):
            for day in week:
                if day == 0:
                    grid.mount(Static(""))
                else:
                    grid.mount(Button(str(day), id=f"cal-day-{self._pfx}-{day}", classes="calendar-day"))

    @on(Button.Pressed)
    def handle_click(self, event: Button.Pressed):
        btn_id = event.button.id or ""
        if btn_id == f"cal-prev-{self._pfx}":
            self.current_month -= 1
            if self.current_month == 0:
                self.current_month = 12
                self.current_year -= 1
            self.update_calendar()
            event.stop()
        elif btn_id == f"cal-next-{self._pfx}":
            self.current_month += 1
            if self.current_month == 13:
                self.current_month = 1
                self.current_year += 1
            self.update_calendar()
            event.stop()
        elif btn_id == f"cal-close-{self._pfx}":
            self.add_class("hidden")
            event.stop()
        elif event.button.has_class("calendar-day"):
            day = int(event.button.label.plain)
            selected = date(self.current_year, self.current_month, day)
            self.app.query_one(f"#{self.target_input_id}", Input).value = selected.strftime("%Y-%m-%d")
            self.add_class("hidden")
            event.stop()

import json


class BacktestApp(App):
    SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config", "ui_settings.json")
    CSS = """
    Screen {
        background: #0a0a0a;
        layers: base overlay;
        color: #eeeeee;
        layout: vertical;
    }

    Header { background: #1a1a1a; color: #00ffff; text-style: bold; border-bottom: solid #333333; }
    Footer { background: #1a1a1a; color: #00ffff; border-top: solid #333333; }
    Footer .footer--key { color: #ff00ff; }

    #main-layout { padding: 0; margin: 0; height: 1fr; }
    #config-column { width: 45; }
    .btop-box { border: heavy #333333; background: #0a0a0a; margin: 0 1; height: 1fr; }
    .btop-box:focus-within { border: heavy #00ffff; }
    .box-title { color: #00ffff; background: #1a1a1a; text-style: bold; width: 100%; text-align: center; margin-top: -1; margin-bottom: 1; }
    .section-header { color: #ff00ff; text-style: bold; margin-top: 1; margin-bottom: 0; text-align: center; background: #1a1a1a; }

    Label { color: #888888; text-style: bold; margin: 0; }
    TabPane Label { margin-top: 1; }
    Input { border: none; background: #1a1a1a; color: #00ff00; height: 1; margin-bottom: 0; }
    Select { border: none; background: #1a1a1a; color: #ffff00; }
    SelectionList { border: none; background: #1a1a1a; height: 8; }

    Button { background: #333333; color: #ffffff; border: none; height: 1; margin-top: 1; }
    Button:hover { background: #00ffff; color: #000000; }
    Button:disabled { background: #222222; color: #555555; }

    #run-btn { background: #ff00ff; color: #ffffff; text-style: bold; height: 3; margin-top: 1; width: 100%; }
    #run-btn:disabled { background: #550055; color: #888888; }

    .sel-btn-row { height: 2; margin-bottom: 0; }
    #select-all-btn { background: #005500; }
    #deselect-all-btn { background: #550000; }

    CalendarWidget {
        width: 36;
        height: auto;
        border: heavy #00ffff;
        background: #111827;
        layer: overlay;
        offset: 46 5;
        padding: 1;
    }
    .cal-container { width: 100%; }
    .cal-close-btn { background: #550000; color: #ffffff; min-width: 4; height: 1; margin-left: 1; }
    .cal-close-btn:hover { background: #ff0000; }
    .hidden { display: none; }
    .cal-header { height: 3; align: center middle; }
    .cal-month-label { width: 15; text-align: center; color: #00ffff; }
    .cal-grid { grid-size: 7; grid-gutter: 0; height: auto; }
    .day-header { text-align: center; color: #ffff00; }
    .calendar-day { min-width: 4; height: 1; border: none; padding: 0; }

    DataTable { height: 1fr; border: none; background: #0a0a0a; color: #eeeeee; }
    .stat-container { height: 4; margin-bottom: 1; padding: 0 1; width: 25%; background: #111111; border: solid #333333; align: center middle; }
    .stat-container Label { margin: 0; width: 100%; text-align: center; }
    .stat-value { color: #00ff00; text-style: bold; }
    .stat-bar { background: #222222; color: #00ff00; width: 100%; height: 1; margin-top: 0; }

    Collapsible { background: #1a1a1a; border: none; margin-top: 1; }
    Collapsible > .collapsible--title { color: #00ffff; text-style: bold; }

    TabPane { padding: 1; }
    Switch { margin-top: 1; }

    .indicator-collapsible {
        background: #0f172a;
        border: none;
        margin-bottom: 0;
        margin-top: 0;
    }
    .indicator-collapsible > .collapsible--title {
        color: #00ffff;
        background: #111111;
        text-style: bold;
        border-bottom: solid #333333;
        padding: 0 1;
    }
    .indicator-collapsible > .collapsible--title:hover {
        background: #1e293b;
        color: #ffffff;
    }

    .inline-field { height: 3; align: left middle; padding: 0 1; }
    .inline-field Label { width: 18; color: #888888; margin: 0; }
    .inline-field Input { width: 10; color: #00ff00; margin: 0; }
    .inline-field Switch { margin: 0; }
    #stats-column { width: 1fr; }
    #top-shortcuts {
        background: #111111;
        color: #888888;
        text-align: center;
        width: 100%;
        height: 1;
        margin: 0;
        padding: 0 1;
        border-bottom: solid #333333;
    }
    #date-row, #date-row-end { height: 3; }
    ProgressBar {
        width: 100%;
        margin-top: 1;
        display: none;
    }
    
    ProgressBar > .bar--bar {
        background: #00ffff;
    }
    
    ProgressBar > .bar--complete {
        background: #00ff00;
    }

    ProgressBar.visible {
        display: block;
    }

    #config-column { width: 45; }
    #stats-row { height: 6; margin-bottom: 1; }
    
    #config-footer { 
        height: auto; 
        border-top: solid #333333; 
        padding: 1; 
        background: #111111;
    }
    
    #status-label { 
        color: #00ffff; 
        text-align: center; 
        width: 100%; 
        height: 1; 
        margin-bottom: 1;
        text-style: bold;
    }

    #btn-row {
        height: 3;
        margin-top: 1;
    }

    #run-btn { width: 1fr; }
    #cancel-btn { width: 12; margin-left: 1; display: none; }
    #cancel-btn.visible { display: block; }
    
    Input:disabled { color: #444444; background: #111111; }

    /* Results tabs */
    #results-tabs { height: 1fr; }
    #tab-trades { padding: 0; }
    #tab-chart  { padding: 0; }
    #tab-stats  { padding: 0 1; }
    .chart-btn { width: 100%; margin: 1 0; display: none; }
    .chart-btn.visible { display: block; }
    #save-btn { width: 100%; margin: 2 0 1 0; background: #ff8800; color: #000000; text-style: bold; height: 3; display: none; }
    #save-btn.visible { display: block; }
    #save-btn:hover { background: #ffaa00; }
    
    #top-shortcuts {
        background: #1a1a1a;
        color: #ff00ff;
        text-align: center;
        width: 100%;
        margin: 0;
        margin-bottom: 1;
        border-bottom: solid #333333;
        height: 1;
        text-style: bold;
    }
    
    #app-logo {
        color: #ffff00;
        text-align: center;
        width: 100%;
        height: 12;
        margin: 1 0;
        overflow: hidden;
    }
    
    ChartWidget { height: 1fr; background: #0a0a0a; padding: 0; }
    ChartWidget:focus { border: solid #00ffff; }
    .chart-info-row { height: 1fr; }
    #ext-metrics { width: 36; padding: 0 1; border-right: solid #333333; }
    #ext-metrics-content { color: #eeeeee; height: auto; }
    #sym-breakdown { width: 1fr; }
    #symbol-table { height: 1fr; border: none; background: #0a0a0a; }
    
    /* Date validation additions */
    .date-status-ok { color: #00ff00; }
    .date-status-fail { color: #ff0000; }
    #min-date-hint { color: #555555; text-align: right; width: 1fr; }
    .date-header-row { height: 2; align: left middle; }
    .date-header-row Label { margin-top: 0; }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "QUIT"),
        Binding("ctrl+c", "quit", "QUIT"),
        Binding("r", "run", "RUN SEQUENCE"),
        Binding("d", "toggle_dark", "DARK MODE"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sort_states = {} # Tracks column_key -> ascending (bool)
        self._active_settings = {}

    def rebuild_strategy_and_risk_tabs(self, strategy_name: str) -> None:
        schema = STRATEGY_SCHEMAS.get(strategy_name, STRATEGY_SCHEMAS["EMA_CROSS"])
        
        # 1. Rebuild Strategy Tab
        try:
            strat_container = self.query_one("#dynamic-strategy-container", VerticalScroll)
            strat_container.remove_children()
            
            for section_name, fields in schema.items():
                if section_name == "RISK": continue
                widgets = []
                for field_name, field_info in fields.items():
                    w_id = f"opt_{strategy_name}_{field_name}".lower()
                    val = field_info["default"]
                    
                    if hasattr(self, "_active_settings") and self._active_settings:
                        val = self._active_settings.get(w_id, val)
                    
                    widgets.append(Label(field_info["label"]))
                    if field_info["type"] == "bool":
                        widgets.append(Switch(value=bool(val), id=w_id))
                    else:
                        widgets.append(Input(str(val), id=w_id))
                
                if widgets:
                    strat_container.mount(
                        Collapsible(
                            *widgets,
                            title=f"{section_name} CONFIGURATION",
                            classes="indicator-collapsible"
                        )
                    )
        except Exception:
            pass
            
        # 2. Rebuild Dynamic Risk Container
        try:
            risk_container = self.query_one("#dynamic-risk-container", Vertical)
            risk_container.remove_children()
            
            for field_name, field_info in schema.get("RISK", {}).items():
                w_id = f"opt_{strategy_name}_{field_name}".lower()
                val = field_info["default"]
                if hasattr(self, "_active_settings") and self._active_settings:
                    val = self._active_settings.get(w_id, val)
                    
                control = Switch(value=bool(val), id=w_id) if field_info["type"] == "bool" else Input(str(val), id=w_id)
                
                row = Horizontal(
                    Label(field_info["label"]),
                    control,
                    classes="inline-field"
                )
                risk_container.mount(row)
        except Exception:
            pass

    @on(Select.Changed, "#strategy-select")
    def on_strategy_changed(self, event: Select.Changed) -> None:
        if event.value:
            # CRITICAL: Save current visual adjustments BEFORE unmounting the widgets,
            # otherwise pending unsaved changes are annihilated during rebuilding!
            self._save_ui_settings()
            self.rebuild_strategy_and_risk_tabs(event.value)

    def on_mount(self) -> None:
        self.title = "EGGSHELL BACKTESTER v1.1"
        # Delay loading until compose is finished so widgets exist
        self.call_after_refresh(self._load_ui_settings)

    def _save_ui_settings(self) -> None:
        """UNIFIED UNIVERSAL SAVER: Directly mirrors the visual DOM into persistent state."""
        try:
            # 1. Seed with existing cache to preserve unmounted widget states
            settings = dict(getattr(self, "_active_settings", {}))

            # 2. Automatically reflect EVERY ACTIVE WIDGET in the app directly by ID!
            for widget in self.query("Input, Select, Switch"):
                if widget.id:
                    # Map generic ID from component directly to memory key
                    settings[widget.id] = widget.value

            # 3. Handle special multi-select checkboxes
            settings["assets"] = [str(cb.label) for cb in self.query("#asset-checkbox-container Checkbox") if cb.value]

            # 4. Immediate synchronization to system RAM cache!
            self._active_settings = settings

            # 5. Write final snapshot to physical disk
            with open(self.SETTINGS_FILE, "w") as f:
                json.dump(settings, f, indent=4)
        except Exception:
            pass

    def _load_ui_settings(self) -> None:
        """UNIFIED UNIVERSAL LOADER: Hydrates existing interface dynamically from dataset."""
        # Establish startup base state
        default_strat = list(STRATEGY_SCHEMAS.keys())[0] if STRATEGY_SCHEMAS else None
        
        if not os.path.exists(self.SETTINGS_FILE):
            self.rebuild_strategy_and_risk_tabs(default_strat)
            return

        try:
            with open(self.SETTINGS_FILE, "r") as f:
                loaded = json.load(f)
            
            # Pre-seed memory cache
            self._active_settings = loaded

            # 1. Perform universal DOM hydration for root components
            for widget in self.query("Input, Select, Switch"):
                if widget.id and widget.id in loaded:
                    try:
                        widget.value = loaded[widget.id]
                    except Exception: pass

            # 2. Trigger strategy-specific sub-DOM reconstruction
            strat_to_load = loaded.get("strategy-select", default_strat)
            self.rebuild_strategy_and_risk_tabs(strat_to_load)
            
            # 3. Automatically restore checkboxes
            saved_assets = set(loaded.get("assets", ["BTCUSDT"]))
            for cb in self.query("#asset-checkbox-container Checkbox"):
                cb.value = str(cb.label) in saved_assets
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        # Rebranded Logo
        logo_ascii = """
             .@@@@.
            @@@@@@@@
           @@@@@@@@@@   ..
          @@@@@@@%---   @@.
          @@@@@. .@@@   %%.
          @@@@@. .@@@   ..
          @@@@@@#@@@@  ..
          @@@@@@@@#**.@@.
          @@@@@@@@@@@@@.
           @@@@@@@@@@@
            -@@@@@@@-
        """
        
        yield Header(show_clock=True)
        with Horizontal(id="main-layout"):
            with Vertical(classes="btop-box", id="config-column"):
                with VerticalScroll(id="config-scroll"):
                    yield Static(logo_ascii, id="app-logo")
                    yield Label("── EGGSHELL BACKTESTER v1.1 ──", classes="box-title")
                    with TabbedContent():
                        with TabPane("STRATEGY SELECT"):
                            with VerticalScroll():
                                yield Label("CHOOSE ACTIVE STRATEGY", classes="box-subtitle")
                                yield Select(
                                    [(k.replace("_", " ").title(), k) for k in STRATEGY_SCHEMAS.keys()],
                                    value=list(STRATEGY_SCHEMAS.keys())[0] if STRATEGY_SCHEMAS else None, 
                                    id="strategy-select",
                                )
                        with TabPane("BASIC"):
                            with VerticalScroll():
                                with Collapsible(title="ASSET SELECTION", id="asset-collapsible"):
                                    yield Input(placeholder="Search assets...", id="asset-search")
                                    with Horizontal(classes="sel-btn-row"):
                                        yield Button("SELECT ALL", id="select-all-btn")
                                        yield Button("DESELECT ALL", id="deselect-all-btn")
                                    with VerticalScroll(id="asset-checkbox-container"):
                                        df_constants = DataframeConstantsBinance()
                                        for sym in df_constants.ACTIVES:
                                            yield Checkbox(sym, value=(sym == "BTCUSDT"), id=f"check-{sym}", classes="asset-checkbox")

                                with Collapsible(title="CORE SETTINGS", collapsed=False):
                                    yield Label("INTERVAL")
                                    yield Select(
                                        [("15m", "15m"), ("1h", "1h"), ("4h", "4h"), ("1d", "1d")],
                                        value="1h", id="interval-select",
                                    )
                                    with Horizontal(classes="date-header-row"):
                                        yield Label("BALANCE ($) ")
                                        yield Label("●", id="balance-status", classes="date-status-ok")
                                    yield Input("1000", id="balance-input")
                                    with Horizontal(classes="date-header-row"):
                                        yield Label("RISK (%) PER TRADE ")
                                        yield Label("●", id="size-status", classes="date-status-ok")
                                    yield Input("20", id="size-input")

                                with Collapsible(title="TIME WINDOW"):
                                    with Horizontal(classes="date-header-row"):
                                        yield Label("START DATE ")
                                        yield Label("●", id="start-date-status", classes="date-status-ok")
                                        yield Label("(Min: 2017-01-01)", id="min-date-hint")
                                    with Horizontal(id="date-row"):
                                        yield Input("2023-01-01", id="start-date-input")
                                        yield Button("PICK", id="start-cal-btn")
                                    with Horizontal(classes="date-header-row"):
                                        yield Label("END DATE ")
                                        yield Label("● NOW", id="end-date-status", classes="date-status-ok")
                                    with Horizontal(id="date-row-end"):
                                        yield Input("", id="end-date-input", placeholder="Now")
                                        yield Button("PICK", id="end-cal-btn")

                        with TabPane("STRATEGY"):
                            yield VerticalScroll(id="dynamic-strategy-container")

                        with TabPane("RISK"):
                            with VerticalScroll():
                                with Horizontal(classes="inline-field"):
                                    yield Label("COOLDOWN (CANDLES)")
                                    yield Input("0", id="cooldown-input")
                                    yield Label("●", id="cooldown-status", classes="date-status-ok")
                                yield Vertical(id="dynamic-risk-container")

                with Vertical(id="config-footer"):
                    yield Label("SYSTEM IDLE", id="status-label")
                    yield ProgressBar(id="main-progress", total=100, show_eta=True)
                    with Horizontal(id="btn-row"):
                        yield Button("EXECUTE SEQUENCE (R)", id="run-btn", variant="primary")
                        yield Button("CANCEL", id="cancel-btn", variant="error")

                yield CalendarWidget(target_input_id="start-date-input", id="start-calendar", classes="hidden")
                yield CalendarWidget(target_input_id="end-date-input", id="end-calendar", classes="hidden")

            with Vertical(classes="btop-box", id="stats-column"):
                yield Label("── REAL-TIME ANALYTICS ──", classes="box-title")
                yield Label(
                    "[bold magenta][R][/bold magenta] RUN SEQUENCE  │  "
                    "[bold magenta][Ctrl+C][/bold magenta] QUIT  │  "
                    "[bold magenta][D][/bold magenta] DARK MODE", 
                    id="top-shortcuts"
                )
                with Horizontal(id="stats-row"):
                    with Vertical(classes="stat-container"):
                        yield Label("TOTAL ROI")
                        yield Label("0.00%", id="stat-return", classes="stat-value")
                        yield Static("░" * 20, id="bar-return", classes="stat-bar")
                    with Vertical(classes="stat-container"):
                        yield Label("WIN RATE")
                        yield Label("0.0%", id="stat-winrate", classes="stat-value")
                        yield Static("░" * 20, id="bar-winrate", classes="stat-bar")
                    with Vertical(classes="stat-container"):
                        yield Label("TRADES")
                        yield Label("0", id="stat-trades", classes="stat-value")
                        yield Static("░" * 20, id="bar-trades", classes="stat-bar")
                    with Vertical(classes="stat-container"):
                        yield Label("P&L")
                        yield Label("$0.00", id="stat-final", classes="stat-value")
                        yield Static("░" * 20, id="bar-final", classes="stat-bar")

                with TabbedContent(id="results-tabs"):
                    with TabPane("TRADES", id="tab-trades"):
                        table = DataTable(id="trades-table", cursor_type="row")
                        table.add_columns("DATE", "TYPE", "SYMBOL", "INVESTED", "QTY", "BUY", "SELL", "TRADE %", "ACCT %")
                        yield table
                    with TabPane("CHART", id="tab-chart"):
                        with Vertical():
                            yield Button("SAVE BACKTEST", id="save-btn")
                            yield Button("FULL PORTFOLIO CHART", id="open-chart-main", variant="success", classes="chart-btn")
                            yield Button("TRADES CHART", id="open-chart-trades", variant="primary", classes="chart-btn")
                            yield Button("TOP DRAWDOWNS CHART", id="open-chart-drawdowns", variant="error", classes="chart-btn")
                            yield Button("CUMULATIVE RETURNS", id="open-chart-returns", variant="success", classes="chart-btn")
                            yield Button("CASH FLOW BALANCE", id="open-chart-cash", variant="primary", classes="chart-btn")
                            yield Button("PORTFOLIO VALUE", id="open-chart-value", variant="default", classes="chart-btn")
                            yield Button("UNDERWATER CHART (DEEP DIVE)", id="open-chart-underwater", variant="warning", classes="chart-btn")
                    with TabPane("STATS", id="tab-stats"):
                        with Horizontal(classes="chart-info-row"):
                            with VerticalScroll(id="ext-metrics"):
                                yield Label("── EXTENDED METRICS ──", classes="box-title")
                                yield Static("", id="ext-metrics-content")
                            with Vertical(id="sym-breakdown"):
                                yield Label("── PER SYMBOL ──", classes="box-title")
                                sym_table = DataTable(id="symbol-table", cursor_type="row")
                                sym_table.add_columns("SYMBOL", "TRADES", "WIN RATE", "TOTAL %")
                                yield sym_table
                    with TabPane("LOGS", id="tab-logs"):
                        yield RichLog(id="main-log", highlight=True, markup=True)

    @on(Button.Pressed, "#start-cal-btn")
    def show_start_cal(self) -> None:
        self.query_one("#start-calendar").toggle_class("hidden")

    @on(Button.Pressed, "#end-cal-btn")
    def show_end_cal(self) -> None:
        self.query_one("#end-calendar").toggle_class("hidden")

    @on(Input.Changed, "#asset-search")
    def filter_assets(self, event: Input.Changed) -> None:
        """Filter the asset checkboxes based on search query."""
        query = event.value.upper()
        container = self.query_one("#asset-checkbox-container", VerticalScroll)
        for checkbox in container.query(Checkbox):
            checkbox.display = query in str(checkbox.label).upper()

    @on(Input.Changed, "#start-date-input")
    def validate_start_date(self, event: Input.Changed) -> None:
        val = event.value.strip()
        indicator = self.query_one("#start-date-status", Label)
        hint = self.query_one("#min-date-hint", Label)
        inpt = event.input
        
        if not val:
            indicator.update("?")
            indicator.set_classes("")
            return

        try:
            # 1. Syntactic / Logic validation
            dt = datetime.strptime(val, "%Y-%m-%d")
            min_dt = datetime(2017, 1, 1) # Earliest usable history for generic assets
            
            if dt < min_dt:
                raise ValueError("DATE PRIOR TO MINIMUM HISTORY")
            if dt > datetime.now():
                raise ValueError("FUTURE DATES PROHIBITED")
                
            # SUCCESS STATE
            indicator.update("● READY")
            indicator.set_classes("date-status-ok")
            hint.update("(Valid Range)")
            hint.styles.color = "#00ff00"
            inpt.styles.color = "#00ff00" # Set input text green on valid
            
        except Exception as e:
            # ERROR STATE
            indicator.update("✖ INVALID")
            indicator.set_classes("date-status-fail")
            hint.update(f"(Err: {str(e)[:15]})")
            hint.styles.color = "#ff0000"
            inpt.styles.color = "#ff0000" # Set input text red on fail

    @on(Input.Changed, "#balance-input")
    def validate_balance(self, event: Input.Changed) -> None:
        val = event.value.strip()
        inpt = event.input
        indicator = self.query_one("#balance-status", Label)
        try:
            if not val:
                raise ValueError("REQUIRED")
            if float(val) <= 0:
                raise ValueError("MUST BE > 0")
            indicator.update("●")
            indicator.set_classes("date-status-ok")
            inpt.styles.color = "#00ff00"
        except Exception:
            indicator.update("✖")
            indicator.set_classes("date-status-fail")
            inpt.styles.color = "#ff0000"

    @on(Input.Changed, "#size-input")
    def validate_size(self, event: Input.Changed) -> None:
        val = event.value.strip()
        inpt = event.input
        indicator = self.query_one("#size-status", Label)
        try:
            if not val:
                raise ValueError("REQUIRED")
            f = float(val)
            if not (0.1 <= f <= 100):
                raise ValueError("RANGE 0.1–100")
            indicator.update("●")
            indicator.set_classes("date-status-ok")
            inpt.styles.color = "#00ff00"
        except Exception:
            indicator.update("✖")
            indicator.set_classes("date-status-fail")
            inpt.styles.color = "#ff0000"

    @on(Input.Changed, "#cooldown-input")
    def validate_cooldown(self, event: Input.Changed) -> None:
        val = event.value.strip()
        inpt = event.input
        indicator = self.query_one("#cooldown-status", Label)
        try:
            if not val:
                raise ValueError("REQUIRED")
            if int(val) < 0:
                raise ValueError("MUST BE >= 0")
            indicator.update("●")
            indicator.set_classes("date-status-ok")
            inpt.styles.color = "#00ff00"
        except Exception:
            indicator.update("✖")
            indicator.set_classes("date-status-fail")
            inpt.styles.color = "#ff0000"

    @on(Input.Changed, "#end-date-input")
    def validate_end_date(self, event: Input.Changed) -> None:
        val = event.value.strip()
        inpt = event.input
        indicator = self.query_one("#end-date-status", Label)
        if not val:
            indicator.update("● NOW")
            indicator.set_classes("date-status-ok")
            inpt.styles.color = "#00ff00"
            return
        try:
            dt = datetime.strptime(val, "%Y-%m-%d")
            start_val = self.query_one("#start-date-input", Input).value.strip()
            if start_val:
                start_dt = datetime.strptime(start_val, "%Y-%m-%d")
                if dt <= start_dt:
                    raise ValueError("MUST BE AFTER START")
            indicator.update("● READY")
            indicator.set_classes("date-status-ok")
            inpt.styles.color = "#00ff00"
        except Exception:
            indicator.update("✖ INVALID")
            indicator.set_classes("date-status-fail")
            inpt.styles.color = "#ff0000"

    @on(Input.Changed)
    def validate_opt_input(self, event: Input.Changed) -> None:
        w_id = event.input.id or ""
        if not w_id.startswith("opt_"):
            return
        val = event.value.strip()
        inpt = event.input
        try:
            strategy_name = self.query_one("#strategy-select", Select).value
            prefix = f"opt_{strategy_name.lower()}_"
            if not w_id.startswith(prefix):
                return
            field_key = w_id[len(prefix):].upper()
            schema = STRATEGY_SCHEMAS.get(strategy_name, {})
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

    @on(Button.Pressed, "#select-all-btn")
    def select_all(self) -> None:
        container = self.query_one("#asset-checkbox-container", VerticalScroll)
        for checkbox in container.query(Checkbox):
            if checkbox.display: # Only select visible ones? Or all? Usually all.
                checkbox.value = True

    @on(Button.Pressed, "#deselect-all-btn")
    def deselect_all(self) -> None:
        container = self.query_one("#asset-checkbox-container", VerticalScroll)
        for checkbox in container.query(Checkbox):
            checkbox.value = False

    @on(Button.Pressed, "#run-btn")
    def on_run_pressed(self) -> None:
        self._save_ui_settings() # Save settings whenever we run a backtest
        self.action_run()



    def _collect_params(self) -> tuple[dict | None, str | None]:
        try:
            assets = [
                str(cb.label) for cb in self.query("#asset-checkbox-container Checkbox")
                if cb.value
            ]
            
            if not assets:
                return None, "SELECT AT LEAST ONE ASSET, CAPTAIN."

            interval = self.query_one("#interval-select", Select).value
            bal_raw = self.query_one("#balance-input", Input).value
            sz_raw = self.query_one("#size-input", Input).value
            balance = float(bal_raw) if bal_raw else 1000.0
            size = float(sz_raw) if sz_raw else 20.0
            start_date = self.query_one("#start-date-input", Input).value
            end_date = self.query_one("#end-date-input", Input).value or None
            cooldown_v = self.query_one("#cooldown-input", Input).value
            cooldown = int(cooldown_v) if cooldown_v and cooldown_v.strip() != "" else 0
            
            strategy_name = self.query_one("#strategy-select", Select).value
            adv_params = {
                "STRATEGY": strategy_name
            }
            schema = STRATEGY_SCHEMAS.get(strategy_name, STRATEGY_SCHEMAS["EMA_CROSS"])
            
            # Combine all fields from STRATEGY and RISK sections of the schema
            all_fields = {}
            for section in ["STRATEGY", "RISK"]:
                all_fields.update(schema.get(section, {}))
                
            for field, info in all_fields.items():
                w_id = f"opt_{strategy_name}_{field}".lower()
                try:
                    val = self.query_one(f"#{w_id}").value
                    if info["type"] == "bool":
                        adv_params[field] = bool(val)
                    elif info["type"] == "int":
                        adv_params[field] = int(val) if str(val).strip() != "" else info["default"]
                    elif info["type"] == "float":
                        adv_params[field] = float(val) if str(val).strip() != "" else info["default"]
                except Exception:
                    # Fallback to previously active loaded setting if widget is detached
                    if hasattr(self, "_active_settings") and w_id in self._active_settings:
                        adv_params[field] = self._active_settings[w_id]
                    else:
                        adv_params[field] = info["default"]
                        
            enabled_sell = adv_params.get("ENABLED_SELL", True)
            return {
                "assets": assets, "interval": interval, "balance": balance, "size": size,
                "start_date": start_date, "end_date": end_date, "adv_params": adv_params,
                "cooldown": cooldown, "accumulate": not enabled_sell,
            }, None
        except ValueError as exc:
            return None, f"INVALID INPUT: {exc}"

    def action_run(self) -> None:
        params, error = self._collect_params()
        if error:
            self.notify(error, severity="error")
            return
        
        self.cancelled = False
        run_btn = self.query_one("#run-btn", Button)
        can_btn = self.query_one("#cancel-btn", Button)
        run_btn.disabled = True
        run_btn.label = "PROCESSING..."
        can_btn.add_class("visible")
        
        progress = self.query_one("#main-progress", ProgressBar)
        progress.add_class("visible")
        progress.progress = 0
        
        self.query_one("#results-tabs", TabbedContent).active = "tab-logs"
        self.notify("INITIATING PORTFOLIO SEQUENCE...")
        Thread(target=self._run_backtest, kwargs=params, daemon=True).start()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.action_cancel()
        elif event.button.id == "save-btn":
            self._save_backtest()
        elif event.button.id and event.button.id.startswith("open-chart-"):
            chart_type = event.button.id.replace("open-chart-", "")
            if hasattr(self, "charts") and self.charts and chart_type in self.charts:
                try:
                    webbrowser.open(f"file://{self.charts[chart_type]}")
                    self.notify(f"Opened {chart_type} chart in browser!", severity="information")
                except Exception as e:
                    self.notify(f"Could not open browser: {e}", severity="error")
            else:
                self.notify(f"Chart '{chart_type}' not generated.", severity="warning")
        # ... (calendar buttons logic if needed)

    def _save_backtest(self) -> None:
        import shutil, csv
        results = getattr(self, "_last_results", None)
        trades  = getattr(self, "_last_trades", [])
        if not results:
            self.notify("NO BACKTEST TO SAVE.", severity="warning")
            return

        proj_root  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_dir   = os.path.join(proj_root, "reports", "results", timestamp)
        charts_out = os.path.join(save_dir, "charts")
        os.makedirs(charts_out, exist_ok=True)

        # ── 1. Copy charts and build local paths ─────────────────────────────
        saved_charts = {}
        source_charts = results.get("charts", {})
        for key, src_path in source_charts.items():
            if src_path and os.path.exists(src_path):
                dst = os.path.join(charts_out, os.path.basename(src_path))
                shutil.copy2(src_path, dst)
                saved_charts[key] = dst

        # ── 2. Stats log (plain text) ─────────────────────────────────────────
        stats_path = os.path.join(save_dir, "stats.txt")
        with open(stats_path, "w") as f:
            f.write(f"EGGSHELL BACKTESTER — RESULTS SNAPSHOT\n")
            f.write(f"Saved: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"{'TOTAL ROI':<28}{results['total_return_pct']:+.2f}%\n")
            f.write(f"{'WIN RATE':<28}{results['win_rate']:.1f}%\n")
            f.write(f"{'TOTAL TRADES':<28}{results['total_trades']}\n")
            f.write(f"{'NET PROFIT':<28}${results['net_profit']:,.2f}\n")
            f.write(f"{'FINAL BALANCE':<28}${results['final_balance']:,.2f}\n")
            f.write(f"{'MAX DRAWDOWN':<28}{results['max_drawdown_pct']:.2f}%\n")
            f.write(f"{'SHARPE RATIO':<28}{results['sharpe_ratio']:.4f}\n")
            f.write(f"{'SORTINO RATIO':<28}{results['sortino_ratio']:.4f}\n")
            f.write(f"{'CALMAR RATIO':<28}{results['calmar_ratio']:.4f}\n")
            f.write(f"{'PROFIT FACTOR':<28}{results['profit_factor']:.4f}\n")
            f.write(f"{'BEST TRADE':<28}{results['best_trade']:+.2f}%\n")
            f.write(f"{'WORST TRADE':<28}{results['worst_trade']:+.2f}%\n")
            f.write(f"{'AVG HOLD TIME':<28}")
            h = results.get("avg_hold_hours", 0)
            f.write(f"{h:.1f}h\n" if h < 48 else f"{h/24:.1f}d\n")
            f.write(f"{'BUY & HOLD':<28}{results.get('buy_hold_pct', 0):+.2f}%\n")
            f.write("\n── FULL VECTORBT STATS ──\n")
            for k, v in results.get("full_stats", {}).items():
                f.write(f"{str(k)[:28]:<28}{v}\n")
            f.write("\n── PER-SYMBOL BREAKDOWN ──\n")
            for sym, s in sorted(results.get("symbol_stats", {}).items()):
                wr_s = s["wins"] / s["trades"] * 100 if s["trades"] else 0
                f.write(f"{sym:<14} trades={s['trades']:>4}  winrate={wr_s:5.1f}%  total={s['total_pct']:+.2f}%\n")

        # ── 3. Trades CSV ─────────────────────────────────────────────────────
        trades_path = os.path.join(save_dir, "trades.csv")
        if trades:
            fieldnames = ["symbol", "buy_time", "sell_time", "buy_price", "sell_price",
                          "quantity", "investment", "profit_pct", "account_profit_pct", "profit_usd"]
            with open(trades_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(trades)

        # ── 4. HTML links file ────────────────────────────────────────────────
        links_path = os.path.join(save_dir, "charts_links.html")
        with open(links_path, "w") as f:
            f.write("<!DOCTYPE html><html><head><meta charset='utf-8'>")
            f.write("<title>Backtest Charts</title>")
            f.write("<style>body{background:#0a0a0a;color:#eee;font-family:monospace;padding:2em;}")
            f.write("h1{color:#00ffff;}a{color:#ff8800;display:block;margin:.5em 0;font-size:1.1em;}</style>")
            f.write("</head><body>")
            f.write(f"<h1>EGGSHELL BACKTESTER — {timestamp}</h1>")
            labels = {"main": "Full Portfolio Chart", "trades": "Trades Chart",
                      "drawdowns": "Top Drawdowns", "returns": "Cumulative Returns",
                      "cash": "Cash Flow Balance", "value": "Portfolio Value",
                      "underwater": "Underwater Chart"}
            for key, dst in saved_charts.items():
                label = labels.get(key, key.title())
                f.write(f'<a href="file://{dst}">{label}</a>')
            f.write("</body></html>")

        self.notify(f"SAVED → reports/results/{timestamp}", severity="information")
        self.log_status(f"BACKTEST SAVED: {save_dir}", "success")

    def action_cancel(self) -> None:
        self.cancelled = True
        self.query_one("#status-label", Label).update("[bold red]ABORTING SEQUENCE...[/bold red]")
        self.log_status("ABORTING BACKTEST BY USER REQUEST", "warning")
        self.notify("ABORTING BACKTEST...", severity="warning")

    def log_status(self, msg: str, level: str = "info") -> None:
        colors = {"info": "cyan", "warning": "yellow", "error": "red", "success": "green"}
        color = colors.get(level, "white")
        log = self.query_one("#main-log", RichLog)
        time_str = datetime.now().strftime("%H:%M:%S")
        log.write(f"[[dim]{time_str}[/dim]] [[b {color}]{level.upper()}[/b {color}]] {msg}")

    def _run_backtest(self, assets, interval, balance, size, start_date, end_date, adv_params, cooldown, accumulate) -> None:
        try:
            progress = self.query_one("#main-progress", ProgressBar)
            status   = self.query_one("#status-label", Label)
            
            # Step 1: Data Download
            self.app.call_from_thread(lambda: self.log_status(f"FETCHING DATA: {len(assets)} ASSETS @ {interval}"))
            self.app.call_from_thread(lambda: status.update("DOWNLOADING HISTORICAL DATA..."))
            self.app.call_from_thread(lambda: progress.update(progress=10))
            if self.cancelled: return
            binance_df = Dataframe(actives=assets, interval=interval, start_date=start_date, end_date=end_date)
            self.app.call_from_thread(lambda: self.log_status(f"DATA ACQUIRED: {len(binance_df.df)} CANDLES LOADED", "success"))
            
            # Step 2: Signal Calculation
            self.app.call_from_thread(lambda: status.update("CALCULATING STRATEGY SIGNALS..."))
            self.app.call_from_thread(lambda: self.log_status("COMPUTING TECHNICAL INDICATORS..."))
            self.app.call_from_thread(lambda: progress.update(progress=40))
            if self.cancelled: return
            all_signals = []
            num_assets = len(assets) if len(assets) > 0 else 1
            for asset_idx, symbol in enumerate(assets):
                if self.cancelled: return
                symbol_df = binance_df.df[binance_df.df["symbol"] == symbol]
                if not symbol_df.empty:
                    self.app.call_from_thread(lambda s=symbol: self.log_status(f"PROCESSING SIGNALS: {s}"))
                    
                    def on_sub_progress(pct: float, msg: str = None):
                        if self.cancelled: return
                        base_val = 40 + (asset_idx / num_assets) * 30
                        step_val = (1.0 / num_assets) * 30 * pct
                        new_val = base_val + step_val
                        self.app.call_from_thread(lambda: progress.update(progress=new_val))
                        if msg:
                            self.app.call_from_thread(lambda: status.update(msg))
                            
                    sl = SignalLogic(symbol_df, on_progress=on_sub_progress, **adv_params)
                    all_signals.append(sl.df)
            
            if not all_signals:
                self.app.call_from_thread(lambda: self.log_status("NO MARKET DATA TO PROCESS", "error"))
                self.app.call_from_thread(lambda: self.notify("NO DATA FOUND.", severity="error"))
                return
            
            unified_signals = pd.concat(all_signals)
            
            # Step 3: Simulation
            self.app.call_from_thread(lambda: self.log_status("INITIALIZING VECTORBT ENGINE..."))
            self.app.call_from_thread(lambda: status.update("SIMULATING MARKET TRADES..."))
            self.app.call_from_thread(lambda: progress.update(progress=70))
            engine = BacktestEngine(unified_signals, initial_balance=balance, position_size_pct=size, cooldown=cooldown, accumulate=accumulate)
            
            def on_engine_progress(pct: float):
                if self.cancelled: return
                new_val = 70 + (pct * 30)
                self.app.call_from_thread(lambda: progress.update(progress=new_val))

            results = engine.run(on_progress=on_engine_progress)
            if self.cancelled: return
            
            self.app.call_from_thread(lambda: self.log_status(f"SIMULATION COMPLETE: {len(engine.trades)} TRADES EXECUTED", "success"))
            self.app.call_from_thread(lambda: progress.update(progress=100))
            self.app.call_from_thread(lambda: status.update("[bold green]BACKTEST COMPLETE[/bold green]"))
            self.app.call_from_thread(self._update_results, results, engine.trades)
            
        except Exception as e:
            import traceback
            import os
            self.app.call_from_thread(lambda: self.log_status(f"CRITICAL ERROR: {e}", "error"))
            proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            err_dir = os.path.join(proj_root, "reports", "errors")
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
        run_btn.label = "EXECUTE SEQUENCE (R)"
        can_btn.remove_class("visible")
        self.query_one("#main-progress", ProgressBar).remove_class("visible")
        self.query_one("#status-label", Label).update("SYSTEM IDLE")

    @staticmethod
    def _fill_bar(value: float, scale: float, width: int = 20) -> str:
        fill = max(0, min(width, int(value / scale)))
        return "█" * fill + "░" * (width - fill)

    def _update_results(self, results: dict, trades: list) -> None:
        # ── Top stat cards ──
        roi = results["total_return_pct"]
        wr  = results["win_rate"]
        pnl_val = results['net_profit']
        
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
        
        self.query_one("#bar-return", Static).update(self._fill_bar(roi, 2.0))
        self.query_one("#bar-winrate", Static).update(self._fill_bar(wr, 5.0))

        # ── TRADES tab ──
        table = self.query_one("#trades-table", DataTable)
        table.clear()
        for t in trades:
            color = "#00ff00" if t["profit_pct"] > 0 else "#ff0000"
            # Color code the type
            t_type = "LONG" # Currently engine only does longs
            type_display = f"[green]{t_type}[/green]" if t_type == "LONG" else f"[red]{t_type}[/red]"

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

        # ── CHART tab — multiple separate braille charts ──
        # Terminal charts disabled as per user request

        # ── STATS tab — extended metrics ──
        full_stats = results.get("full_stats", {})
        metrics_lines = []
        for k, v in full_stats.items():
            # Sanitize brackets out to prevent markup collision, then format width
            k_clean = str(k).replace("[", "(").replace("]", ")").upper()
            k_str = k_clean[:22].ljust(23)
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
        
        # Add existing custom calculated metrics
        h = results.get("avg_hold_hours", 0)
        hold_str = f"{h:.1f}h" if h < 48 else f"{h / 24:.1f}d"
        net_c  = "green" if results["net_profit"] >= 0 else "red"
        avg_t  = results.get("avg_trade_pct", 0)
        avg_c  = "green" if avg_t >= 0 else "red"
        
        metrics_lines.extend([
            "",
            "── EGGSHELL METRICS ──",
            f"[dim]{'NET PROFIT'.ljust(22)}[/dim][{net_c}]${results['net_profit']:,.2f}[/{net_c}]",
            f"[dim]{'AVG TRADE'.ljust(22)}[/dim][{avg_c}]{avg_t:+.2f}%[/{avg_c}]",
            f"[dim]{'AVG HOLD TIME'.ljust(22)}[/dim][cyan]{hold_str}[/cyan]"
        ])
        
        self.query_one("#ext-metrics-content", Static).update("\n".join(metrics_lines))


        # Reveal chart buttons if their respective reports exist
        self.charts = results.get("charts", {})
        
        import os
        for btn in self.query(".chart-btn"):
            chart_type = btn.id.replace("open-chart-", "")
            if self.charts and chart_type in self.charts and os.path.exists(self.charts[chart_type]):
                btn.add_class("visible")
            else:
                btn.remove_class("visible")

        # ── CHART tab — per-symbol breakdown ──
        sym_table = self.query_one("#symbol-table", DataTable)
        sym_table.clear()
        for sym, s in sorted(results.get("symbol_stats", {}).items()):
            wr_s = s["wins"] / s["trades"] * 100 if s["trades"] else 0
            col  = "#00ff00" if s["total_pct"] >= 0 else "#ff0000"
            sym_table.add_row(
                sym.replace("USDT", ""),
                str(s["trades"]),
                f"{wr_s:.1f}%",
                f"[{col}]{s['total_pct']:+.2f}%[/]",
            )

        self._last_results = results
        self._last_trades = trades
        self.query_one("#save-btn", Button).add_class("visible")

        self.notify("PORTFOLIO SEQUENCE COMPLETE.", severity="information")
        self.query_one("#results-tabs", TabbedContent).active = "tab-stats"

    @on(DataTable.HeaderSelected)
    def on_header_click(self, event: DataTable.HeaderSelected):
        # Toggle sort direction
        current_asc = self.sort_states.get(event.column_key, True)
        new_asc = not current_asc
        self.sort_states[event.column_key] = new_asc
        
        # Smart sorting key
        def sort_key(value):
            if not isinstance(value, str):
                return value
            clean = value.replace("$", "").replace("%", "")
            if "[" in clean and "]" in clean:
                while "[" in clean and "]" in clean:
                    start = clean.find("[")
                    end = clean.find("]") + 1
                    clean = clean[:start] + clean[end:]
            try:
                return float(clean)
            except ValueError:
                return clean.lower()

        if event.data_table.row_count:
            event.data_table.sort(event.column_key, key=sort_key, reverse=not new_asc)


if __name__ == "__main__":
    BacktestApp().run()