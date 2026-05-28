"""Monte Carlo-only analysis language and scoring."""

from __future__ import annotations


def compute_scores(results: dict, _trades: list) -> dict[str, int]:
    dist = results.get("simulation_distribution", {})
    prob_positive = dist.get("probability_positive_pct", results.get("win_rate", 0.0))
    median = dist.get("median_return_pct", results.get("total_return_pct", 0.0))
    p05 = dist.get("p05_return_pct", median)
    p95 = dist.get("p95_return_pct", median)
    dispersion = max(0.0, p95 - p05)
    max_dd = abs(dist.get("median_max_drawdown_pct", results.get("max_drawdown_pct", 0.0)))
    valid = max(1, int(dist.get("valid_paths", results.get("total_trades", 1))))

    outcome = min(100, max(0, int(50 + median * 2)))
    robustness = min(100, max(0, int(prob_positive)))
    variance = min(100, max(0, int(100 - dispersion * 1.5)))
    drawdown = min(100, max(0, int(100 - max_dd * 2)))
    sample = min(100, int(valid / 100 * 100)) if valid < 100 else 100
    overall = int(0.25 * outcome + 0.30 * robustness + 0.20 * variance + 0.15 * drawdown + 0.10 * sample)
    return {
        "overall": overall,
        "outcome": outcome,
        "robustness": robustness,
        "variance": variance,
        "drawdown": drawdown,
        "sample": sample,
    }


def detect_patterns(results: dict, _trades: list, setup_info: dict | None = None) -> list[tuple[str, str]]:
    setup_info = setup_info or {}
    dist = results.get("simulation_distribution", {})
    valid = dist.get("valid_paths", results.get("total_trades", 0))
    prob = dist.get("probability_positive_pct", results.get("win_rate", 0.0))
    median = dist.get("median_return_pct", results.get("total_return_pct", 0.0))
    p05 = dist.get("p05_return_pct", median)
    p95 = dist.get("p95_return_pct", median)
    dd = abs(dist.get("median_max_drawdown_pct", results.get("max_drawdown_pct", 0.0)))
    n_sims = setup_info.get("n_sims", valid)

    findings = [("info", f"Monte Carlo environment: {valid}/{n_sims} valid synthetic simulation paths analyzed.")]
    findings.append(("info", f"Terminal return distribution: p05 {p05:+.2f}%, median {median:+.2f}%, p95 {p95:+.2f}%."))
    findings.append(("info", f"Probability of positive terminal outcome: {prob:.1f}%."))
    if p05 < -15:
        findings.append(("warn", f"Left-tail outcome risk is material: 5th percentile return is {p05:+.2f}%."))
    if (p95 - p05) > 40:
        findings.append(("warn", "Wide simulation envelope detected; variance dominates the outcome distribution."))
    if dd > 25:
        findings.append(("warn", f"Median path drawdown is high at {dd:.1f}%."))
    elif dd < 10 and valid >= 30:
        findings.append(("ok", f"Median simulated drawdown is contained at {dd:.1f}%."))
    if prob >= 70:
        findings.append(("ok", "Positive outcomes dominate the simulated route distribution."))
    elif prob < 45:
        findings.append(("warn", "Less than half of simulated paths finish positive."))
    return findings


def build_recommendations(scores: dict, _patterns: list[tuple[str, str]], results: dict) -> list[str]:
    dist = results.get("simulation_distribution", {})
    recs = []
    if scores.get("variance", 0) < 50:
        recs.append("Reduce variance exposure or test volatility-based sizing across the path distribution.")
    if scores.get("robustness", 0) < 55:
        recs.append("Tune parameters for higher probability of positive terminal outcomes, not only higher median return.")
    if abs(dist.get("median_max_drawdown_pct", results.get("max_drawdown_pct", 0.0))) > 20:
        recs.append("Add drawdown constraints and rerun the simulation envelope.")
    if scores.get("sample", 0) < 75:
        recs.append("Increase the number of simulation paths for a more stable distribution estimate.")
    if not recs:
        recs.append("Validate robustness by rerunning with different seeds, drift, and volatility assumptions.")
    return recs[:5]


def build_prompt(results: dict, _trades: list, setup_info: dict) -> str:
    dist = results.get("simulation_distribution", {})
    return (
        "You are analyzing a Monte Carlo probabilistic simulation environment. "
        "Discuss only simulation paths, terminal distributions, probability ranges, variance, "
        "confidence bands, drawdown distribution, and robustness.\n\n"
        f"Paths: {dist.get('valid_paths', setup_info.get('n_sims', 0))}  "
        f"Bars/path: {setup_info.get('n_bars', 0)}  Drift: {setup_info.get('drift', 0.0):+.2f}%  "
        f"Volatility: {setup_info.get('volatility', 0.0):.2f}%\n"
        f"Median return: {dist.get('median_return_pct', results.get('total_return_pct', 0.0)):+.2f}%  "
        f"P05/P95: {dist.get('p05_return_pct', 0.0):+.2f}% / {dist.get('p95_return_pct', 0.0):+.2f}%  "
        f"P(terminal > start): {dist.get('probability_positive_pct', results.get('win_rate', 0.0)):.1f}%  "
        f"Median max drawdown: {dist.get('median_max_drawdown_pct', results.get('max_drawdown_pct', 0.0)):.2f}%\n\n"
        "Write 3 concise paragraphs: distribution assessment, robustness strengths, and simulation risks/improvements."
    )
