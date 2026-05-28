"""Random Walk-only analysis language and scoring."""

from __future__ import annotations


def compute_scores(results: dict, _trades: list) -> dict[str, int]:
    roi = results.get("total_return_pct", 0.0)
    max_dd = abs(results.get("max_drawdown_pct", 0.0))
    sharpe = results.get("sharpe_ratio", 0.0)
    pf = results.get("profit_factor", 0.0)
    n = results.get("total_trades", 0)
    movement = min(100, max(0, int(50 + roi * 2)))
    risk = min(100, max(0, int(100 - max_dd * 2)))
    stochastic_fit = min(100, max(0, int(50 + sharpe * 20)))
    signal_response = min(100, max(0, int(pf * 35)))
    sample = 100 if n >= 20 else max(10, int(n / 20 * 100))
    overall = int(0.25 * movement + 0.25 * risk + 0.20 * stochastic_fit + 0.20 * signal_response + 0.10 * sample)
    return {
        "overall": overall,
        "movement": movement,
        "risk": risk,
        "stochastic": stochastic_fit,
        "signal": signal_response,
        "sample": sample,
    }


def detect_patterns(results: dict, _trades: list, setup_info: dict | None = None) -> list[tuple[str, str]]:
    setup_info = setup_info or {}
    drift = setup_info.get("drift", 0.0)
    vol = setup_info.get("volatility", 0.0)
    roi = results.get("total_return_pct", 0.0)
    dd = abs(results.get("max_drawdown_pct", 0.0))
    n = results.get("total_trades", 0)
    findings = [
        ("info", f"Random Walk environment: synthetic stochastic path with drift {drift:+.2f}% and volatility {vol:.2f}% per bar."),
        ("info", f"Synthetic path response return is {roi:+.2f}% with {dd:.1f}% maximum drawdown."),
    ]
    if vol > abs(drift) * 10 and vol > 1:
        findings.append(("info", "Volatility dominates drift; path dispersion is the main driver."))
    if dd > 25:
        findings.append(("warn", "Synthetic path drawdown is large under the configured volatility propagation."))
    if n < 10:
        findings.append(("warn", "Few synthetic signal events occurred; stochastic sample is thin."))
    return findings


def build_recommendations(scores: dict, _patterns: list[tuple[str, str]], _results: dict) -> list[str]:
    recs = []
    if scores.get("risk", 0) < 55:
        recs.append("Lower volatility assumptions or reduce position sizing in stochastic stress tests.")
    if scores.get("signal", 0) < 50:
        recs.append("Check whether entry logic is too sensitive to random path noise.")
    if scores.get("sample", 0) < 70:
        recs.append("Increase synthetic bars or adjust signal thresholds to improve stochastic sample size.")
    if not recs:
        recs.append("Rerun the random walk with alternate seeds to test path dependence.")
    return recs[:5]


def build_prompt(results: dict, _trades: list, setup_info: dict) -> str:
    return (
        "You are analyzing a Random Walk stochastic model. Focus only on path randomness, drift, "
        "volatility propagation, entropy, and synthetic signal behavior.\n\n"
        f"Bars: {setup_info.get('n_bars', 0)}  Drift: {setup_info.get('drift', 0.0):+.2f}%  "
        f"Volatility: {setup_info.get('volatility', 0.0):.2f}%/bar  "
        f"Return: {results.get('total_return_pct', 0.0):+.2f}%  "
        f"Max drawdown: {results.get('max_drawdown_pct', 0.0):.2f}%  "
        f"Synthetic signal events: {results.get('total_trades', 0)}\n\n"
        "Write 3 concise paragraphs: stochastic movement assessment, strengths, and random-path risks/improvements."
    )
