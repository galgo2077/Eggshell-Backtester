"""Live trading analysis boundary."""

from __future__ import annotations


def compute_scores(_results: dict, _trades: list) -> dict[str, int]:
    return {"overall": 0, "execution": 0, "exposure": 0, "pnl": 0, "risk": 0}


def detect_patterns(_results: dict, _trades: list, _setup_info: dict | None = None) -> list[tuple[str, str]]:
    return [("info", "Live trading environment requires active broker/exchange execution data.")]


def build_recommendations(_scores: dict, _patterns: list[tuple[str, str]], _results: dict) -> list[str]:
    return ["Connect live execution records before generating live trading analytics."]


def build_prompt(_results: dict, _trades: list, _setup_info: dict) -> str:
    return "Live trading analysis requires active positions, broker data, execution records, and real PnL."
