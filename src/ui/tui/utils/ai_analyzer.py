"""
Post-backtest AI analysis: scoring, pattern detection, recommendations, markup.
All functions are pure (no UI dependencies) — composer wires them into the tab.
"""
from __future__ import annotations
from typing import Any

from analysis.modes import (
    MONTE_CARLO, RANDOM_WALK, REAL_MARKET_BACKTEST, LIVE_TRADING, mode_from_setup,
)
from analysis.montecarlo import analyzer as montecarlo_analyzer
from analysis.random_walk import analyzer as random_walk_analyzer
from analysis.live_trading import analyzer as live_trading_analyzer


# ── Score computation ─────────────────────────────────────────────────────────

def _compute_real_market_scores(results: dict, trades: list) -> dict[str, int]:
    roi        = results.get("total_return_pct",  0.0)
    buy_hold   = results.get("buy_hold_pct",       0.0)
    sharpe     = results.get("sharpe_ratio",        0.0)
    max_dd     = abs(results.get("max_drawdown_pct", 0.0))
    win_rate   = results.get("win_rate",            0.0)
    pf         = results.get("profit_factor",       0.0)
    avg_win    = results.get("avg_win_pct",         0.0)
    avg_loss   = abs(results.get("avg_loss_pct",    0.0))
    avg_trade  = results.get("avg_trade_pct",       0.0)
    sym_stats  = results.get("symbol_stats",        {})
    n_trades   = results.get("total_trades",        0)

    # ── Return score ──────────────────────────────────────────────────────────
    if roi > 30:   ret = 95
    elif roi > 20: ret = 82
    elif roi > 10: ret = 68
    elif roi > 5:  ret = 52
    elif roi > 0:  ret = 36
    elif roi > -5: ret = 18
    else:          ret = 5
    if roi > buy_hold + 5:  ret = min(100, ret + 12)
    elif roi < buy_hold - 5: ret = max(0,   ret - 12)

    # ── Risk score ────────────────────────────────────────────────────────────
    if sharpe > 2:    sh = 65
    elif sharpe > 1.5: sh = 52
    elif sharpe > 1:   sh = 38
    elif sharpe > 0.5: sh = 22
    elif sharpe > 0:   sh = 10
    else:              sh = 0
    if max_dd < 5:    dd = 35
    elif max_dd < 10: dd = 27
    elif max_dd < 20: dd = 18
    elif max_dd < 30: dd = 8
    else:              dd = 0
    risk = sh + dd

    # ── Consistency score ─────────────────────────────────────────────────────
    if win_rate > 65:   wr = 50
    elif win_rate > 55: wr = 38
    elif win_rate > 45: wr = 26
    elif win_rate > 35: wr = 14
    else:               wr = 0
    if pf > 2.5:   pfs = 50
    elif pf > 2:   pfs = 40
    elif pf > 1.5: pfs = 28
    elif pf > 1.2: pfs = 15
    elif pf > 1:   pfs = 6
    else:          pfs = 0
    consistency = wr + pfs

    # ── Efficiency score ──────────────────────────────────────────────────────
    rr = avg_win / avg_loss if avg_loss > 0 else 0
    if rr > 3:    rrs = 60
    elif rr > 2:  rrs = 48
    elif rr > 1.5: rrs = 35
    elif rr > 1:  rrs = 20
    else:         rrs = 5
    if avg_trade > 2:    ats = 40
    elif avg_trade > 1:  ats = 30
    elif avg_trade > 0:  ats = 18
    elif avg_trade > -1: ats = 8
    else:                ats = 0
    efficiency = rrs + ats

    # ── Portfolio score ───────────────────────────────────────────────────────
    n_sym = len(sym_stats)
    if n_sym >= 5:   div = 40
    elif n_sym >= 3: div = 30
    elif n_sym >= 2: div = 20
    else:            div = 8
    if sym_stats and n_trades > 0:
        max_t = max(s["trades"] for s in sym_stats.values())
        conc  = max_t / n_trades
        if conc < 0.4:   conc_s = 30
        elif conc < 0.6: conc_s = 20
        elif conc < 0.8: conc_s = 10
        else:             conc_s = 0
    else:
        conc_s = 15
    if sym_stats:
        prof   = sum(1 for s in sym_stats.values() if s["total_pct"] > 0)
        prof_s = int((prof / max(n_sym, 1)) * 30)
    else:
        prof_s = 0
    portfolio = div + conc_s + prof_s

    overall = int(
        0.25 * ret + 0.25 * risk + 0.20 * consistency +
        0.15 * efficiency + 0.15 * portfolio
    )

    return {
        "overall":     min(100, max(0, overall)),
        "return":      min(100, max(0, ret)),
        "risk":        min(100, max(0, risk)),
        "consistency": min(100, max(0, consistency)),
        "efficiency":  min(100, max(0, efficiency)),
        "portfolio":   min(100, max(0, portfolio)),
    }


def compute_scores(results: dict, trades: list, setup_info: dict | None = None) -> dict[str, int]:
    mode = mode_from_setup(setup_info or results)
    if mode == MONTE_CARLO:
        return montecarlo_analyzer.compute_scores(results, trades)
    if mode == RANDOM_WALK:
        return random_walk_analyzer.compute_scores(results, trades)
    if mode == LIVE_TRADING:
        return live_trading_analyzer.compute_scores(results, trades)
    return _compute_real_market_scores(results, trades)


# ── Pattern detection ─────────────────────────────────────────────────────────

def detect_patterns(
    results: dict, trades: list, setup_info: dict | None = None
) -> list[tuple[str, str]]:
    """Returns list of (severity, message). severity: 'warn' | 'ok' | 'info'."""
    mode = mode_from_setup(setup_info or results)
    if mode == MONTE_CARLO:
        return montecarlo_analyzer.detect_patterns(results, trades, setup_info)
    if mode == RANDOM_WALK:
        return random_walk_analyzer.detect_patterns(results, trades, setup_info)
    if mode == LIVE_TRADING:
        return live_trading_analyzer.detect_patterns(results, trades, setup_info)

    findings: list[tuple[str, str]] = []
    setup_info = setup_info or {}
    ds = setup_info.get("data_source", "REAL")

    roi       = results.get("total_return_pct",   0.0)
    buy_hold  = results.get("buy_hold_pct",        0.0)
    win_rate  = results.get("win_rate",            0.0)
    pf        = results.get("profit_factor",       0.0)
    avg_win   = results.get("avg_win_pct",         0.0)
    avg_loss  = abs(results.get("avg_loss_pct",    0.0))
    max_dd    = abs(results.get("max_drawdown_pct", 0.0))
    n_trades  = results.get("total_trades",        0)
    sharpe    = results.get("sharpe_ratio",        0.0)
    sym_stats = results.get("symbol_stats",        {})
    dd_hist   = results.get("drawdown_history",    [])
    commission = setup_info.get("commission", 0.0)
    slippage   = setup_info.get("slippage",   0.0)

    rr = avg_win / avg_loss if avg_loss > 0 else 0

    # ── Data-source mode notice ───────────────────────────────────────────────
    if ds == "MONTE_CARLO":
        n_sims = setup_info.get("n_sims", 0)
        findings.append(("info",
            f"Monte Carlo simulation ({n_sims} paths) — results represent a median outcome. "
            f"Real-world performance may differ significantly."))
    elif ds == "RANDOM_WALK":
        drift = setup_info.get("drift", 0.0)
        vol   = setup_info.get("volatility", 0.0)
        findings.append(("info",
            f"Synthetic random walk (drift {drift:+.2f}%, vol {vol:.2f}%/bar) — "
            f"no real market microstructure. Treat as stress-test only."))
    else:
        start = setup_info.get("start_date", "")
        end   = setup_info.get("end_date", "") or "present"
        if start:
            findings.append(("info", f"Real Binance data ({start} → {end})."))

    # ── Cost impact warning ───────────────────────────────────────────────────
    if (commission + slippage) > 0 and n_trades > 50:
        total_cost_est = (commission + slippage) * 2 * n_trades
        findings.append(("info",
            f"Estimated round-trip cost drag: ~{total_cost_est:.1f}% across {n_trades} trades "
            f"({commission}% commission + {slippage}% slippage)."))

    # ── Return vs buy & hold (only meaningful for REAL data) ─────────────────
    if ds == "REAL":
        if roi > buy_hold + 5:
            findings.append(("ok",   f"Strategy outperforms buy-and-hold by {roi - buy_hold:.1f}%."))
        elif roi < buy_hold - 5 and buy_hold > 0:
            findings.append(("warn", f"Strategy underperforms buy-and-hold by {buy_hold - roi:.1f}%."))

    # ── Win rate vs profit factor tension ─────────────────────────────────────
    if win_rate > 65 and pf < 1.3:
        findings.append(("warn", "High win rate but low profit factor — many small wins offset by large losses."))
    elif win_rate < 45 and pf > 2.0:
        findings.append(("info", "Low win rate compensated by strong reward-risk ratio."))

    # ── R:R ratio ─────────────────────────────────────────────────────────────
    if rr < 1.2 and win_rate < 60:
        findings.append(("warn", f"Weak reward-risk ratio ({rr:.2f}:1) combined with a sub-60% win rate."))
    elif rr > 2.5:
        findings.append(("ok",   f"Strong reward-risk ratio ({rr:.2f}:1)."))

    # ── Drawdown ──────────────────────────────────────────────────────────────
    if max_dd > 30:
        findings.append(("warn", f"Severe max drawdown of {max_dd:.1f}% — significant capital exposure."))
    elif max_dd > 15:
        findings.append(("warn", f"Notable max drawdown of {max_dd:.1f}%."))
    elif max_dd < 8 and n_trades > 10:
        findings.append(("ok",   f"Well-controlled drawdown ({max_dd:.1f}%)."))

    # ── Drawdown clustering ───────────────────────────────────────────────────
    if len(dd_hist) > 20:
        clusters, cur = 0, 0
        for v in dd_hist:
            if v < -5:
                cur += 1
            else:
                if cur >= 10:
                    clusters += 1
                cur = 0
        if clusters >= 2:
            findings.append(("warn", f"Drawdown clusters detected ({clusters} prolonged dip periods)."))

    # ── Trade frequency ───────────────────────────────────────────────────────
    if n_trades > 250:
        findings.append(("warn", f"High trade count ({n_trades}) — overtrading risk; check commission impact."))
    elif n_trades < 10:
        findings.append(("warn", f"Very few trades ({n_trades}) — insufficient sample for reliable statistics."))

    # ── Sharpe quality ────────────────────────────────────────────────────────
    if sharpe > 1.8:
        findings.append(("ok",   f"Excellent risk-adjusted return (Sharpe {sharpe:.2f})."))
    elif sharpe < 0.5 and n_trades >= 10:
        findings.append(("warn", f"Low Sharpe ratio ({sharpe:.2f}) — returns poorly compensate for risk."))

    # ── Portfolio concentration ───────────────────────────────────────────────
    if sym_stats and n_trades > 0:
        most_traded = max(sym_stats.items(), key=lambda x: x[1]["trades"])
        sym_name, sym_data = most_traded
        conc_pct = sym_data["trades"] / n_trades * 100
        if conc_pct > 70:
            findings.append(("warn",
                f"Portfolio concentration: {sym_name.replace('USDT','')} accounts for {conc_pct:.0f}% of trades."))

    # ── Per-asset contribution ────────────────────────────────────────────────
    if sym_stats:
        losers = [s for s, d in sym_stats.items() if d["total_pct"] < -5 and d["trades"] >= 3]
        if losers:
            names = ", ".join(s.replace("USDT", "") for s in losers[:3])
            findings.append(("warn", f"Loss-generating assets: {names}."))
        winners = [s for s, d in sym_stats.items() if d["total_pct"] > 10]
        if winners:
            names = ", ".join(s.replace("USDT", "") for s in winners[:3])
            findings.append(("ok",   f"Strong contributors: {names}."))

    return findings


# ── Recommendations ───────────────────────────────────────────────────────────

def build_recommendations(
    scores: dict, patterns: list[tuple[str, str]], results: dict, setup_info: dict | None = None
) -> list[str]:
    mode = mode_from_setup(setup_info or results)
    if mode == MONTE_CARLO:
        return montecarlo_analyzer.build_recommendations(scores, patterns, results)
    if mode == RANDOM_WALK:
        return random_walk_analyzer.build_recommendations(scores, patterns, results)
    if mode == LIVE_TRADING:
        return live_trading_analyzer.build_recommendations(scores, patterns, results)

    recs: list[str] = []

    rr = (results.get("avg_win_pct", 0) /
          max(abs(results.get("avg_loss_pct", 1e-9)), 1e-9))
    pf       = results.get("profit_factor", 0.0)
    max_dd   = abs(results.get("max_drawdown_pct", 0.0))
    n_trades = results.get("total_trades", 0)
    sharpe   = results.get("sharpe_ratio", 0.0)

    if scores["efficiency"] < 50 and rr < 1.5:
        recs.append("Tighten take-profit targets or widen stop-loss to improve reward-risk ratio.")
    if scores["risk"] < 50 and max_dd > 20:
        recs.append("Reduce position size or add a max-drawdown circuit breaker.")
    if scores["consistency"] < 50 and pf < 1.3:
        recs.append("Review entry signals — profit factor below 1.3 suggests noisy entries.")
    if n_trades > 200:
        recs.append("Consider adding a trend filter to reduce overtrading and commission drag.")
    if n_trades < 15:
        recs.append("Expand the backtest window or loosen entry conditions to gather more trades.")
    if sharpe < 0.7 and scores["return"] > 50:
        recs.append("Returns exist but are highly volatile — consider volatility-based sizing.")
    if scores["portfolio"] < 50:
        recs.append("Diversify across more assets or rebalance allocation to reduce concentration risk.")
    if scores["overall"] >= 75:
        recs.append("Strong overall result — consider live paper-trading before deploying capital.")

    return recs[:5]  # cap at 5


# ── Ollama prompt builder ─────────────────────────────────────────────────────

def build_analysis_prompt(results: dict, trades: list, setup_info: dict) -> str:
    mode = mode_from_setup(setup_info or results)
    if mode == MONTE_CARLO:
        return montecarlo_analyzer.build_prompt(results, trades, setup_info)
    if mode == RANDOM_WALK:
        return random_walk_analyzer.build_prompt(results, trades, setup_info)
    if mode == LIVE_TRADING:
        return live_trading_analyzer.build_prompt(results, trades, setup_info)

    roi       = results.get("total_return_pct",    0.0)
    bh        = results.get("buy_hold_pct",         0.0)
    wr        = results.get("win_rate",             0.0)
    pf        = results.get("profit_factor",        0.0)
    sharpe    = results.get("sharpe_ratio",         0.0)
    sortino   = results.get("sortino_ratio",        0.0)
    max_dd    = abs(results.get("max_drawdown_pct", 0.0))
    calmar    = results.get("calmar_ratio",         0.0)
    n_t       = results.get("total_trades",         0)
    avg_h     = results.get("avg_hold_hours",       0.0)
    avg_t     = results.get("avg_trade_pct",        0.0)
    avg_w     = results.get("avg_win_pct",          0.0)
    avg_l     = results.get("avg_loss_pct",         0.0)

    strat      = setup_info.get("strategy", "Unknown").replace("_", " ").title()
    assets     = ", ".join(a.replace("USDT","") for a in setup_info.get("assets", [])[:5])
    iv         = setup_info.get("interval", "1h")
    balance    = setup_info.get("balance",   1000.0)
    budget     = setup_info.get("budget",    20.0)
    start      = setup_info.get("start_date", "")
    end        = setup_info.get("end_date",   "") or "present"
    ds         = setup_info.get("data_source", "REAL")
    commission = setup_info.get("commission",  0.0)
    slippage   = setup_info.get("slippage",    0.0)
    pyramiding = setup_info.get("pyramiding",  False)
    cooldown   = setup_info.get("cooldown",    0)
    n_sims     = setup_info.get("n_sims",      0)
    n_bars     = setup_info.get("n_bars",      0)
    drift      = setup_info.get("drift",       0.0)
    vol_s      = setup_info.get("volatility",  0.0)
    alloc      = setup_info.get("allocation",  {})

    # Mode line
    if ds == "MONTE_CARLO":
        mode_line = f"Mode: Monte Carlo ({n_sims} paths, {n_bars} bars, drift {drift:+.2f}%, vol {vol_s:.2f}%)"
    elif ds == "RANDOM_WALK":
        mode_line = f"Mode: Random Walk (GBM, {n_bars} bars, drift {drift:+.2f}%, vol {vol_s:.2f}%/bar)"
    else:
        mode_line = f"Mode: Real market data ({start} → {end})"

    # Allocation line
    alloc_line = ""
    if alloc and len(alloc) > 1:
        parts = [f"{a.replace('USDT','')}: {p:.0f}%" for a, p in list(alloc.items())[:5]]
        alloc_line = f"Allocation: {', '.join(parts)}\n"

    # Cost line
    cost_line = ""
    if commission > 0 or slippage > 0:
        cost_line = f"Costs: {commission}% commission, {slippage}% slippage\n"

    rr = avg_w / abs(avg_l) if avg_l else 0

    return (
        f"You are a quant trading analyst. Write 3 focused paragraphs of professional "
        f"post-backtest feedback. Plain text only, no markdown, no bullet points.\n\n"
        f"=== BACKTEST SETUP ===\n"
        f"Strategy: {strat}  Assets: {assets}  Interval: {iv}\n"
        f"{mode_line}\n"
        f"Capital: ${balance:,.0f}  Budget/trade: {budget}%"
        f"{'  Pyramiding: ON' if pyramiding else ''}"
        f"{'  Cooldown: ' + str(cooldown) + ' bars' if cooldown else ''}\n"
        f"{alloc_line}{cost_line}"
        f"\n=== PERFORMANCE RESULTS ===\n"
        f"ROI: {roi:+.1f}%  Buy&Hold: {bh:+.1f}%  WinRate: {wr:.1f}%  Trades: {n_t}\n"
        f"ProfitFactor: {pf:.2f}  Sharpe: {sharpe:.2f}  Sortino: {sortino:.2f}  Calmar: {calmar:.2f}\n"
        f"MaxDrawdown: -{max_dd:.1f}%  AvgTrade: {avg_t:+.2f}%  R:R: {rr:.2f}:1  AvgHold: {avg_h:.1f}h\n\n"
        f"Paragraph 1: Overall assessment. "
        f"Paragraph 2: Key strengths. "
        f"Paragraph 3: Main risks and concrete improvement suggestions."
    )


# ── Rich markup builders ──────────────────────────────────────────────────────

def _score_bar(score: int, width: int = 16) -> str:
    filled = int(round(score / 100 * width))
    empty  = width - filled
    bar    = "█" * filled + "░" * empty
    if score >= 70:   color = "green"
    elif score >= 45: color = "yellow"
    else:             color = "red"
    return f"[{color}]{bar}[/{color}]"


def _grade(score: int) -> str:
    if score >= 85:   return "[bold green]EXCELLENT[/bold green]"
    elif score >= 70: return "[green]GOOD[/green]"
    elif score >= 55: return "[yellow]FAIR[/yellow]"
    elif score >= 40: return "[red]WEAK[/red]"
    else:             return "[bold red]POOR[/bold red]"


def build_scores_markup(scores: dict, setup_info: dict | None = None) -> str:
    mode = mode_from_setup(setup_info)
    if mode == MONTE_CARLO:
        rows = [
            ("OVERALL", "overall"),
            ("OUTCOME", "outcome"),
            ("ROBUSTNESS", "robustness"),
            ("VARIANCE", "variance"),
            ("DRAWDOWN", "drawdown"),
            ("SAMPLE", "sample"),
        ]
    elif mode == RANDOM_WALK:
        rows = [
            ("OVERALL", "overall"),
            ("MOVEMENT", "movement"),
            ("RISK", "risk"),
            ("STOCHASTIC", "stochastic"),
            ("SIGNAL", "signal"),
            ("SAMPLE", "sample"),
        ]
    elif mode == LIVE_TRADING:
        rows = [
            ("OVERALL", "overall"),
            ("EXECUTION", "execution"),
            ("EXPOSURE", "exposure"),
            ("PNL", "pnl"),
            ("RISK", "risk"),
        ]
    else:
        rows = [
            ("OVERALL",     "overall"),
            ("RETURN",      "return"),
            ("RISK",        "risk"),
            ("CONSISTENCY", "consistency"),
            ("EFFICIENCY",  "efficiency"),
            ("PORTFOLIO",   "portfolio"),
        ]
    lines = ["[bold dim]── SCORECARD ──────────────────────────────[/bold dim]"]
    for label, key in rows:
        s   = scores.get(key, 0)
        bar = _score_bar(s)
        grade = _grade(s) if key == "overall" else f"[dim]{s:3d}[/dim]"
        lines.append(f" [dim]{label:<13}[/dim] {bar} {grade}")
    return "\n".join(lines)


def build_full_markup(
    results:       dict,
    trades:        list,
    setup_info:    dict,
    patterns:      list[tuple[str, str]],
    recs:          list[str],
    enhanced_text: str = "",
) -> str:
    lines: list[str] = []

    # ── Context header ────────────────────────────────────────────────────────
    ds      = setup_info.get("data_source", "REAL")
    mode    = mode_from_setup(setup_info or results)
    strat   = setup_info.get("strategy", "").replace("_", " ").title()
    assets  = [a.replace("USDT","") for a in setup_info.get("assets", [])]
    iv      = setup_info.get("interval", "")
    balance = setup_info.get("balance", 0.0)
    budget  = setup_info.get("budget",  0.0)
    start   = setup_info.get("start_date", "")
    end     = setup_info.get("end_date",   "") or "present"
    comm    = setup_info.get("commission", 0.0)
    slip    = setup_info.get("slippage",   0.0)
    n_sims  = setup_info.get("n_sims",     0)
    n_bars  = setup_info.get("n_bars",     0)
    drift   = setup_info.get("drift",      0.0)
    vol_s   = setup_info.get("volatility", 0.0)

    if mode == MONTE_CARLO:
        mode_tag = f"[bold yellow]MONTE CARLO[/bold yellow] [dim]{n_sims} paths · {n_bars} bars · drift {drift:+.2f}% · vol {vol_s:.2f}%[/dim]"
    elif mode == RANDOM_WALK:
        mode_tag = f"[bold cyan]RANDOM WALK[/bold cyan] [dim]{n_bars} bars · drift {drift:+.2f}% · vol {vol_s:.2f}%/bar[/dim]"
    elif mode == LIVE_TRADING:
        mode_tag = "[bold magenta]LIVE TRADING[/bold magenta] [dim]broker/execution data[/dim]"
    else:
        mode_tag = f"[bold green]REAL DATA[/bold green] [dim]{start} → {end}[/dim]"

    asset_str = ", ".join(assets[:5]) + (f" +{len(assets)-5}" if len(assets) > 5 else "")
    cost_str  = f"  [dim]fees {comm}%+{slip}%[/dim]" if (comm + slip) > 0 else ""

    lines += [
        "[bold dim]── CONTEXT ──────────────────────────────────[/bold dim]",
        f" {mode_tag}",
        f" [dim]Strategy[/dim]  {strat}   [dim]Interval[/dim] {iv}",
    ]
    if mode == MONTE_CARLO:
        lines.append(f" [dim]Simulation[/dim] {n_sims} probabilistic paths, {n_bars} bars per path")
        lines.append(f" [dim]Capital basis[/dim] ${balance:,.0f}   [dim]Budget rule[/dim] {budget}%{cost_str}")
    elif mode == RANDOM_WALK:
        lines.append(f" [dim]Synthetic model[/dim] {n_bars} bars, drift {drift:+.2f}%, volatility {vol_s:.2f}%")
        lines.append(f" [dim]Capital basis[/dim] ${balance:,.0f}   [dim]Budget rule[/dim] {budget}%{cost_str}")
    elif mode == LIVE_TRADING:
        lines.append(" [dim]Live execution data required[/dim]")
    else:
        lines.append(f" [dim]Assets[/dim]    {asset_str}")
        lines.append(f" [dim]Capital[/dim]   ${balance:,.0f}   [dim]Budget/trade[/dim] {budget}%{cost_str}")
    lines.append("")

    # ── Observations ──────────────────────────────────────────────────────────
    if patterns:
        lines.append("[bold dim]── OBSERVATIONS ────────────────────────────[/bold dim]")
        for severity, msg in patterns:
            if severity == "ok":
                lines.append(f" [green]✓[/green] {msg}")
            elif severity == "warn":
                lines.append(f" [yellow]⚠[/yellow] {msg}")
            else:
                lines.append(f" [cyan]ℹ[/cyan] {msg}")
        lines.append("")

    # ── AI analysis ───────────────────────────────────────────────────────────
    if enhanced_text.strip():
        lines.append("[bold dim]── AI ANALYSIS ─────────────────────────────[/bold dim]")
        lines.append(enhanced_text.strip())
        lines.append("")

    # ── Recommendations ───────────────────────────────────────────────────────
    if recs:
        lines.append("[bold dim]── RECOMMENDATIONS ─────────────────────────[/bold dim]")
        for r in recs:
            lines.append(f" [cyan]→[/cyan] {r}")
        lines.append("")

    # ── Key metrics summary ───────────────────────────────────────────────────
    lines.append("[bold dim]── KEY METRICS ──────────────────────────────[/bold dim]")
    roi    = results.get("total_return_pct",    0.0)
    bh     = results.get("buy_hold_pct",         0.0)
    wr     = results.get("win_rate",             0.0)
    pf     = results.get("profit_factor",        0.0)
    sh     = results.get("sharpe_ratio",         0.0)
    so     = results.get("sortino_ratio",        0.0)
    dd     = abs(results.get("max_drawdown_pct", 0.0))
    n_t    = results.get("total_trades",         0)
    avg_h  = results.get("avg_hold_hours",       0.0)
    avg_t  = results.get("avg_trade_pct",        0.0)
    avg_w  = results.get("avg_win_pct",          0.0)
    avg_l  = results.get("avg_loss_pct",         0.0)
    cal    = results.get("calmar_ratio",         0.0)
    hold_s = f"{avg_h:.1f}h" if avg_h < 48 else f"{avg_h/24:.1f}d"
    rr     = avg_w / abs(avg_l) if avg_l else 0

    rc = "green" if roi >= 0 else "red"
    wc = "green" if wr  >= 50 else "red"

    if mode == MONTE_CARLO:
        dist = results.get("simulation_distribution", {})
        lines += [
            f" [dim]{'Median Return':<20}[/dim][{rc}]{dist.get('median_return_pct', roi):+.2f}%[/{rc}]   [dim]P(Positive)[/dim] {dist.get('probability_positive_pct', wr):.1f}%",
            f" [dim]{'P05 / P95':<20}[/dim]{dist.get('p05_return_pct', 0.0):+.2f}% / {dist.get('p95_return_pct', 0.0):+.2f}%",
            f" [dim]{'Return Std Dev':<20}[/dim]{dist.get('std_return_pct', 0.0):.2f}%   [dim]Valid Paths[/dim] {dist.get('valid_paths', n_t)}",
            f" [dim]{'Median Drawdown':<20}[/dim]{dist.get('median_max_drawdown_pct', results.get('max_drawdown_pct', 0.0)):.2f}%",
        ]
    elif mode == RANDOM_WALK:
        lines += [
            f" [dim]{'Synthetic Return':<20}[/dim][{rc}]{roi:+.2f}%[/{rc}]   [dim]Synthetic Events[/dim] {n_t}",
            f" [dim]{'Profit Factor':<20}[/dim]{pf:.2f}   [dim]Sharpe-like[/dim] {sh:.2f}",
            f" [dim]{'Path Drawdown':<20}[/dim][red]-{dd:.2f}%[/red]   [dim]Avg Hold[/dim] {hold_s}",
            f" [dim]{'Avg Event':<20}[/dim]{avg_t:+.2f}%   [dim]R:R[/dim] {rr:.2f}:1",
        ]
    else:
        lines += [
            f" [dim]{'ROI':<20}[/dim][{rc}]{roi:+.2f}%[/{rc}]   [dim]Buy & Hold[/dim] {bh:+.2f}%",
            f" [dim]{'Win Rate':<20}[/dim][{wc}]{wr:.1f}%[/{wc}]   [dim]Profit Factor[/dim] {pf:.2f}",
            f" [dim]{'Sharpe':<20}[/dim]{sh:.2f}   [dim]Sortino[/dim] {so:.2f}",
            f" [dim]{'Max Drawdown':<20}[/dim][red]-{dd:.2f}%[/red]   [dim]Calmar[/dim] {cal:.2f}",
            f" [dim]{'Reward:Risk':<20}[/dim]{rr:.2f}:1   [dim]Avg Trade[/dim] {avg_t:+.2f}%",
            f" [dim]{'Trades':<20}[/dim]{n_t}   [dim]Avg Hold[/dim] {hold_s}",
        ]

    return "\n".join(lines)
