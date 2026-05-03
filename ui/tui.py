from binance_service.dataframe import Dataframe
from core.signal_logic import SignalLogic
from core.backtest_engine import BacktestEngine
from core.constants import DataframeConstantsBinance

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

def _build_dynamic_schema():
    schema = {"STRATEGY": {}}
    sig = inspect.signature(SignalLogic.__init__)
    for name, param in sig.parameters.items():
        if name in ['self', 'df', 'kwargs', 'args', 'ENABLED_SELL', 'BUY_LEVEL', 'SELL_LEVEL']: continue
        t = "str"
        if param.annotation == bool or isinstance(param.default, bool): t = "bool"
        elif param.annotation == int or isinstance(param.default, int): t = "int"
        elif param.annotation == float or isinstance(param.default, float): t = "float"
        schema["STRATEGY"][name] = {
            "type": t,
            "default": param.default if param.default != inspect.Parameter.empty else "",
            "label": name.replace("_", " ")
        }
    return schema

INDICATOR_SCHEMA = _build_dynamic_schema()

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
    SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "ui_settings.json")
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

    def on_mount(self) -> None:
        self.title = "EGGSHELL BACKTESTER v1.0"
        # Delay loading until compose is finished so widgets exist
        self.call_after_refresh(self._load_ui_settings)

    def _save_ui_settings(self) -> None:
        try:
            settings = {
                "interval": self.query_one("#interval-select", Select).value,
                "balance": self.query_one("#balance-input", Input).value,
                "size": self.query_one("#size-input", Input).value,
                "start_date": self.query_one("#start-date-input", Input).value,
                "end_date": self.query_one("#end-date-input", Input).value,
                "accumulate": self.query_one("#toggle-accumulate", Switch).value,
                "max_pos": self.query_one("#max-pos", Input).value,
                "max_pos_enabled": self.query_one("#toggle-max-pos", Switch).value,
                "assets": [str(cb.label) for cb in self.query("#asset-checkbox-container Checkbox") if cb.value]
            }
            for section, fields in INDICATOR_SCHEMA.items():
                for field, info in fields.items():
                    try:
                        widget = self.query_one(f"#strat_{field}")
                        settings[f"strat_{field}"] = widget.value
                    except Exception: pass
            
            # Manually save Risk-located strategy params
            try:
                settings["strat_ENABLED_SELL"] = self.query_one("#strat_ENABLED_SELL", Switch).value
                settings["strat_BUY_LEVEL"] = self.query_one("#strat_BUY_LEVEL", Input).value
                settings["strat_SELL_LEVEL"] = self.query_one("#strat_SELL_LEVEL", Input).value
            except Exception: pass

            with open(self.SETTINGS_FILE, "w") as f:
                json.dump(settings, f, indent=4)
        except Exception:
            pass

    def _load_ui_settings(self) -> None:
        if not os.path.exists(self.SETTINGS_FILE):
            return
        try:
            with open(self.SETTINGS_FILE, "r") as f:
                s = json.load(f)
            
            # Helper to set value if key exists
            def set_v(id, val):
                try:
                    w = self.query_one(id)
                    if isinstance(w, (Input, Select, Switch)):
                        w.value = val
                except Exception: pass

            set_v("#interval-select", s.get("interval", "1h"))
            set_v("#balance-input", s.get("balance", "1000"))
            set_v("#size-input", s.get("size", "20"))
            set_v("#start-date-input", s.get("start_date", "2023-01-01"))
            set_v("#end-date-input", s.get("end_date", ""))
            set_v("#toggle-accumulate", s.get("accumulate", False))
            set_v("#max-pos", s.get("max_pos", "5"))
            set_v("#toggle-max-pos", s.get("max_pos_enabled", False))
            
            for section, fields in INDICATOR_SCHEMA.items():
                for field, info in fields.items():
                    val = s.get(f"strat_{field}", info["default"])
                    set_v(f"#strat_{field}", str(val) if info["type"] != "bool" else val)
            
            # Manually load Risk-located strategy params
            set_v("#strat_ENABLED_SELL", s.get("strat_ENABLED_SELL", True))
            set_v("#strat_BUY_LEVEL", str(s.get("strat_BUY_LEVEL", "30")))
            set_v("#strat_SELL_LEVEL", str(s.get("strat_SELL_LEVEL", "70")))
            
            # Assets
            saved_assets = set(s.get("assets", ["BTCUSDT"]))
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
                    yield Label("── EGGSHELL BACKTESTER v1.0 ──", classes="box-title")
                    with TabbedContent():
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
                                    yield Label("BALANCE ($)")
                                    yield Input("1000", id="balance-input")
                                    yield Label("RISK (%) PER TRADE")
                                    yield Input("20", id="size-input")

                                with Collapsible(title="TIME WINDOW"):
                                    yield Label("START DATE")
                                    with Horizontal(id="date-row"):
                                        yield Input("2023-01-01", id="start-date-input")
                                        yield Button("PICK", id="start-cal-btn")
                                    yield Label("END DATE")
                                    with Horizontal(id="date-row-end"):
                                        yield Input("", id="end-date-input", placeholder="Now")
                                        yield Button("PICK", id="end-cal-btn")

                        with TabPane("STRATEGY"):
                            with VerticalScroll(id="dynamic-strategy-container"):
                                for section_name, section_fields in INDICATOR_SCHEMA.items():
                                    with Collapsible(title=f"{section_name} CONFIGURATION", classes="indicator-collapsible"):
                                        for field_name, field_info in section_fields.items():
                                            with Horizontal(classes="inline-field"):
                                                yield Label(field_info["label"])
                                                if field_info["type"] == "bool":
                                                    yield Switch(field_info["default"], id=f"strat_{field_name}")
                                                else:
                                                    yield Input(str(field_info["default"]), id=f"strat_{field_name}")

                        with TabPane("RISK"):
                            with VerticalScroll():
                                with Horizontal(classes="inline-field"):
                                    yield Label("TOTAL TRADES LIMIT")
                                    yield Input("5", id="max-pos")
                                with Horizontal(classes="inline-field"):
                                    yield Label("ACCUMULATE")
                                    yield Switch(value=False, id="toggle-accumulate")
                                with Horizontal(classes="inline-field"):
                                    yield Label("ENABLE LIMIT")
                                    yield Switch(value=False, id="toggle-max-pos")
                                with Horizontal(classes="inline-field"):
                                    yield Label("ENABLE SELL")
                                    yield Switch(value=True, id="strat_ENABLED_SELL")
                                with Horizontal(classes="inline-field"):
                                    yield Label("BUY CONDITION")
                                    yield Input("30", id="strat_BUY_LEVEL")
                                with Horizontal(classes="inline-field"):
                                    yield Label("SELL CONDITION")
                                    yield Input("70", id="strat_SELL_LEVEL")

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

    @on(Switch.Changed, "#toggle-max-pos")
    def on_max_pos_toggle(self, event: Switch.Changed) -> None:
        self.query_one("#max-pos", Input).disabled = not event.value

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
            max_v = self.query_one("#max-pos", Input).value
            
            adv_params = {}
            for section, fields in INDICATOR_SCHEMA.items():
                for field, info in fields.items():
                    try:
                        val = self.query_one(f"#strat_{field}").value
                        if info["type"] == "bool":
                            adv_params[field] = bool(val)
                        elif info["type"] == "int":
                            adv_params[field] = int(val) if val else info["default"]
                        elif info["type"] == "float":
                            adv_params[field] = float(val) if val else info["default"]
                    except Exception:
                        adv_params[field] = info["default"]
            
            # Manually collect Risk-located strategy params
            try:
                adv_params["ENABLED_SELL"] = self.query_one("#strat_ENABLED_SELL", Switch).value
                val_buy = self.query_one("#strat_BUY_LEVEL", Input).value
                adv_params["BUY_LEVEL"] = float(val_buy) if val_buy else 30.0
                val_sell = self.query_one("#strat_SELL_LEVEL", Input).value
                adv_params["SELL_LEVEL"] = float(val_sell) if val_sell else 70.0
            except Exception: pass
                        
            max_pos_on = self.query_one("#toggle-max-pos", Switch).value
            max_positions = (int(max_v) if max_v else 5) if max_pos_on else 999
            accumulate = self.query_one("#toggle-accumulate", Switch).value
            return {
                "assets": assets, "interval": interval, "balance": balance, "size": size,
                "start_date": start_date, "end_date": end_date, "adv_params": adv_params,
                "max_positions": max_positions, "accumulate": accumulate
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
        if event.button.id == "run-btn":
            self.action_run()
        elif event.button.id == "cancel-btn":
            self.action_cancel()
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

    def _run_backtest(self, assets, interval, balance, size, start_date, end_date, adv_params, max_positions, accumulate) -> None:
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
            for symbol in assets:
                if self.cancelled: return
                symbol_df = binance_df.df[binance_df.df["symbol"] == symbol]
                if not symbol_df.empty:
                    self.app.call_from_thread(lambda s=symbol: self.log_status(f"PROCESSING SIGNALS: {s}"))
                    sl = SignalLogic(symbol_df, **adv_params)
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
            engine = BacktestEngine(unified_signals, initial_balance=balance, position_size_pct=size, max_positions=max_positions, accumulate=accumulate)
            
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
            os.makedirs("reports/errors", exist_ok=True)
            with open("reports/errors/error.log", "a") as f:
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
            k_str = str(k)[:20].upper().ljust(22)
            if isinstance(v, float):
                if "[%]" in k:
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