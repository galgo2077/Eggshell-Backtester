"""
Risk tab — left config panel, fourth tab.
Contains budget, cooldown, sell-at-end, trading costs, order behaviour,
and the portfolio allocation opener button.
"""
from textual.app import ComposeResult
from textual.widgets import (
    TabPane, Label, Input, Select, Switch, Button, Collapsible, Static,
)
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual import on

from ..utils.helpers import _tip
from ..components.modals import AllocModal


class RiskTab(TabPane):
    def __init__(self, **kwargs):
        super().__init__("RISK", id="tab-risk-pane", **kwargs)

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="risk-tab-scroll"):
            yield Static("", id="portfolio-mode-badge", classes="hidden portfolio-badge")

            with Horizontal(classes="date-header-row"):
                yield Label("BUDGET PER TRADE (%) ", id="size-label")
                yield _tip(
                    "% of total balance invested per trade signal.\n"
                    "E.g. 20% of $1000 balance = $200 per entry.\n"
                    "Lower = smaller positions, higher = larger exposure."
                )
                yield Label("●", id="size-status", classes="date-status-ok")
            yield Input("20", id="size-input")

            with Horizontal(classes="date-header-row"):
                yield Label("ENTRY COOLDOWN  (candles after close) ")
                yield _tip(
                    "Candles to skip after a position closes before allowing a new entry.\n"
                    "0 = re-enter immediately on the next signal."
                )
                yield Label("●", id="cooldown-status", classes="date-status-ok")
            yield Input("0", id="cooldown-input")

            with Horizontal(classes="inline-field"):
                yield Label("SELL AT END")
                yield _tip(
                    "Force-close all open positions on the final candle.\n"
                    "Useful for clean P&L accounting at end of backtest window."
                )
                yield Switch(False, id="vbt-sell-at-end")

            with Vertical(id="alloc-section"):
                yield Button("⬡  SET ALLOCATION", id="alloc-open-btn")
                yield Label("TOTAL: 0.0%", id="alloc-total")

            with Collapsible(title="TRADING COSTS", classes="indicator-collapsible"):
                with Horizontal(classes="label-row"):
                    yield Label("COMMISSION  (% per trade)")
                    yield _tip("Percentage fee per order.\nBinance spot charges ~0.1%.\n0.1 = 0.1% of trade value.")
                yield Input("0.0", id="vbt-fees")
                with Horizontal(classes="label-row"):
                    yield Label("FIXED FEE  ($  per order)")
                    yield _tip("Fixed USD cost added to every order,\nregardless of trade size.")
                yield Input("0.0", id="vbt-fixed-fees")
                with Horizontal(classes="label-row"):
                    yield Label("SLIPPAGE  (% per fill)")
                    yield _tip("Price slippage per fill.\nBuys fill slightly higher, sells lower.\nModels real-world execution cost.")
                yield Input("0.0", id="vbt-slippage")

            with Collapsible(title="ORDER BEHAVIOUR", classes="indicator-collapsible"):
                with Horizontal(classes="inline-field"):
                    yield Label("PYRAMIDING")
                    yield _tip(
                        "Allow stacking multiple buy entries\n"
                        "per asset before the first closes.\n"
                        "OFF = only one open position per asset."
                    )
                    yield Switch(True, id="vbt-accumulate")
                with Horizontal(classes="inline-field"):
                    yield Label("CASH SHARING")
                    yield _tip("Share a single cash pool across all assets.\nOFF = each asset gets its own isolated capital.")
                    yield Switch(True, id="vbt-cash-sharing")
                with Horizontal(classes="label-row"):
                    yield Label("SIZE TYPE")
                    yield _tip("Value: invest a fixed $ amount per trade.\nPercent: invest a % of remaining capital per trade.")
                yield Select(
                    [("Value ($) — fixed $ per trade", "value"),
                     ("Percent (%) — % of capital",   "percent")],
                    value="value", id="vbt-size-type",
                )
                with Horizontal(classes="inline-field"):
                    yield Label("ALLOW PARTIAL FILL")
                    yield _tip("Allow orders to fill partially\nif capital is insufficient for the full size.")
                    yield Switch(True, id="vbt-allow-partial")
                with Horizontal(classes="inline-field"):
                    yield Label("LOCK CASH")
                    yield _tip("Reserve cash for pending orders\nbefore they execute. Prevents over-allocation.")
                    yield Switch(False, id="vbt-lock-cash")
                with Horizontal(classes="label-row"):
                    yield Label("ORDER REJECT PROB  (%)")
                    yield _tip("Probability (%) that an order is randomly rejected.\n0 = never rejected. Simulates exchange failures.")
                yield Input("0.0", id="vbt-reject-prob")
                yield Label("MIN ORDER SIZE  (units, 0 = off)")
                yield Input("0.0", id="vbt-min-size")
                yield Label("MAX ORDER SIZE  (units, 0 = unlimited)")
                yield Input("0.0", id="vbt-max-size")
                with Horizontal(classes="label-row"):
                    yield Label("UPON OPPOSITE ENTRY")
                    yield _tip(
                        "What happens when a sell signal fires while long\n"
                        "(or buy signal fires while short).\n"
                        "Reverse: flip position. Close: close first. Ignore: skip."
                    )
                yield Select(
                    [("Reverse Position", "reverse"),
                     ("Close First",      "close"),
                     ("Ignore",           "ignore"),
                     ("Add",              "add")],
                    value="reverse", id="vbt-upon-opposite-entry",
                )
                with Horizontal(classes="label-row"):
                    yield Label("DIRECTION")
                    yield _tip(
                        "Long Only: only buy signals are processed.\n"
                        "Short Only: only sell signals.\n"
                        "Both: full long+short trading."
                    )
                yield Select(
                    [("Long Only",          "longonly"),
                     ("Short Only",         "shortonly"),
                     ("Both (Long+Short)",  "both")],
                    value="longonly", id="vbt-direction",
                )
                with Horizontal(classes="label-row"):
                    yield Label("CONFLICT MODE  (entry + exit same candle)")
                    yield _tip(
                        "What to do when a buy AND sell signal fire on the same candle.\n"
                        "Ignore both: skip the candle.\n"
                        "Entry wins: execute the buy.\n"
                        "Exit wins: execute the sell."
                    )
                yield Select(
                    [("Ignore both",    "ignore"),
                     ("Entry wins",     "entry"),
                     ("Exit wins",      "exit"),
                     ("Opposite wins",  "opposite")],
                    value="ignore", id="vbt-conflict-mode",
                )

    def on_mount(self) -> None:
        self.call_after_refresh(self._fix_scroll_height)

    def on_show(self) -> None:
        self.call_after_refresh(self._fix_scroll_height)

    def _fix_scroll_height(self) -> None:
        try:
            scroll = self.query_one("#risk-tab-scroll", VerticalScroll)
            scroll.styles.height = "1fr"
            scroll.styles.overflow_y = "scroll"
            scroll.styles.overflow_x = "hidden"
            scroll.refresh(layout=True)
        except Exception:
            pass

    # ── Local event handlers ──────────────────────────────────────────────────

    @on(Input.Changed, "#size-input")
    def validate_size(self, event: Input.Changed) -> None:
        val       = event.value.strip()
        inpt      = event.input
        indicator = self.query_one("#size-status", Label)
        try:
            if not val:
                raise ValueError("REQUIRED")
            f = float(val)
            try:
                size_type = str(self.query_one("#vbt-size-type", Select).value)
            except Exception:
                size_type = "percent"
            if size_type == "percent":
                if not (0.1 <= f <= 100):
                    raise ValueError("RANGE 0.1–100")
            else:
                if f <= 0:
                    raise ValueError("MUST BE > 0")
            indicator.update("●")
            indicator.set_classes("date-status-ok")
            inpt.styles.color = "#00ff00"
        except Exception:
            indicator.update("✖")
            indicator.set_classes("date-status-fail")
            inpt.styles.color = "#ff0000"

    @on(Input.Changed, "#cooldown-input")
    def validate_cooldown(self, event: Input.Changed) -> None:
        val       = event.value.strip()
        indicator = self.query_one("#cooldown-status", Label)
        try:
            if not val:
                raise ValueError
            if int(float(val)) < 0:
                raise ValueError
            indicator.update("●")
            indicator.set_classes("date-status-ok")
            event.input.styles.color = "#00ff00"
        except Exception:
            indicator.update("✖")
            indicator.set_classes("date-status-fail")
            event.input.styles.color = "#ff0000"

    @on(Select.Changed, "#vbt-size-type")
    def on_size_type_changed(self, event: Select.Changed) -> None:
        is_pct = str(event.value) == "percent"
        try:
            self.query_one("#size-label", Label).update(
                "BUDGET PER TRADE (%) " if is_pct else "BUDGET PER TRADE ($) "
            )
        except Exception:
            pass
        try:
            inpt      = self.query_one("#size-input", Input)
            indicator = self.query_one("#size-status", Label)
            f  = float(inpt.value)
            ok = (0.1 <= f <= 100) if is_pct else (f > 0)
            if ok:
                indicator.update("●")
                indicator.set_classes("date-status-ok")
                inpt.styles.color = "#00ff00"
            else:
                indicator.update("✖")
                indicator.set_classes("date-status-fail")
                inpt.styles.color = "#ff0000"
        except Exception:
            pass

    @on(Button.Pressed, "#alloc-open-btn")
    def on_alloc_open(self, event: Button.Pressed) -> None:
        assets = [
            str(cb.label)
            for cb in self.app.query("#asset-checkbox-container Checkbox")
            if cb.value
        ]

        def _on_dismiss(result) -> None:
            if result is not None:
                self.app.state.alloc_values = result
                for k, v in result.items():
                    self.app.state.active_settings[f"alloc-{k}"] = v
                self.app._update_alloc_total()
                self.app._refresh_pie_live()
                self.app._save()

        self.app.push_screen(AllocModal(assets, self.app.state.alloc_values), _on_dismiss)
