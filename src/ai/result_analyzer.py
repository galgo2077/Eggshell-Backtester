from __future__ import annotations
from analysis.modes import MONTE_CARLO, RANDOM_WALK, LIVE_TRADING, mode_from_setup
from analysis.montecarlo import analyzer as montecarlo_analyzer
from analysis.random_walk import analyzer as random_walk_analyzer
from analysis.live_trading import analyzer as live_trading_analyzer

def detect_result_patterns(
    results: dict, trades: list, setup_info: dict | None = None
) -> list[tuple[str, str]]:
    """Returns list of (severity, message) based on execution outcomes."""
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

    if (commission + slippage) > 0 and n_trades > 50:
        total_cost_est = (commission + slippage) * 2 * n_trades
        findings.append(("info",
            f"Estimated round-trip cost drag: ~{total_cost_est:.1f}% across {n_trades} trades "
            f"({commission}% commission + {slippage}% slippage)."))

    if ds == "REAL":
        if roi > buy_hold + 5:
            findings.append(("ok",   f"Strategy outperforms buy-and-hold by {roi - buy_hold:.1f}%."))
        elif roi < buy_hold - 5 and buy_hold > 0:
            findings.append(("warn", f"Strategy underperforms buy-and-hold by {buy_hold - roi:.1f}%."))

    if win_rate > 65 and pf < 1.3:
        findings.append(("warn", "High win rate but low profit factor — many small wins offset by large losses."))
    elif win_rate < 45 and pf > 2.0:
        findings.append(("info", "Low win rate compensated by strong reward-risk ratio."))

    if rr < 1.2 and win_rate < 60:
        findings.append(("warn", f"Weak reward-risk ratio ({rr:.2f}:1) combined with a sub-60% win rate."))
    elif rr > 2.5:
        findings.append(("ok",   f"Strong reward-risk ratio ({rr:.2f}:1)."))

    if max_dd > 30:
        findings.append(("warn", f"Severe max drawdown of {max_dd:.1f}% — significant capital exposure."))
    elif max_dd > 15:
        findings.append(("warn", f"Notable max drawdown of {max_dd:.1f}%."))
    elif max_dd < 8 and n_trades > 10:
        findings.append(("ok",   f"Well-controlled drawdown ({max_dd:.1f}%)."))

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

    if n_trades > 250:
        findings.append(("warn", f"High trade count ({n_trades}) — overtrading risk; check commission impact."))
    elif n_trades < 10:
        findings.append(("warn", f"Very few trades ({n_trades}) — insufficient sample for reliable statistics."))

    if sharpe > 1.8:
        findings.append(("ok",   f"Excellent risk-adjusted return (Sharpe {sharpe:.2f})."))
    elif sharpe < 0.5 and n_trades >= 10:
        findings.append(("warn", f"Low Sharpe ratio ({sharpe:.2f}) — returns poorly compensate for risk."))

    if sym_stats and n_trades > 0:
        most_traded = max(sym_stats.items(), key=lambda x: x[1]["trades"])
        sym_name, sym_data = most_traded
        conc_pct = sym_data["trades"] / n_trades * 100
        if conc_pct > 70:
            findings.append(("warn",
                f"Portfolio concentration: {sym_name.replace('USDT','')} accounts for {conc_pct:.0f}% of trades."))

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

def link_setup_to_results(setup_risks: list, result_patterns: list) -> list[tuple[str, str]]:
    """Links pre-execution setup risks to post-execution results."""
    linked = []
    
    # E.g. If budget was high (setup risk) and max_dd was high (result pattern)
    setup_warns = [msg for sev, msg in setup_risks if sev == "warn"]
    result_warns = [msg for sev, msg in result_patterns if sev == "warn"]
    
    if any("aggressive" in msg.lower() for msg in setup_warns) and any("drawdown" in msg.lower() for msg in result_warns):
        linked.append(("warn", "The aggressive risk settings detected during setup analysis directly contributed to the large drawdowns observed."))
        
    if any("concentration" in msg.lower() for msg in setup_warns) and any("concentration" in msg.lower() for msg in result_warns):
        linked.append(("warn", "The lack of diversification noted before execution resulted in significant portfolio concentration in the backtest."))
        
    return linked
