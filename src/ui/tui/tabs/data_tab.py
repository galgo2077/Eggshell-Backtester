"""
DATA tab — left config panel.
Handles data source selection (REAL / RANDOM_WALK / MONTE_CARLO),
asset checkboxes, date inputs, balance input, and all local validations.
Cross-tab concerns (allocation rebuild, pie refresh) are delegated to the composer.

Scroll architecture:
  DataTab owns one permanent DataTabScroll, backed by DataTabScrollManager.
  _DataContent uses VerticalGroup (height: auto), so the single scroll container
  measures real content height and keeps one authoritative offset / scrollbar.
"""
from datetime import datetime

from textual import events, on
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import (
    TabPane, Label, Select, Input, Button, Checkbox, Collapsible, Switch, Static,
)
from textual.containers import Horizontal, VerticalGroup, VerticalScroll

from core.constants import DataframeConstantsBinance
from ..utils.helpers import _tip


class DataTabScrollManager:
    """Single source of truth for the DATA tab's scroll state and bounds."""

    WHEEL_STEP = 3

    def __init__(self) -> None:
        self.scroll: DataTabScroll | None = None
        self.offset = 0
        self.viewport_height = 0
        self.content_height = 0
        self.max_offset = 0

    def bind(self, scroll: "DataTabScroll") -> None:
        self.scroll = scroll
        scroll.can_focus = True
        scroll.styles.height = "1fr"
        scroll.styles.overflow_y = "scroll"
        scroll.styles.overflow_x = "hidden"
        scroll.show_vertical_scrollbar = True
        scroll.show_horizontal_scrollbar = False
        self.refresh_bounds()

    def refresh_bounds(self) -> None:
        if self.scroll is None:
            return

        self.viewport_height = max(0, int(self.scroll.container_size.height))
        self.content_height = max(0, int(self.scroll.virtual_size.height))
        self.max_offset = max(0, int(self.scroll.max_scroll_y))
        self.offset = min(max(0, int(self.scroll.scroll_y)), self.max_offset)

        if int(self.scroll.scroll_y) != self.offset:
            self.scroll.scroll_to(y=self.offset, animate=False, force=True, immediate=True)

    def restore_offset(self) -> None:
        if self.scroll is None:
            return

        self.refresh_bounds()
        self.scroll.scroll_to(y=self.offset, animate=False, force=True, immediate=True)

    def refresh_layout(self) -> None:
        if self.scroll is None:
            return

        self.scroll.refresh(layout=True)
        self.restore_offset()

    def sync_offset(self) -> None:
        if self.scroll is None:
            return
        self.offset = min(max(0, int(self.scroll.scroll_y)), max(0, int(self.scroll.max_scroll_y)))

    def scroll_by(self, rows: int) -> None:
        if self.scroll is None:
            return

        self.refresh_bounds()
        target = min(max(0, self.offset + rows), self.max_offset)
        self.offset = target
        self.scroll.scroll_to(y=target, animate=False, force=True, immediate=True)

    def scroll_home(self) -> None:
        self.scroll_by(-self.max_offset)

    def scroll_end(self) -> None:
        self.refresh_bounds()
        self.scroll_by(self.max_offset - self.offset)

    def page_size(self) -> int:
        self.refresh_bounds()
        return max(1, self.viewport_height - 2)

    def handle_key(self, event: events.Key) -> bool:
        keys = {
            "up": -1,
            "down": 1,
            "pageup": -self.page_size(),
            "pagedown": self.page_size(),
        }
        if event.key in keys:
            self.scroll_by(keys[event.key])
            return True
        if event.key == "home":
            self.scroll_home()
            return True
        if event.key == "end":
            self.scroll_end()
            return True
        return False

    def handle_wheel(self, direction: int) -> None:
        self.scroll_by(direction * self.WHEEL_STEP)


class DataTabScroll(VerticalScroll):
    """Permanent DATA tab scroll container; all scroll events flow through manager."""

    def __init__(self, manager: DataTabScrollManager, **kwargs):
        super().__init__(**kwargs)
        self.manager = manager

    def on_mount(self) -> None:
        self.manager.bind(self)

    def on_resize(self, event: events.Resize) -> None:
        self.manager.refresh_layout()

    def watch_scroll_y(self, old_value: float, new_value: float) -> None:
        super().watch_scroll_y(old_value, new_value)
        self.manager.sync_offset()

    async def _on_key(self, event: events.Key) -> None:
        if self.manager.handle_key(event):
            event.stop()
            event.prevent_default()
            return
        await super()._on_key(event)

    def _on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        self.manager.handle_wheel(-1)
        event.stop()

    def _on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        self.manager.handle_wheel(1)
        event.stop()


class _DataContent(VerticalGroup):
    """
    Inner content for the DATA tab.
    VerticalGroup has height: auto so content height determines total size,
    allowing the parent VerticalScroll to detect overflow and show a thumb.
    """

    def compose(self) -> ComposeResult:
        # ── Data source selector ──────────────────────────────────────────────
        with Horizontal(classes="label-row"):
            yield Label("DATA SOURCE MODE")
            yield _tip(
                "REAL = live Binance data.\n"
                "RANDOM WALK = single simulated GBM price path.\n"
                "MONTE CARLO = batch of independent simulated paths."
            )
        yield Select(
            [
                ("Real Market Data",       "REAL"),
                ("Random Walk  (GBM)",     "RANDOM_WALK"),
                ("Monte Carlo  (N Paths)", "MONTE_CARLO"),
            ],
            value="REAL",
            id="data-source-select",
        )

        # ── REAL market data config ───────────────────────────────────────────
        with VerticalGroup(id="data-real-section"):
            with Collapsible(title="ASSET SELECTION", id="asset-collapsible"):
                yield Input(placeholder="Search assets...", id="asset-search")
                with Horizontal(classes="sel-btn-row"):
                    yield Button("SELECT ALL",   id="select-all-btn")
                    yield Button("DESELECT ALL", id="deselect-all-btn")
                with VerticalGroup(id="asset-checkbox-container"):
                    df_constants = DataframeConstantsBinance()
                    for sym in df_constants.ACTIVES:
                        yield Checkbox(sym, value=(sym == "BTCUSDT"),
                                       id=f"check-{sym}", classes="asset-checkbox")

            with Collapsible(title="CORE SETTINGS", collapsed=False):
                with Horizontal(classes="label-row"):
                    yield Label("INTERVAL")
                    yield _tip("Candlestick time frame per bar.\n1h = one candle per hour.\nSmaller intervals = more data, slower load.")
                yield Select(
                    [("15m", "15m"), ("1h", "1h"), ("4h", "4h"), ("1d", "1d")],
                    value="1h", id="interval-select",
                )
                with Horizontal(classes="date-header-row"):
                    yield Label("BALANCE ($) ")
                    yield _tip("Starting capital in USD for the entire backtest portfolio.")
                    yield Label("●", id="balance-status", classes="date-status-ok")
                yield Input("1000", id="balance-input")

            with Collapsible(title="START DATE", collapsed=False):
                with Horizontal(classes="date-header-row"):
                    yield _tip("First date of historical data to fetch.\nFormat: YYYY-MM-DD\nMinimum: 2017-01-01")
                    yield Label("●", id="start-date-status", classes="date-status-ok")
                    yield Label("(Min: 2017-01-01)", id="min-date-hint")
                yield Input("2023-01-01", id="start-date-input")
                yield Button("PICK", id="start-cal-btn")

            with Collapsible(title="END DATE", collapsed=False):
                with Horizontal(classes="date-header-row"):
                    yield _tip("Last date of historical data.\nLeave empty to use the most recent candle available.")
                    yield Label("● NOW", id="end-date-status", classes="date-status-ok")
                    yield Label("(leave empty = now)", classes="date-status-ok")
                yield Input("", id="end-date-input", placeholder="Now (leave empty)")
                yield Button("PICK", id="end-cal-btn")

        # ── Random Walk config ────────────────────────────────────────────────
        with VerticalGroup(id="data-rw-section", classes="hidden"):
            with Horizontal(classes="label-row"):
                yield Label("INTERVAL")
                yield _tip("Candlestick time frame for each simulated bar.")
            yield Select(
                [("15m", "15m"), ("1h", "1h"), ("4h", "4h"), ("1d", "1d")],
                value="1h", id="rw-interval-select",
            )
            yield Label("BALANCE ($)")
            yield Input("1000", id="rw-balance-input")
            with Horizontal(classes="label-row"):
                yield Label("N BARS (CANDLES)")
                yield _tip("Number of synthetic candles to generate per asset.")
            yield Input("1000", id="rw-n-bars")
            yield Label("START PRICE ($)")
            yield Input("100.0", id="rw-start-price")
            with Horizontal(classes="label-row"):
                yield Label("DRIFT  (% PER BAR)")
                yield _tip("Mean directional trend per bar.\nPositive = upward bias on average.\n0.05 = 0.05% per candle.")
            yield Input("0.05", id="rw-drift")
            with Horizontal(classes="label-row"):
                yield Label("VOLATILITY  (% PER BAR)")
                yield _tip("Standard deviation of returns per bar.\nHigher = wilder price swings.\n2.0 = 2% std dev per candle.")
            yield Input("2.0", id="rw-volatility")
            with Horizontal(classes="label-row"):
                yield Label("SEED  (-1 = RANDOM)")
                yield _tip("Random seed for reproducible results.\n-1 = different result each run.")
            yield Input("-1", id="rw-seed")

        # ── Monte Carlo config ────────────────────────────────────────────────
        with VerticalGroup(id="data-mc-section", classes="hidden"):
            with Horizontal(classes="label-row"):
                yield Label("INTERVAL")
                yield _tip("Candlestick time frame for each simulated bar.")
            yield Select(
                [("15m", "15m"), ("1h", "1h"), ("4h", "4h"), ("1d", "1d")],
                value="1h", id="mc-interval-select",
            )
            yield Label("BALANCE ($)")
            yield Input("1000", id="mc-balance-input")
            with Horizontal(classes="label-row"):
                yield Label("N SIMULATIONS")
                yield _tip("Number of independent price paths to run.\nHigher = more reliable distribution of outcomes.")
            yield Input("50", id="mc-n-sims")
            with Horizontal(classes="label-row"):
                yield Label("N BARS PER PATH")
                yield _tip("Number of candles in each simulated path.")
            yield Input("1000", id="mc-n-bars")
            yield Label("START PRICE ($)")
            yield Input("100.0", id="mc-start-price")
            with Horizontal(classes="label-row"):
                yield Label("DRIFT  (% PER BAR)")
                yield _tip("Mean directional trend per bar.\nPositive = upward bias on average.")
            yield Input("0.05", id="mc-drift")
            with Horizontal(classes="label-row"):
                yield Label("VOLATILITY  (% PER BAR)")
                yield _tip("Standard deviation of returns per bar.\nHigher = wilder price swings.")
            yield Input("2.0", id="mc-volatility")
            with Horizontal(classes="label-row"):
                yield Label("BASE SEED  (-1 = RANDOM)")
                yield _tip("Seed offset for all paths.\nEach path i uses seed+i.\n-1 = fully random each run.")
            yield Input("-1", id="mc-seed")


class DataTab(TabPane):
    def __init__(self, **kwargs):
        super().__init__("DATA", **kwargs)
        self.scroll_manager = DataTabScrollManager()

    def compose(self) -> ComposeResult:
        yield DataTabScroll(self.scroll_manager, id="data-tab-scroll")

    def on_mount(self) -> None:
        scroll = self.query_one("#data-tab-scroll", DataTabScroll)
        scroll.mount(_DataContent())
        self.call_after_refresh(self.scroll_manager.refresh_layout)

    def on_show(self) -> None:
        self.call_after_refresh(self.scroll_manager.refresh_layout)

    # ── Local event handlers ──────────────────────────────────────────────────

    @on(Select.Changed, "#data-source-select")
    def on_data_source_changed(self, event: Select.Changed) -> None:
        mode = str(event.value) if event.value else "REAL"
        try:
            self.query_one("#data-real-section").set_class(mode != "REAL",       "hidden")
            self.query_one("#data-rw-section").set_class(mode != "RANDOM_WALK",  "hidden")
            self.query_one("#data-mc-section").set_class(mode != "MONTE_CARLO",  "hidden")
        except Exception:
            pass
        try:
            self.app.query_one("#vbt-sell-at-end", Switch).disabled = False
        except Exception:
            pass
        try:
            self.app._rebuild_allocation_inputs(reset=True)
            self.app._refresh_pie_live()
        except Exception:
            pass
        self.call_after_refresh(self.scroll_manager.refresh_layout)

    @on(Input.Changed, "#asset-search")
    def filter_assets(self, event: Input.Changed) -> None:
        query = event.value.upper()
        container = self.query_one("#asset-checkbox-container", VerticalGroup)
        for checkbox in container.query(Checkbox):
            checkbox.display = query in str(checkbox.label).upper()
        self.call_after_refresh(self.scroll_manager.refresh_layout)

    @on(Input.Changed, "#start-date-input")
    def validate_start_date(self, event: Input.Changed) -> None:
        val       = event.value.strip()
        indicator = self.query_one("#start-date-status", Label)
        hint      = self.query_one("#min-date-hint", Label)
        inpt      = event.input
        if not val:
            indicator.update("?")
            indicator.set_classes("")
            return
        try:
            dt     = datetime.strptime(val, "%Y-%m-%d")
            min_dt = datetime(2017, 1, 1)
            if dt < min_dt:
                raise ValueError("DATE PRIOR TO MINIMUM HISTORY")
            if dt > datetime.now():
                raise ValueError("FUTURE DATES PROHIBITED")
            indicator.update("● READY")
            indicator.set_classes("date-status-ok")
            hint.update("(Valid Range)")
            hint.styles.color = "#00ff00"
            inpt.styles.color = "#00ff00"
        except Exception as e:
            indicator.update("✖ INVALID")
            indicator.set_classes("date-status-fail")
            hint.update(f"(Err: {str(e)[:15]})")
            hint.styles.color = "#ff0000"
            inpt.styles.color = "#ff0000"

    @on(Input.Changed, "#end-date-input")
    def validate_end_date(self, event: Input.Changed) -> None:
        val       = event.value.strip()
        inpt      = event.input
        indicator = self.query_one("#end-date-status", Label)
        if not val:
            indicator.update("● NOW")
            indicator.set_classes("date-status-ok")
            inpt.styles.color = "#00ff00"
            return
        try:
            dt        = datetime.strptime(val, "%Y-%m-%d")
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

    @on(Input.Changed, "#balance-input")
    def validate_balance(self, event: Input.Changed) -> None:
        val       = event.value.strip()
        inpt      = event.input
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

    @on(Button.Pressed, "#select-all-btn")
    def select_all(self) -> None:
        for cb in self.query_one("#asset-checkbox-container", VerticalGroup).query(Checkbox):
            cb.value = True

    @on(Button.Pressed, "#deselect-all-btn")
    def deselect_all(self) -> None:
        for cb in self.query_one("#asset-checkbox-container", VerticalGroup).query(Checkbox):
            cb.value = False

    @on(Button.Pressed, "#start-cal-btn")
    def show_start_cal(self) -> None:
        self.app.query_one("#start-calendar").toggle_class("hidden")

    @on(Button.Pressed, "#end-cal-btn")
    def show_end_cal(self) -> None:
        self.app.query_one("#end-calendar").toggle_class("hidden")

    @on(Checkbox.Changed, ".asset-checkbox")
    def on_asset_toggled(self, event: Checkbox.Changed) -> None:
        if not self.app.state.loading:
            self.app._rebuild_allocation_inputs(reset=True)
            self.app._refresh_pie_live()
            self.app._save()
