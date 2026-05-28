"""Shared utility helpers — server IP detection, chart URL building, tooltip factory."""
import os
import socket
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from textual.widgets import Static

_REPORTS_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))),
    "reports",
)
_CHART_PORT = int(os.environ.get("EGGSHELL_CHART_PORT", "8080"))
_CHART_SERVER: ThreadingHTTPServer | None = None
_CHART_THREAD: Thread | None = None


class _QuietChartHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:
        return


def _server_ip() -> str:
    host = os.environ.get("EGGSHELL_HOST")
    if host:
        return host
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "SERVER_IP"


def _chart_url(file_path: str, anchor: str = "") -> str:
    ensure_chart_server()
    rel = os.path.relpath(file_path, _REPORTS_ROOT).replace(os.sep, "/")
    url = f"http://{_server_ip()}:{_CHART_PORT}/{rel}"
    return url + (f"#{anchor}" if anchor else "")


def ensure_chart_server() -> str:
    """Serve reports/ over HTTP so browser chart buttons always have a target."""
    global _CHART_SERVER, _CHART_THREAD

    if _CHART_SERVER is not None:
        return f"http://{_server_ip()}:{_CHART_PORT}"

    os.makedirs(_REPORTS_ROOT, exist_ok=True)
    handler = partial(_QuietChartHandler, directory=_REPORTS_ROOT)
    try:
        server = ThreadingHTTPServer(("0.0.0.0", _CHART_PORT), handler)
    except OSError:
        return f"http://{_server_ip()}:{_CHART_PORT}"

    thread = Thread(target=server.serve_forever, daemon=True, name="eggshell-chart-server")
    thread.start()
    _CHART_SERVER = server
    _CHART_THREAD = thread
    return f"http://{_server_ip()}:{_CHART_PORT}"


def _tip(text: str) -> Static:
    """Return an ⓘ info-icon widget with a tooltip."""
    w = Static("ⓘ", classes="info-icon")
    w.tooltip = text
    return w
