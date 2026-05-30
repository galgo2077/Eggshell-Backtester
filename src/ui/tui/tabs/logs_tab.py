"""Logs tab — results panel. Scrollable rich log + Ollama runtime status."""
from __future__ import annotations

import subprocess
from threading import Thread

from textual.app import ComposeResult
from textual.widgets import TabPane, RichLog, Static
from textual.containers import Vertical


_OLLAMA_REFRESH_SEC = 5


class LogsTab(TabPane):
    def __init__(self, **kwargs):
        super().__init__("LOGS", id="tab-logs", **kwargs)
        self._ollama_timer = None
        self._ollama_visible = False

    def compose(self) -> ComposeResult:
        with Vertical(id="logs-outer"):
            yield RichLog(id="main-log", highlight=True, markup=True)
            yield Static("", id="ollama-status-panel")

    # ── Ollama monitor lifecycle ──────────────────────────────────────────────

    def start_ollama_monitor(self) -> None:
        if self._ollama_timer is not None:
            return
        self._ollama_visible = True
        self._ollama_timer = self.set_interval(_OLLAMA_REFRESH_SEC, self._schedule_refresh)
        self._schedule_refresh()
        try:
            self.query_one("#ollama-status-panel").add_class("ollama-visible")
        except Exception:
            pass

    def stop_ollama_monitor(self) -> None:
        if self._ollama_timer is not None:
            self._ollama_timer.stop()
            self._ollama_timer = None
        self._ollama_visible = False
        try:
            panel = self.query_one("#ollama-status-panel")
            panel.remove_class("ollama-visible")
            panel.update("")
        except Exception:
            pass

    def _schedule_refresh(self) -> None:
        Thread(target=self._fetch_ollama_status, daemon=True).start()

    def _fetch_ollama_status(self) -> None:
        try:
            result = subprocess.run(
                ["ollama", "ps"],
                capture_output=True, text=True, timeout=4
            )
            markup = self._parse_ollama_ps(result.stdout, result.returncode)
        except FileNotFoundError:
            markup = self._offline_markup("ollama command not found")
        except subprocess.TimeoutExpired:
            markup = self._offline_markup("ollama ps timed out")
        except Exception as e:
            markup = self._offline_markup(str(e))

        if self._ollama_visible:
            self.app.call_from_thread(self._apply_status, markup)

    def _apply_status(self, markup: str) -> None:
        try:
            self.query_one("#ollama-status-panel").update(markup)
        except Exception:
            pass

    @staticmethod
    def _parse_ollama_ps(stdout: str, returncode: int) -> str:
        lines = [l for l in stdout.strip().splitlines() if l.strip()]

        if returncode != 0 or len(lines) < 2:
            # No model loaded — service is up but idle
            return (
                "[dim]──────────────────────────[/dim]\n"
                "[bold dim]OLLAMA STATUS[/bold dim]\n"
                "[green]●[/green] [bold]ONLINE[/bold]  [dim]Model:[/dim] [yellow]NONE LOADED[/yellow]\n"
                "[dim]Inference:[/dim] IDLE"
            )

        # Parse header + first data row
        # Expected: NAME   ID   SIZE   PROCESSOR   UNTIL
        try:
            header = lines[0].lower().split()
            row    = lines[1].split()

            def _col(name: str) -> str:
                try:
                    idx = next(i for i, h in enumerate(header) if name in h)
                    return row[idx] if idx < len(row) else "—"
                except StopIteration:
                    return "—"

            model     = row[0] if row else "—"
            size      = _col("size")
            processor = " ".join(row[3:5]) if len(row) >= 5 else _col("processor")
            is_gpu    = "gpu" in processor.lower()
            proc_color = "green" if is_gpu else "yellow"
            backend    = "GPU" if is_gpu else "CPU"

            return (
                "[dim]──────────────────────────[/dim]\n"
                "[bold dim]OLLAMA STATUS[/bold dim]\n"
                f"[green]●[/green] [bold]ACTIVE[/bold]\n"
                f"[dim]Model:[/dim]     [bold]{model}[/bold]\n"
                f"[dim]VRAM:[/dim]      [bold]{size}[/bold]\n"
                f"[dim]Backend:[/dim]   [{proc_color}][bold]{backend}[/bold][/{proc_color}]  [dim]{processor}[/dim]\n"
                f"[dim]Inference:[/dim] [bold green]ACTIVE[/bold green]"
            )
        except Exception:
            return (
                "[dim]──────────────────────────[/dim]\n"
                "[bold dim]OLLAMA STATUS[/bold dim]\n"
                f"[green]●[/green] ONLINE  [dim](raw)[/dim] {stdout[:120]}"
            )

    @staticmethod
    def _offline_markup(reason: str) -> str:
        return (
            "[dim]──────────────────────────[/dim]\n"
            "[bold dim]OLLAMA STATUS[/bold dim]\n"
            "[red]●[/red] [bold red]OFFLINE[/bold red]\n"
            f"[dim]Reason:[/dim] {reason}"
        )
