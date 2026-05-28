"""Popup calendar widget for date-input fields."""
import calendar
from datetime import datetime, date

from textual.app import ComposeResult
from textual.widget import Widget
from textual.containers import Horizontal, Vertical, Grid
from textual.widgets import Button, Label, Input, Static
from textual import on


class CalendarWidget(Static):
    def __init__(self, target_input_id: str, **kwargs):
        super().__init__(**kwargs)
        self.target_input_id = target_input_id
        self.current_year  = datetime.now().year
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
            day      = int(event.button.label.plain)
            selected = date(self.current_year, self.current_month, day)
            self.app.query_one(f"#{self.target_input_id}", Input).value = selected.strftime("%Y-%m-%d")
            self.add_class("hidden")
            event.stop()
