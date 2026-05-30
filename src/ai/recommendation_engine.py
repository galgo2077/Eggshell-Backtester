from __future__ import annotations
from analysis.modes import MONTE_CARLO, RANDOM_WALK, LIVE_TRADING, mode_from_setup
from analysis.montecarlo import analyzer as montecarlo_analyzer
from analysis.random_walk import analyzer as random_walk_analyzer
from analysis.live_trading import analyzer as live_trading_analyzer

def build_setup_recommendations(setup_risks: list) -> list[str]:
    """Generates recommendations based purely on the pre-execution setup."""
    recs = []
    setup_warns = [msg for sev, msg in setup_risks if sev == "warn"]
    setup_infos = [msg for sev, msg in setup_risks if sev == "info"]
    
    if any("aggressive" in msg.lower() for msg in setup_warns):
        recs.append("Reduce risk per trade to lower drawdown exposure.")
        
    if any("zero diversification" in msg.lower() for msg in setup_warns) or any("low diversification" in msg.lower() for msg in setup_infos):
        recs.append("Increase diversification by adding uncorrelated assets.")
        
    if any("high volatility" in msg.lower() for msg in setup_warns):
        recs.append("Lower the volatility assumption for a more realistic baseline.")
        
    if any("zero fees" in msg.lower() for msg in setup_warns):
        recs.append("Configure realistic fees and slippage to ensure accurate backtesting.")
        
    return recs[:5]

def build_result_recommendations(
    scores: dict, patterns: list[tuple[str, str]], results: dict, setup_info: dict | None = None
) -> list[str]:
    """Migrated post-execution recommendations."""
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

    if scores.get("efficiency", 100) < 50 and rr < 1.5:
        recs.append("Tighten take-profit targets or widen stop-loss to improve reward-risk ratio.")
    if scores.get("risk", 100) < 50 and max_dd > 20:
        recs.append("Reduce position size or add a max-drawdown circuit breaker.")
    if scores.get("consistency", 100) < 50 and pf < 1.3:
        recs.append("Review entry signals — profit factor below 1.3 suggests noisy entries.")
    if n_trades > 200:
        recs.append("Consider adding a trend filter to reduce overtrading and commission drag.")
    if n_trades < 15:
        recs.append("Expand the backtest window or loosen entry conditions to gather more trades.")
    if sharpe < 0.7 and scores.get("return", 0) > 50:
        recs.append("Returns exist but are highly volatile — consider volatility-based sizing.")
    if scores.get("portfolio", 100) < 50:
        recs.append("Diversify across more assets or rebalance allocation to reduce concentration risk.")
    if scores.get("overall", 0) >= 75:
        recs.append("Strong overall result — consider live paper-trading before deploying capital.")

    return recs[:5]
