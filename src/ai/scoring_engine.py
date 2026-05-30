from __future__ import annotations
from analysis.modes import MONTE_CARLO, RANDOM_WALK, LIVE_TRADING, mode_from_setup
from analysis.montecarlo import analyzer as montecarlo_analyzer
from analysis.random_walk import analyzer as random_walk_analyzer
from analysis.live_trading import analyzer as live_trading_analyzer

def compute_setup_scores(setup_info: dict) -> dict[str, int]:
    """Computes pre-execution setup quality scores."""
    mode = mode_from_setup(setup_info)
    
    # Defaults
    stability = 50
    risk_quality = 50
    portfolio_structure = 50
    diversification = 50
    realism = 50
    
    ds = setup_info.get("data_source", "REAL")
    budget = setup_info.get("budget", 20.0)
    assets = setup_info.get("assets", [])
    alloc = setup_info.get("allocation", {})
    cooldown = setup_info.get("cooldown", 0)
    
    # Portfolio & Diversification
    n_assets = len(assets)
    if n_assets >= 5:
        diversification = 90
        portfolio_structure = 85
    elif n_assets >= 3:
        diversification = 70
        portfolio_structure = 75
    elif n_assets >= 2:
        diversification = 50
        portfolio_structure = 55
    else:
        diversification = 20
        portfolio_structure = 30
        
    # Risk Quality
    if budget <= 5:
        risk_quality = 95
    elif budget <= 10:
        risk_quality = 85
    elif budget <= 25:
        risk_quality = 65
    elif budget <= 50:
        risk_quality = 40
    else:
        risk_quality = 15
        
    # Realism & Stability
    if ds == "REAL":
        realism = 90
        if cooldown > 0:
            realism = min(100, realism + 10)
    elif ds == "MONTE_CARLO":
        n_sims = setup_info.get("n_sims", 50)
        n_bars = setup_info.get("n_bars", 1000)
        if n_sims >= 100 and n_bars >= 2000:
            stability = 95
            realism = 80
        elif n_sims >= 50:
            stability = 75
            realism = 60
        else:
            stability = 40
            realism = 40
    elif ds == "RANDOM_WALK":
        realism = 20
        stability = 50
        
    overall = int(0.2 * stability + 0.3 * risk_quality + 0.2 * portfolio_structure + 0.15 * diversification + 0.15 * realism)

    return {
        "overall": min(100, max(0, overall)),
        "stability": min(100, max(0, stability)),
        "risk_quality": min(100, max(0, risk_quality)),
        "portfolio": min(100, max(0, portfolio_structure)),
        "diversification": min(100, max(0, diversification)),
        "realism": min(100, max(0, realism)),
    }

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

    # Return score
    if roi > 30:   ret = 95
    elif roi > 20: ret = 82
    elif roi > 10: ret = 68
    elif roi > 5:  ret = 52
    elif roi > 0:  ret = 36
    elif roi > -5: ret = 18
    else:          ret = 5
    if roi > buy_hold + 5:  ret = min(100, ret + 12)
    elif roi < buy_hold - 5: ret = max(0,   ret - 12)

    # Risk score
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

    # Consistency score
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

    # Efficiency score
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

    # Portfolio score
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

def compute_result_scores(results: dict, trades: list, setup_info: dict | None = None) -> dict[str, int]:
    mode = mode_from_setup(setup_info or results)
    if mode == MONTE_CARLO:
        return montecarlo_analyzer.compute_scores(results, trades)
    if mode == RANDOM_WALK:
        return random_walk_analyzer.compute_scores(results, trades)
    if mode == LIVE_TRADING:
        return live_trading_analyzer.compute_scores(results, trades)
    return _compute_real_market_scores(results, trades)
