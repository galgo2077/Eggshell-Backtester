from __future__ import annotations
from analysis.modes import mode_from_setup, MONTE_CARLO, RANDOM_WALK, LIVE_TRADING
from .scoring_engine import compute_setup_scores

class AIStrategySetupAnalyzer:
    @staticmethod
    def analyze(setup_info: dict) -> dict:
        """
        Analyzes the strategy setup before execution.
        Returns a dict containing:
        - scores: Setup quality scores
        - risks: List of tuples (severity, message)
        - mode: Execution mode
        """
        mode = mode_from_setup(setup_info)
        scores = compute_setup_scores(setup_info)
        risks = []
        
        budget = setup_info.get("budget", 20.0)
        assets = setup_info.get("assets", [])
        alloc = setup_info.get("allocation", {})
        
        # Mode-specific analysis
        if mode == MONTE_CARLO:
            n_sims = setup_info.get("n_sims", 50)
            n_bars = setup_info.get("n_bars", 1000)
            if n_sims < 100:
                risks.append(("warn", f"Monte Carlo simulation uses {n_sims} paths, which may be statistically insufficient. Consider >= 100."))
            if n_bars < 1000:
                risks.append(("warn", f"Monte Carlo simulation runs for only {n_bars} bars per path, reducing long-term stability confidence."))
        elif mode == RANDOM_WALK:
            drift = setup_info.get("drift", 0.05)
            vol = setup_info.get("volatility", 2.0)
            if vol > 5.0:
                risks.append(("warn", f"High volatility assumption ({vol}%). This synthetic environment represents extreme market stress."))
            if drift > 1.0:
                risks.append(("warn", f"Unusually high positive drift ({drift}%). This may mask poor strategy logic in a bull run."))
            
        # General Analysis
        if budget > 25:
            risks.append(("warn", f"Risk per trade is very aggressive ({budget}%). Drawdown risk is extremely high."))
        elif budget > 10:
            risks.append(("warn", f"Risk per trade ({budget}%) may cause large drawdowns under adverse conditions."))
            
        if len(assets) == 1:
            risks.append(("warn", f"Zero diversification. Portfolio is entirely exposed to {assets[0]}."))
        elif len(assets) < 3:
            risks.append(("info", "Low diversification. Consider adding more uncorrelated assets to reduce exposure concentration."))
            
        # Advanced param checks
        adv_params = setup_info.get("adv_params", {})
        strat_name = adv_params.get("STRATEGY", "")
        if strat_name == "DUAL_STRATEGY":
            risks.append(("info", "Dual Strategy selected. Ensure Strategy A and Strategy B use complementary, non-conflicting logic."))
        
        # VBT checks
        vbt_params = setup_info.get("vbt_params", {})
        if vbt_params.get("fees", 0) == 0 and vbt_params.get("slippage", 0) == 0 and mode not in [MONTE_CARLO, RANDOM_WALK]:
            risks.append(("warn", "Zero fees and slippage configured. Real-market backtest will be unrealistically optimistic."))
            
        return {
            "scores": scores,
            "risks": risks,
            "mode": mode
        }
