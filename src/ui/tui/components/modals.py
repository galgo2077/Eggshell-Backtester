"""Modal dialogs: save-name prompt, load-backtest picker, portfolio allocation editor, chart URL."""
import os
import re as _re

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Label, Input, DataTable
from textual import on


class SaveNameModal(ModalScreen):
    CSS = """
    SaveNameModal { align: center middle; }
    SaveNameModal > Vertical {
        width: 64; height: auto;
        background: #111827; border: heavy #00ffff; padding: 2 3;
    }
    SaveNameModal .modal-title { color: #00ffff; text-style: bold; text-align: center; width: 100%; margin-bottom: 1; }
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
        raw  = self.query_one("#save-name-input", Input).value.strip()
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
    LoadBacktestModal .modal-title { color: #00ffff; text-style: bold; text-align: center; width: 100%; margin-bottom: 1; }
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
                name     = f.replace("_", " ")
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


class AllocModal(ModalScreen):
    CSS = """
    AllocModal { align: center middle; }
    AllocModal > Vertical {
        width: 48; height: 85%; max-height: 85%;
        background: #111827; border: heavy #00ffff; padding: 2 3;
    }
    AllocModal .modal-title { color: #00ffff; text-style: bold; text-align: center; width: 100%; margin-bottom: 1; }
    AllocModal VerticalScroll { height: 1fr; border: solid #1a1a1a; }
    AllocModal .alloc-modal-label { color: #888888; margin-top: 1; }
    AllocModal .alloc-modal-input { height: 3; border-bottom: solid #00ffff; color: #00ff00; background: #111111; }
    AllocModal #alloc-modal-total { text-style: bold; margin-top: 1; color: #00ff00; }
    AllocModal #alloc-modal-total.invalid { color: #ff0000; }
    AllocModal .modal-btns { height: 3; margin-top: 1; }
    AllocModal .modal-btns Button { width: 1fr; height: 3; margin: 0; }
    AllocModal #alloc-modal-ok { background: #005500; color: #fff; text-style: bold; margin-right: 1; }
    AllocModal #alloc-modal-ok:hover { background: #00ff00; color: #000; }
    AllocModal #alloc-modal-cancel { background: #550000; }
    AllocModal #alloc-modal-cancel:hover { background: #ff0000; }
    """

    def __init__(self, assets: list, current_alloc: dict, **kwargs):
        super().__init__(**kwargs)
        self._assets       = assets
        self._current_alloc = dict(current_alloc)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("PORTFOLIO ALLOCATION", classes="modal-title")
            with VerticalScroll():
                for asset in self._assets:
                    sym = asset.replace("USDT", "")
                    val = str(self._current_alloc.get(asset, round(100.0 / max(len(self._assets), 1), 2)))
                    yield Label(f"{sym}  (%)", classes="alloc-modal-label")
                    yield Input(val, id=f"alloc-modal-{asset}", classes="alloc-modal-input")
            yield Label("TOTAL: 0.0%", id="alloc-modal-total")
            with Horizontal(classes="modal-btns"):
                yield Button("CONFIRM", id="alloc-modal-ok")
                yield Button("CANCEL", id="alloc-modal-cancel")

    def on_mount(self) -> None:
        self._refresh_total()

    @on(Input.Changed, ".alloc-modal-input")
    def _on_alloc_modal_input(self, event: Input.Changed) -> None:
        self._refresh_total()

    def _refresh_total(self) -> None:
        total = 0.0
        for asset in self._assets:
            try:
                total += float(self.query_one(f"#alloc-modal-{asset}", Input).value)
            except Exception:
                pass
        lbl = self.query_one("#alloc-modal-total", Label)
        lbl.update(f"TOTAL: {total:.1f}%")
        if abs(total - 100.0) < 0.1:
            lbl.remove_class("invalid")
        else:
            lbl.add_class("invalid")

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)

    def _confirm(self) -> None:
        result = {}
        for asset in self._assets:
            try:
                result[asset] = float(self.query_one(f"#alloc-modal-{asset}", Input).value)
            except Exception:
                result[asset] = round(100.0 / max(len(self._assets), 1), 2)
        self.dismiss(result)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "alloc-modal-ok":
            self._confirm()
        elif event.button.id == "alloc-modal-cancel":
            self.dismiss(None)


class ChartUrlModal(ModalScreen):
    """Shows the chart URL in a selectable Input — works on headless/remote servers."""

    CSS = """
    ChartUrlModal { align: center middle; }
    ChartUrlModal > Vertical {
        width: 82; height: auto;
        background: #0d1117; border: heavy #00ffff; padding: 2 3;
    }
    ChartUrlModal .modal-title {
        color: #00ffff; text-style: bold; text-align: center;
        width: 100%; margin-bottom: 1;
    }
    ChartUrlModal .url-label {
        color: #888888; margin-top: 1; margin-bottom: 1;
    }
    ChartUrlModal #chart-url-input {
        background: #1e293b; color: #00ff00; text-style: bold;
        border: solid #00ff00; width: 100%; margin-bottom: 1; height: 3;
    }
    ChartUrlModal #chart-url-input:focus {
        border: solid #00ff00;
    }
    ChartUrlModal .hint {
        color: #555555; margin-top: 1; margin-bottom: 1;
    }
    ChartUrlModal #chart-url-close {
        background: #00ffff; color: #000000; text-style: bold;
        width: 100%; height: 3; margin-top: 1;
    }
    ChartUrlModal #chart-url-close:hover { background: #ffffff; }
    """

    def __init__(self, url: str, **kwargs):
        super().__init__(**kwargs)
        self._url = url

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("CHART URL", classes="modal-title")
            yield Label("Auto-copied to clipboard  ·  Or select all Ctrl+A and copy Ctrl+C  ·  Close Esc", classes="url-label")
            yield Input(self._url, id="chart-url-input")
            yield Label(
                "Vast.ai SSH tunnel:  ssh -L 8080:localhost:8080 root@<ip> -p <port>\n"
                "Or expose port 8080 in instance settings and use the public IP.",
                classes="hint",
            )
            yield Button("CLOSE", id="chart-url-close")

    def on_mount(self) -> None:
        inp = self.query_one("#chart-url-input", Input)
        inp.focus()
        inp.action_select_all()

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "chart-url-close":
            self.dismiss(None)
