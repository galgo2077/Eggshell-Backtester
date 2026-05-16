from binance_service.dataframe import Dataframe
from core.signal_logic import SignalLogic
from core.backtest_engine import BacktestEngine
from core.constants import DataframeConstantsBinance, STRATEGY_SCHEMAS

import os
import calendar
import webbrowser
from datetime import datetime, date
from textual.app import App, ComposeResult
from textual.screen import ModalScreen
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
import re as _re
import time


class SaveNameModal(ModalScreen):
    CSS = """
    SaveNameModal { align: center middle; }
    SaveNameModal > Vertical {
        width: 64; height: auto;
        background: #111827; border: heavy #00ffff; padding: 2 3;
    }
    SaveNameModal .modal-title {
        color: #00ffff; text-style: bold; text-align: center; width: 100%; margin-bottom: 1;
    }
    SaveNameModal Label { color: #888888; }
    SaveNameModal Input { background: #1e293b; color: #00ff00; height: 3; margin: 1 0 2 0; }
    SaveNameModal .modal-btns { height: 3; }
    SaveNameModal .modal-btns Button { width: 1fr; height: 3; margin: 0; }
    SaveNameModal #modal-save-ok { background: #ff8800; color: #000; text-style: bold; margin-right: 1; }
    SaveNameModal #modal-save-ok:hover { background: #ffaa00; }
    SaveNameModal #modal-save-cancel { background: #550000; }
    SaveNameModal #modal-save-cancel:hover { background: #ff0000; }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("SAVE BACKTEST", classes="modal-title")
            yield Label("NAME THIS SESSION:")
            yield Input(placeholder="e.g. btc_ema_bull_run", id="save-name-input")
            with Horizontal(classes="modal-btns"):
                yield Button("SAVE", id="modal-save-ok")
                yield Button("CANCEL", id="modal-save-cancel")

    def on_mount(self) -> None:
        self.query_one("#save-name-input", Input).focus()

    def on_key(self, event) -> None:
        if event.key == "enter":
            self._confirm()
        elif event.key == "escape":
            self.dismiss(None)

    def _confirm(self) -> None:
        raw = self.query_one("#save-name-input", Input).value.strip()
        name = _re.sub(r"[^\w\-]", "_", raw) if raw else ""
        self.dismiss(name)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "modal-save-ok":
            self._confirm()
        elif event.button.id == "modal-save-cancel":
            self.dismiss(None)


class LoadBacktestModal(ModalScreen):
    CSS = """
    LoadBacktestModal { align: center middle; }
    LoadBacktestModal > Vertical {
        width: 84; height: 28;
        background: #111827; border: heavy #00ffff; padding: 2 3;
    }
    LoadBacktestModal .modal-title {
        color: #00ffff; text-style: bold; text-align: center; width: 100%; margin-bottom: 1;
    }
    LoadBacktestModal Input { background: #1e293b; color: #00ff00; height: 3; margin-bottom: 1; }
    LoadBacktestModal DataTable { height: 1fr; background: #0a0a0a; }
    LoadBacktestModal .modal-btns { height: 3; margin-top: 1; }
    LoadBacktestModal .modal-btns Button { width: 1fr; height: 3; margin: 0; }
    LoadBacktestModal #modal-load-ok { background: #005500; color: #fff; text-style: bold; margin-right: 1; }
    LoadBacktestModal #modal-load-ok:hover { background: #00ff00; color: #000; }
    LoadBacktestModal #modal-load-cancel { background: #550000; }
    LoadBacktestModal #modal-load-cancel:hover { background: #ff0000; }
    """

    def __init__(self, results_dir: str, **kwargs):
        super().__init__(**kwargs)
        self.results_dir = results_dir
        self._selected: str | None = None
        self._all_folders: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("LOAD BACKTEST", classes="modal-title")
            yield Input(placeholder="Search by name...", id="load-search-input")
            yield DataTable(id="load-table", cursor_type="row")
            with Horizontal(classes="modal-btns"):
                yield Button("LOAD", id="modal-load-ok")
                yield Button("CANCEL", id="modal-load-cancel")

    def on_mount(self) -> None:
        table = self.query_one("#load-table", DataTable)
        table.add_columns("NAME", "SAVED ON")
        self._all_folders = self._get_folders()
        self._populate(self._all_folders)
        self.query_one("#load-search-input", Input).focus()

    def _get_folders(self) -> list[str]:
        if not os.path.exists(self.results_dir):
            return []
        entries = []
        for f in os.listdir(self.results_dir):
            full = os.path.join(self.results_dir, f)
            if os.path.isdir(full):
                entries.append((os.path.getmtime(full), f))
        return [f for _, f in sorted(entries, reverse=True)]

    def _populate(self, folders: list[str]) -> None:
        table = self.query_one("#load-table", DataTable)
        table.clear()
        for f in folders:
            parts = f.split("_", 2)
            if len(parts[0]) == 8 and parts[0].isdigit():
                d, t = parts[0], parts[1] if len(parts) > 1 else ""
                date_fmt = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                time_fmt = f"{t[:2]}:{t[2:4]}:{t[4:6]}" if len(t) == 6 else t
                saved_on = f"{date_fmt} {time_fmt}"
                name = parts[2].replace("_", " ") if len(parts) > 2 else "(unnamed)"
            else:
                name = f.replace("_", " ")
                saved_on = ""
            table.add_row(name, saved_on, key=f)

    @on(Input.Changed, "#load-search-input")
    def on_search(self, event: Input.Changed) -> None:
        q = event.value.lower()
        self._populate([f for f in self._all_folders if q in f.lower()])

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key:
            self._selected = str(event.row_key.value)

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)

    def _load(self) -> None:
        if self._selected:
            self.dismiss(self._selected)
        else:
            self.app.notify("SELECT A BACKTEST FIRST.", severity="warning")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "modal-load-ok":
            self._load()
        elif event.button.id == "modal-load-cancel":
            self.dismiss(None)


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
    #save-btn { width: 100%; margin: 2 0 0 0; background: #ff8800; color: #000000; text-style: bold; height: 3; display: none; }
    #save-btn.visible { display: block; }
    #save-btn:hover { background: #ffaa00; }
    #load-btn { width: 100%; margin: 1 0 1 0; background: #1e3a5f; color: #00ccff; text-style: bold; height: 3; }
    #load-btn:hover { background: #00ccff; color: #000000; }
    #asset-chart-select { width: 100%; margin: 1 0; display: none; }
    #asset-chart-select.visible { display: block; }
    
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

    #tab-pie { padding: 0 1; }
    #assets-pie { width: 100%; height: auto; }
    #alloc-section { display: none; margin-top: 1; }
    #alloc-section.visible { display: block; }
    .alloc-label { width: 10; color: #888888; }
    .alloc-input { width: 8; }
    #alloc-total { text-align: right; margin-top: 1; text-style: bold; color: #00ff00; }
    #alloc-total.invalid { color: #ff0000; }

    #dual-strategy-panel { margin-top: 1; border-top: solid #333333; padding-top: 1; height: auto; }
    #dual-strategy-panel Label { margin-top: 1; color: #888888; }
    #dual-slot-btn-a, #dual-slot-btn-b { width: 1fr; }
    #dual-slot-btn-a.active-slot, #dual-slot-btn-b.active-slot { background: #00ffff; color: #000000; text-style: bold; }

    /* Portfolio managed backtest */
    .portfolio-badge {
        background: #0a2a0a;
        color: #00ff00;
        text-style: bold;
        text-align: center;
        border: solid #00ff00;
        margin: 1 0;
        padding: 0 1;
        height: 2;
    }
    #allocation-container { max-height: 14; border: solid #1a1a1a; }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "QUIT"),
        Binding("ctrl+c", "quit", "QUIT"),
        Binding("r", "run", "RUN SEQUENCE"),
        Binding("d", "toggle_dark", "DARK MODE"),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.sort_states = {}
        self._active_settings = {}
        self._loading_settings = False
        self._dual_active_slot = "a"

    def rebuild_strategy_and_risk_tabs(self, strategy_name: str) -> None:
        schema = STRATEGY_SCHEMAS.get(strategy_name, STRATEGY_SCHEMAS["EMA_CROSS"])

        # 1. Rebuild Strategy Tab
        try:
            strat_container = self.query_one("#dynamic-strategy-container", VerticalScroll)
            strat_container.remove_children()

            if strategy_name == "DUAL_STRATEGY":
                saved = getattr(self, "_active_settings", {})
                try:
                    a_name = self.query_one("#opt_dual_strategy_strategy_a", Select).value or "EMA_CROSS"
                except Exception:
                    a_name = "EMA_CROSS"
                try:
                    b_name = self.query_one("#opt_dual_strategy_strategy_b", Select).value or "ELLIOT_BOLLINGER"
                except Exception:
                    b_name = "ELLIOT_BOLLINGER"

                slot = getattr(self, "_dual_active_slot", "a")
                name = a_name if slot == "a" else b_name

                btn_a = Button("◀ STRATEGY A", id="dual-slot-btn-a")
                btn_b = Button("STRATEGY B ▶", id="dual-slot-btn-b")
                if slot == "a":
                    btn_a.add_class("active-slot")
                else:
                    btn_b.add_class("active-slot")
                strat_container.mount(Horizontal(btn_a, btn_b, classes="sel-btn-row"))

                slot_schema = STRATEGY_SCHEMAS.get(name, {})
                for section_name, fields in slot_schema.items():
                    slot_widgets = []
                    for field_name, field_info in fields.items():
                        if field_name == "ENABLED_SELL": continue
                        w_id = f"opt_dual_{slot}_{field_name}".lower()
                        val = saved.get(w_id, field_info["default"])
                        slot_widgets.append(Label(field_info["label"]))
                        if field_info["type"] == "bool":
                            slot_widgets.append(Switch(value=bool(val), id=w_id))
                        else:
                            slot_widgets.append(Input(str(val), id=w_id))
                    if slot_widgets:
                        title = f"STRATEGY {slot.upper()} — {name.replace('_', ' ')} — {section_name}"
                        strat_container.mount(
                            Collapsible(*slot_widgets, title=title, classes="indicator-collapsible")
                        )
                return

            saved = getattr(self, "_active_settings", {})
            for section_name, fields in schema.items():
                if section_name == "RISK": continue
                widgets = []
                for field_name, field_info in fields.items():
                    w_id = f"opt_{strategy_name}_{field_name}".lower()
                    val = saved.get(w_id, field_info["default"])
                    widgets.append(Label(field_info["label"]))
                    if field_info["type"] == "bool":
                        widgets.append(Switch(value=bool(val), id=w_id))
                    else:
                        widgets.append(Input(str(val), id=w_id))
                if widgets:
                    strat_container.mount(
                        Collapsible(*widgets, title=f"{section_name} CONFIGURATION", classes="indicator-collapsible")
                    )

            # RISK fields (excluding ENABLED_SELL) → collapsible in STRATEGY tab
            risk_extra = {k: v for k, v in schema.get("RISK", {}).items() if k != "ENABLED_SELL"}
            if risk_extra:
                risk_widgets = []
                for field_name, field_info in risk_extra.items():
                    w_id = f"opt_{strategy_name}_{field_name}".lower()
                    val = saved.get(w_id, field_info["default"])
                    risk_widgets.append(Label(field_info["label"]))
                    if field_info["type"] == "bool":
                        risk_widgets.append(Switch(value=bool(val), id=w_id))
                    else:
                        risk_widgets.append(Input(str(val), id=w_id))
                strat_container.mount(
                    Collapsible(*risk_widgets, title="RISK CONFIGURATION", classes="indicator-collapsible")
                )
        except Exception:
            pass

        # 2. ENABLED_SELL only → RISK tab dynamic container
        try:
            risk_container = self.query_one("#dynamic-risk-container", Vertical)
            risk_container.remove_children()
            if strategy_name != "DUAL_STRATEGY":
                enabled_sell_info = schema.get("RISK", {}).get("ENABLED_SELL")
                if enabled_sell_info:
                    saved = getattr(self, "_active_settings", {})
                    w_id = f"opt_{strategy_name}_enabled_sell"
                    val = saved.get(w_id, enabled_sell_info["default"])
                    risk_container.mount(
                        Horizontal(
                            Label(enabled_sell_info["label"]),
                            Switch(value=bool(val), id=w_id),
                            classes="inline-field"
                        )
                    )
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

    @on(Button.Pressed, "#dual-slot-btn-a")
    def on_dual_slot_a(self) -> None:
        self._dual_active_slot = "a"
        self.rebuild_strategy_and_risk_tabs("DUAL_STRATEGY")

    @on(Button.Pressed, "#dual-slot-btn-b")
    def on_dual_slot_b(self) -> None:
        self._dual_active_slot = "b"
        self.rebuild_strategy_and_risk_tabs("DUAL_STRATEGY")

    @on(Select.Changed, "#opt_dual_strategy_strategy_a")
    def on_dual_a_changed(self, event: Select.Changed) -> None:
        if not event.value:
            return
        try:
            if self.query_one("#strategy-select", Select).value != "DUAL_STRATEGY":
                return
        except Exception:
            return
        self._save_ui_settings()
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
        self._save_ui_settings()
        self.rebuild_strategy_and_risk_tabs("DUAL_STRATEGY")

    @on(Select.Changed, "#strategy-select")
    def on_strategy_changed(self, event: Select.Changed) -> None:
        if event.value:
            self._save_ui_settings()
            self.rebuild_strategy_and_risk_tabs(event.value)
            try:
                dual_panel = self.query_one("#dual-strategy-panel")
                if event.value == "DUAL_STRATEGY":
                    dual_panel.remove_class("hidden")
                else:
                    dual_panel.add_class("hidden")
            except Exception:
                pass

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
            try:
                dual_panel = self.query_one("#dual-strategy-panel")
                if strat_to_load == "DUAL_STRATEGY":
                    dual_panel.remove_class("hidden")
                else:
                    dual_panel.add_class("hidden")
            except Exception:
                pass

            # 3. Automatically restore checkboxes
            self._loading_settings = True
            saved_assets = set(loaded.get("assets", ["BTCUSDT"]))
            for cb in self.query("#asset-checkbox-container Checkbox"):
                cb.value = str(cb.label) in saved_assets
            self._loading_settings = False
            # 4. Rebuild allocation with saved values (must happen after checkboxes restored)
            self._rebuild_allocation_inputs(reset=False)
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
                    with TabbedContent(id="config-tabs"):
                        with TabPane("STRATEGY SELECT"):
                            with VerticalScroll():
                                yield Label("CHOOSE ACTIVE STRATEGY", classes="box-subtitle")
                                yield Select(
                                    [(k.replace("_", " ").title(), k) for k in STRATEGY_SCHEMAS.keys()],
                                    value=list(STRATEGY_SCHEMAS.keys())[0] if STRATEGY_SCHEMAS else None,
                                    id="strategy-select",
                                )
                                _sub = [(k.replace("_", " ").title(), k) for k in STRATEGY_SCHEMAS.keys() if k != "DUAL_STRATEGY"]
                                _sub_b_default = _sub[1][1] if len(_sub) > 1 else _sub[0][1]
                                with Vertical(id="dual-strategy-panel", classes="hidden"):
                                    yield Label("SIGNAL CONDITION")
                                    yield Select(
                                        [("AND  — Both signals required", "AND"), ("OR  — Either signal triggers", "OR")],
                                        value="AND", id="opt_dual_strategy_condition",
                                    )
                                    yield Label("STRATEGY A")
                                    yield Select(_sub, value="EMA_CROSS", id="opt_dual_strategy_strategy_a")
                                    yield Label("STRATEGY B")
                                    yield Select(_sub, value=_sub_b_default, id="opt_dual_strategy_strategy_b")
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

                        with TabPane("RISK", id="tab-risk-pane"):
                            with VerticalScroll():
                                yield Static("", id="portfolio-mode-badge", classes="hidden portfolio-badge")
                                with Horizontal(classes="date-header-row"):
                                    yield Label("BUDGET PER TRADE (%) ")
                                    yield Label("●", id="size-status", classes="date-status-ok")
                                yield Input("20", id="size-input")
                                with Vertical(id="alloc-section"):
                                    yield Static("── PORTFOLIO ALLOCATION ──", classes="section-header")
                                    yield VerticalScroll(id="allocation-container")
                                    yield Label("TOTAL: 0.0%", id="alloc-total")
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
                            yield Button("LOAD BACKTEST", id="load-btn")
                            yield Select([], id="asset-chart-select", prompt="SELECT ASSET")
                            yield Button("FULL PORTFOLIO CHART", id="open-chart-main", variant="success", classes="chart-btn")
                            yield Button("TOP DRAWDOWNS CHART", id="open-chart-drawdowns", variant="error", classes="chart-btn")
                            yield Button("CUMULATIVE RETURNS", id="open-chart-returns", variant="success", classes="chart-btn")
                            yield Button("CASH FLOW BALANCE", id="open-chart-cash", variant="primary", classes="chart-btn")
                            yield Button("PORTFOLIO VALUE", id="open-chart-value", variant="default", classes="chart-btn")
                            yield Button("UNDERWATER CHART (DEEP DIVE)", id="open-chart-underwater", variant="warning", classes="chart-btn")
                            yield Button("ASSET TRADES CHART", id="open-chart-asset-trades", variant="primary", classes="chart-btn")
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
                    with TabPane("PIE", id="tab-pie"):
                        with VerticalScroll():
                            yield Static("", id="assets-pie")
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
        if w_id.startswith("alloc-"):
            self._update_alloc_total()
            return
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
                    elif info["type"] == "str":
                        adv_params[field] = str(val) if val and val is not Select.BLANK else info["default"]
                except Exception:
                    if hasattr(self, "_active_settings") and w_id in self._active_settings:
                        adv_params[field] = self._active_settings[w_id]
                    else:
                        adv_params[field] = info["default"]

            if strategy_name == "DUAL_STRATEGY":
                a_name = adv_params.get("STRATEGY_A", "EMA_CROSS")
                b_name = adv_params.get("STRATEGY_B", "ELLIOT_BOLLINGER")
                adv_params["PARAMS_A"] = self._collect_dual_slot_params("a", a_name)
                adv_params["PARAMS_B"] = self._collect_dual_slot_params("b", b_name)

            # Per-symbol allocation
            per_symbol_alloc = None
            if len(assets) >= 2:
                per_symbol_alloc = {}
                for asset in assets:
                    try:
                        per_symbol_alloc[asset] = float(self.query_one(f"#alloc-{asset}", Input).value)
                    except Exception:
                        per_symbol_alloc[asset] = round(100.0 / len(assets), 2)
                total_alloc = sum(per_symbol_alloc.values())
                if abs(total_alloc - 100.0) > 0.5:
                    return None, f"ALLOCATION MUST SUM TO 100% (CURRENTLY {total_alloc:.1f}%)"

            return {
                "assets": assets, "interval": interval, "balance": balance, "size": size,
                "start_date": start_date, "end_date": end_date, "adv_params": adv_params,
                "cooldown": cooldown, "accumulate": True,
                "per_symbol_alloc": per_symbol_alloc,
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

    def _draw_pie_chart(self) -> str:
        import math
        results   = getattr(self, "_last_results", None)
        COLORS    = ['#818cf8','#34d399','#fb7185','#fbbf24','#22d3ee','#a78bfa','#f97316','#84cc16']

        # Collect live-selected assets for pre-run preview
        try:
            live_assets = [str(cb.label) for cb in self.query("#asset-checkbox-container Checkbox") if cb.value]
        except Exception:
            live_assets = []

        if not results:
            if len(live_assets) < 2:
                return "\n[dim #555555]  Run a backtest to see the asset pie.[/dim #555555]"
            # Pre-run preview — show allocation only
            symbols   = sorted(live_assets)
            sym_stats = {}
        else:
            sym_stats = results.get("symbol_stats", {})
            symbols   = sorted(sym_stats.keys())
            if not symbols:
                return "\n[dim #555555]  No trades recorded.[/dim #555555]"

        alloc: dict[str, float] = {}
        for sym in symbols:
            try:
                alloc[sym] = float(self.query_one(f"#alloc-{sym}", Input).value)
            except Exception:
                alloc[sym] = 100.0 / len(symbols)
        total_a = sum(alloc.values()) or 1.0

        bounds = [0.0]
        for sym in symbols:
            bounds.append(bounds[-1] + (alloc[sym] / total_a) * 2 * math.pi)

        # ── Braille dot pie ───────────────────────────────────────────────────
        # Each braille char = 2 dot-cols × 4 dot-rows.
        # Chars are ~2× taller than wide → dot aspect is square.
        # W chars × H chars  →  DW=W*2 dot-cols × DH=H*4 dot-rows.
        # W=36, H=18 → visual box ≈ 36 char-widths × 36 char-widths = square.
        W, H     = 36, 18
        DW, DH   = W * 2, H * 4
        cx, cy   = (DW - 1) / 2.0, (DH - 1) / 2.0
        r        = min(DW, DH) / 2.0 - 1.5   # dot-space radius (dots are square)

        # Braille bit layout:  col 0 rows 0-2 → bits 0-2; col 0 row 3 → bit 6
        #                      col 1 rows 0-2 → bits 3-5; col 1 row 3 → bit 7
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
                    parts.append(' ')
                else:
                    dom     = max(votes, key=votes.get)
                    col_str = COLORS[dom % len(COLORS)]
                    parts.append(f"[{col_str}]{chr(0x2800 + bits)}[/{col_str}]")
            rows.append("".join(parts))

        # ── Stats table ───────────────────────────────────────────────────────
        sep = "[#1f2937]" + "─" * 52 + "[/#1f2937]"
        is_preview = not bool(sym_stats)
        header_label = "── PORTFOLIO PREVIEW ──" if is_preview else "── ASSET ALLOCATION PIE ──"

        tbl = [
            "",
            f"[bold #00ffff]  {'SYM':<7} {'ALLOC':>6}  {'BUD%/T':>6}  {'P&L%':>8}  {'WIN%':>6}  {'TRADES':>6}[/bold #00ffff]",
            sep,
        ]
        for i, sym in enumerate(symbols):
            s       = sym_stats.get(sym, {})
            col_str = COLORS[i % len(COLORS)]
            a       = alloc.get(sym, 100.0 / len(symbols))
            try:
                bud = float(self.query_one(f"#budget-{sym}", Input).value)
                bud_str = f"{bud:.0f}%"
            except Exception:
                try:
                    bud_str = self.query_one("#size-input", Input).value + "%"
                except Exception:
                    bud_str = "-"
            pnl     = s.get("total_pct", 0.0)
            t       = s.get("trades", 0)
            wr      = s.get("wins", 0) / t * 100 if t else 0.0
            pc      = "green" if pnl >= 0 else ("dim" if is_preview else "red")
            short   = sym.replace("USDT", "")
            pnl_col = f"[dim #555555]{'--':>7}[/dim #555555]" if is_preview else f"[{pc}]{pnl:+7.2f}%[/{pc}]"
            wr_col  = f"[dim #555555]{'--':>5}[/dim #555555]"  if is_preview else f"[cyan]{wr:5.1f}%[/cyan]"
            t_col   = f"[dim #555555]{'--':>5}[/dim #555555]"  if is_preview else f"[white]{t:5d}[/white]"
            tbl.append(
                f"  [{col_str}]⣿[/{col_str}] [white]{short:<7}[/white]"
                f" [yellow]{a:5.1f}%[/yellow]"
                f"  [magenta]{bud_str:>5}[/magenta]"
                f"  {pnl_col}"
                f"  {wr_col}"
                f"  {t_col}"
            )
        tbl.append(sep)
        if is_preview:
            tbl.append("[dim #555555]  Run backtest to populate P&L stats.[/dim #555555]")

        header = f"\n[bold #00ffff]  {header_label}[/bold #00ffff]\n"
        return header + "\n".join(rows) + "\n" + "\n".join(tbl)

    def _apply_asset_filter(self, value) -> None:
        is_all = (value is Select.BLANK or value == "__ALL__")
        charts = getattr(self, "charts", {})
        portfolio_btns = [
            "open-chart-main", "open-chart-drawdowns", "open-chart-returns",
            "open-chart-cash", "open-chart-value", "open-chart-underwater",
        ]

        # Portfolio charts: visible only when ALL is selected
        for btn_id in portfolio_btns:
            try:
                btn = self.query_one(f"#{btn_id}", Button)
                key = btn_id.replace("open-chart-", "")
                if is_all and charts and key in charts and os.path.exists(charts.get(key, "")):
                    btn.add_class("visible")
                else:
                    btn.remove_class("visible")
            except Exception:
                pass

        # Asset trades chart: always visible once charts exist, but disabled when ALL
        try:
            btn = self.query_one("#open-chart-asset-trades", Button)
            if charts and "trades" in charts and os.path.exists(charts.get("trades", "")):
                btn.add_class("visible")
                btn.disabled = is_all
            else:
                btn.remove_class("visible")
        except Exception:
            pass

    @on(Select.Changed, "#asset-chart-select")
    def on_asset_filter_changed(self, event: Select.Changed) -> None:
        self._apply_asset_filter(event.value)

    def _rebuild_allocation_inputs(self, reset: bool = True) -> None:
        try:
            assets        = [str(cb.label) for cb in self.query("#asset-checkbox-container Checkbox") if cb.value]
            container     = self.query_one("#allocation-container", VerticalScroll)
            alloc_section = self.query_one("#alloc-section")
            badge         = self.query_one("#portfolio-mode-badge", Static)
            container.remove_children()

            if len(assets) < 2:
                alloc_section.remove_class("visible")
                badge.add_class("hidden")
                return

            alloc_section.add_class("visible")
            badge.remove_class("hidden")
            badge.update(f"⬡  PORTFOLIO MODE — {len(assets)} ASSETS")

            n = len(assets)
            base_pct = round(100.0 / n, 2)
            pcts = [base_pct] * (n - 1) + [round(100.0 - base_pct * (n - 1), 2)]
            for asset, default_pct in zip(assets, pcts):
                val = str(default_pct) if reset else str(self._active_settings.get(f"alloc-{asset}", default_pct))
                container.mount(Horizontal(
                    Label(asset.replace("USDT", ""), classes="alloc-label"),
                    Input(val, id=f"alloc-{asset}", classes="alloc-input"),
                    Label("%"),
                    classes="inline-field",
                ))
            self._update_alloc_total()
        except Exception:
            pass

    def _update_alloc_total(self) -> None:
        try:
            assets = [str(cb.label) for cb in self.query("#asset-checkbox-container Checkbox") if cb.value]
            total = 0.0
            for asset in assets:
                try:
                    total += float(self.query_one(f"#alloc-{asset}", Input).value)
                except Exception:
                    pass
            lbl = self.query_one("#alloc-total", Label)
            lbl.update(f"TOTAL: {total:.1f}%")
            if abs(total - 100.0) < 0.1:
                lbl.remove_class("invalid")
            else:
                lbl.add_class("invalid")
        except Exception:
            pass

    def _refresh_pie_live(self) -> None:
        try:
            markup = self._draw_pie_chart()
            self._pie_markup = markup
            tc = self.query_one("#results-tabs", TabbedContent)
            if getattr(tc, "active", None) == "tab-pie":
                self.query_one("#assets-pie", Static).update(markup)
        except Exception:
            pass

    @on(Input.Changed, ".alloc-input")
    def on_alloc_input_changed(self, event: Input.Changed) -> None:
        self._update_alloc_total()
        self._refresh_pie_live()

    @on(TabbedContent.TabActivated, "#config-tabs")
    def on_config_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if getattr(event.pane, "id", None) == "tab-risk-pane":
            self._rebuild_allocation_inputs(reset=False)
            # Switch right panel to PIE for live portfolio preview
            try:
                self.query_one("#results-tabs", TabbedContent).active = "tab-pie"
            except Exception:
                pass

    @on(Checkbox.Changed, ".asset-checkbox")
    def on_asset_toggled(self, event: Checkbox.Changed) -> None:
        if not self._loading_settings:
            self._rebuild_allocation_inputs(reset=True)
            self._refresh_pie_live()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel-btn":
            self.action_cancel()
        elif event.button.id == "save-btn":
            def _after_name(name: str | None) -> None:
                if name is not None:
                    self._save_backtest(name)
            self.push_screen(SaveNameModal(), _after_name)
        elif event.button.id == "load-btn":
            proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            results_dir = os.path.join(proj_root, "reports", "results")
            def _after_load(folder: str | None) -> None:
                if folder:
                    self._load_backtest(folder)
            self.push_screen(LoadBacktestModal(results_dir), _after_load)
        elif event.button.id == "open-chart-asset-trades":
            symbol = self.query_one("#asset-chart-select", Select).value
            charts = getattr(self, "charts", {})
            trades_path = charts.get("trades", "")
            if trades_path and os.path.exists(trades_path):
                if symbol and symbol not in (Select.BLANK, "__ALL__"):
                    webbrowser.open(f"file://{trades_path}#{symbol}")
                else:
                    webbrowser.open(f"file://{trades_path}")
            else:
                self.notify("TRADES CHART NOT GENERATED.", severity="warning")
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

    def _save_backtest(self, name: str = "") -> None:
        import shutil, csv
        results = getattr(self, "_last_results", None)
        trades  = getattr(self, "_last_trades", [])
        if not results:
            self.notify("NO BACKTEST TO SAVE.", severity="warning")
            return

        proj_root   = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        timestamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name   = name if name else timestamp
        results_dir = os.path.join(proj_root, "reports", "results")
        candidate   = os.path.join(results_dir, base_name)
        # Avoid overwriting: append timestamp if folder already exists
        if os.path.exists(candidate):
            base_name = f"{base_name}_{timestamp}"
            candidate = os.path.join(results_dir, base_name)
        save_dir = candidate
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

        # ── 5. results.json (for full reload) ────────────────────────────────
        import json as _json
        def _ser(obj):
            if isinstance(obj, dict):  return {k: _ser(v) for k, v in obj.items()}
            if isinstance(obj, list):  return [_ser(v) for v in obj]
            if hasattr(obj, 'isoformat'): return str(obj)
            if isinstance(obj, float) and obj != obj: return None  # NaN
            return obj
        snap = {k: v for k, v in results.items()
                if k not in ('equity_history','returns_history','drawdown_history',
                             'price_history','timestamp_history')}
        snap['charts'] = saved_charts
        with open(os.path.join(save_dir, "results.json"), "w") as f:
            _json.dump(_ser(snap), f)

        self.notify(f"SAVED → reports/results/{base_name}", severity="information")
        self.log_status(f"BACKTEST SAVED: {save_dir}", "success")

    def _load_backtest(self, folder_name: str) -> None:
        import json as _json
        proj_root  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        save_dir   = os.path.join(proj_root, "reports", "results", folder_name)
        charts_dir = os.path.join(save_dir, "charts")

        if not os.path.exists(save_dir):
            self.notify("BACKTEST FOLDER NOT FOUND.", severity="error")
            return

        # ── Load results.json ─────────────────────────────────────────────────
        results_path = os.path.join(save_dir, "results.json")
        results: dict = {}
        if os.path.exists(results_path):
            try:
                with open(results_path) as f:
                    results = _json.load(f)
            except Exception:
                pass

        # Fall back to chart files if results.json missing (old saves)
        if not results.get("charts"):
            chart_files = {
                "main":       "vectorbt_report.html",
                "trades":     "vectorbt_trades.html",
                "underwater": "vectorbt_underwater.html",
                "value":      "vectorbt_value.html",
                "drawdowns":  "vectorbt_drawdowns.html",
                "returns":    "vectorbt_returns.html",
                "cash":       "vectorbt_cash.html",
            }
            results["charts"] = {
                k: os.path.join(charts_dir, v)
                for k, v in chart_files.items()
                if os.path.exists(os.path.join(charts_dir, v))
            }

        # Ensure all stat keys exist (default 0 for old saves without results.json)
        for key in ("total_return_pct","win_rate","total_trades","net_profit","final_balance",
                    "max_drawdown_pct","avg_hold_hours","sharpe_ratio","sortino_ratio",
                    "calmar_ratio","profit_factor","best_trade","worst_trade",
                    "avg_trade_pct","avg_win_pct","avg_loss_pct","buy_hold_pct"):
            results.setdefault(key, 0.0)
        results.setdefault("symbol_stats", {})
        results.setdefault("full_stats", {})

        # ── Load trades.csv ───────────────────────────────────────────────────
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
                        "account_profit_pct": float(row.get("account_profit_pct", 0)),
                        "profit_usd":         float(row["profit_usd"]),
                        "investment":         float(row["investment"]),
                        "quantity":           float(row["quantity"]),
                        "reason":             "Buy Sig -> Sell Sig",
                    })
            except Exception:
                pass

        # ── Rebuild symbol_stats from trades if missing ───────────────────────
        if not results["symbol_stats"] and trades:
            for t in trades:
                s = results["symbol_stats"].setdefault(t["symbol"], {"trades": 0, "wins": 0, "total_pct": 0.0})
                s["trades"] += 1
                if t["profit_pct"] > 0:
                    s["wins"] += 1
                s["total_pct"] += t["profit_pct"]

        # ── Push everything into the UI via _update_results ───────────────────
        self._update_results(results, trades)
        self.log_status(f"[bold cyan]── LOADED: {folder_name} ──[/bold cyan]", "info")
        self.notify(f"LOADED: {folder_name}", severity="information")

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

    def _run_backtest(self, assets, interval, balance, size, start_date, end_date, adv_params, cooldown, accumulate, per_symbol_alloc=None) -> None:
        # ── UI helpers (run on main thread, release GIL so asyncio can render) ─
        def _prog(v: float):
            self.app.call_from_thread(
                lambda _v=v: self.query_one("#main-progress", ProgressBar).update(progress=_v)
            )

        def _status(msg: str):
            self.app.call_from_thread(
                lambda m=msg: self.query_one("#status-label", Label).update(m)
            )

        def _log(msg: str, level: str = "info", pause: float = 0.04):
            """Write to log + update status bar, then sleep so Textual renders it."""
            self.app.call_from_thread(lambda m=msg, l=level: self.log_status(m, l))
            self.app.call_from_thread(lambda m=msg: self.query_one("#status-label", Label).update(m))
            time.sleep(pause)   # release GIL → asyncio loop cycles → widget renders

        try:
            # ── Step 1: Data Download  (10 → 40%) ─────────────────────────────
            _prog(10)
            _log(f"FETCHING DATA: {len(assets)} ASSET(S) @ {interval} | {start_date} → {end_date or 'NOW'}", pause=0.05)
            if self.cancelled: return

            def on_data_progress(pct: float, msg: str = None):
                if self.cancelled: return
                _prog(10 + pct * 30)
                if msg:
                    _log(msg, pause=0.04)   # sleep here too — called from pool thread

            binance_df = Dataframe(
                actives=assets, interval=interval,
                start_date=start_date, end_date=end_date,
                on_progress=on_data_progress,
            )

            total_candles = len(binance_df.df)
            _prog(40)
            _log(f"DATA READY: {total_candles:,} CANDLES ACROSS {len(assets)} ASSET(S)", "success", pause=0.06)
            if self.cancelled: return

            # ── Step 2: Signal Calculation  (40 → 70%) ────────────────────────
            _log("COMPUTING TECHNICAL INDICATORS...", pause=0.04)

            all_signals = []
            num_assets  = max(len(assets), 1)

            for asset_idx, symbol in enumerate(assets):
                if self.cancelled: return
                symbol_df = binance_df.df[binance_df.df["symbol"] == symbol]
                if symbol_df.empty:
                    _log(f"NO DATA FOR {symbol} — SKIPPED", "warning", pause=0.04)
                    continue

                base_pct = 40 + (asset_idx / num_assets) * 30
                _prog(base_pct)
                _log(f"SIGNALS [{asset_idx + 1}/{num_assets}]: {symbol}  ({len(symbol_df):,} candles)", pause=0.04)

                def on_sub_progress(pct: float, msg: str = None, _idx=asset_idx):
                    if self.cancelled: return
                    _prog(40 + (_idx / num_assets) * 30 + (30.0 / num_assets) * pct)
                    if msg:
                        _log(msg, pause=0.03)

                sl = SignalLogic(symbol_df, on_progress=on_sub_progress, **adv_params)
                all_signals.append(sl.df)

            if not all_signals:
                _log("NO MARKET DATA TO PROCESS", "error", pause=0.04)
                self.app.call_from_thread(lambda: self.notify("NO DATA FOUND.", severity="error"))
                return

            unified_signals = pd.concat(all_signals)
            _prog(70)
            _log("ALL SIGNALS COMPUTED — STARTING ENGINE...", "success", pause=0.06)
            if self.cancelled: return

            # ── Step 3: Engine Simulation  (70 → 100%) ────────────────────────
            _log("INITIALIZING VECTORBT PORTFOLIO ENGINE...", pause=0.04)

            engine = BacktestEngine(
                unified_signals, initial_balance=balance, position_size_pct=size,
                cooldown=cooldown, accumulate=accumulate, per_symbol_alloc=per_symbol_alloc,
            )

            def on_engine_progress(pct: float, msg: str = None):
                if self.cancelled: return
                _prog(70 + pct * 30)
                if msg:
                    _log(msg, pause=0.04)

            results = engine.run(on_progress=on_engine_progress)
            if self.cancelled: return

            _prog(100)
            _log(f"SIMULATION COMPLETE — {len(engine.trades)} TRADES EXECUTED", "success", pause=0.06)
            self.app.call_from_thread(
                lambda: self.query_one("#status-label", Label).update("[bold green]BACKTEST COMPLETE[/bold green]")
            )
            self.app.call_from_thread(self._update_results, results, engine.trades)

        except Exception as e:
            import traceback
            import os
            self.app.call_from_thread(lambda: self.log_status(f"CRITICAL ERROR: {e}", "error"))
            proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
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


        self.charts = results.get("charts", {})

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

        symbols = sorted(set(t["symbol"] for t in trades))
        asset_select = self.query_one("#asset-chart-select", Select)
        options = [("ALL ASSETS", "__ALL__")] + [(s, s) for s in symbols]
        asset_select.set_options(options)
        asset_select.value = "__ALL__"
        asset_select.add_class("visible")
        self._apply_asset_filter("__ALL__")

        # Store for deferred render — PIE tab content is lazy-mounted by Textual
        self._pie_markup = self._draw_pie_chart()

        self.notify("PORTFOLIO SEQUENCE COMPLETE.", severity="information")
        self.query_one("#results-tabs", TabbedContent).active = "tab-stats"

    @on(TabbedContent.TabActivated, "#results-tabs")
    def on_results_tab_activated(self, event: TabbedContent.TabActivated) -> None:
        if getattr(event.pane, "id", None) == "tab-pie":
            markup = self._draw_pie_chart()
            self._pie_markup = markup
            try:
                self.query_one("#assets-pie", Static).update(
                    markup or "[dim #555555]  Select 2+ assets to preview allocation.[/dim #555555]"
                )
            except Exception:
                pass

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