from __future__ import annotations
import threading
from .setup_analyzer import AIStrategySetupAnalyzer
from .result_analyzer import detect_result_patterns, link_setup_to_results
from .scoring_engine import compute_result_scores
from .recommendation_engine import build_setup_recommendations, build_result_recommendations
from analysis.modes import mode_from_setup, MONTE_CARLO, RANDOM_WALK, LIVE_TRADING

# Import the prompt builders and markup tools originally in ai_analyzer
from analysis.montecarlo import analyzer as montecarlo_analyzer
from analysis.random_walk import analyzer as random_walk_analyzer
from analysis.live_trading import analyzer as live_trading_analyzer

class AIAnalysisOrchestrator:
    @staticmethod
    def analyze_setup(setup_info: dict) -> dict:
        """Runs the PRE-EXECUTION analysis phase."""
        return AIStrategySetupAnalyzer.analyze(setup_info)

    @staticmethod
    def analyze_results(results: dict, trades: list, setup_info: dict) -> dict:
        """Runs the POST-EXECUTION analysis phase."""
        scores = compute_result_scores(results, trades, setup_info)
        patterns = detect_result_patterns(results, trades, setup_info)
        recs = build_result_recommendations(scores, patterns, results, setup_info)
        return {
            "scores": scores,
            "patterns": patterns,
            "recommendations": recs
        }

    @staticmethod
    def generate_combined_feedback(setup_risks: list, result_patterns: list) -> list[tuple[str, str]]:
        """Connects setup decisions to execution outcomes."""
        return link_setup_to_results(setup_risks, result_patterns)

    # ── Ollama prompt builder ─────────────────────────────────────────────────────
    @staticmethod
    def build_setup_prompt(setup_info: dict) -> str:
        strat       = setup_info.get("strategy", "Unknown").replace("_", " ").title()
        assets      = ", ".join(a.replace("USDT","") for a in setup_info.get("assets", [])[:8]) or "none selected"
        iv          = setup_info.get("interval", "1h")
        balance     = setup_info.get("balance",      1000.0)
        budget      = setup_info.get("budget",        20.0)
        ds          = setup_info.get("data_source",  "REAL")
        cooldown    = setup_info.get("cooldown",       0)
        pyramiding  = setup_info.get("pyramiding",    False)
        cash_share  = setup_info.get("cash_sharing",  False)
        sell_end    = setup_info.get("sell_at_end",   False)
        commission  = setup_info.get("commission",     0.0)
        slippage    = setup_info.get("slippage",       0.0)
        start       = setup_info.get("start_date",    "")
        end         = setup_info.get("end_date",      "") or "present"
        n_sims      = setup_info.get("n_sims",         0)
        n_bars      = setup_info.get("n_bars",         0)
        drift       = setup_info.get("drift",          0.0)
        vol_s       = setup_info.get("volatility",     0.0)

        # Strategy-specific params
        adv = setup_info.get("adv_params", {})
        strat_params = {
            k: v for k, v in adv.items()
            if k not in ("STRATEGY", "STRATEGY_A", "STRATEGY_B", "PARAMS_A", "PARAMS_B")
            and not callable(v)
        }
        params_lines = "\n".join(f"  {k}: {v}" for k, v in list(strat_params.items())[:20])

        if ds == "MONTE_CARLO":
            data_ctx = f"Mode: Monte Carlo simulation ({n_sims} paths, {n_bars} bars per path, drift {drift:+.2f}%, vol {vol_s:.2f}%)"
        elif ds == "RANDOM_WALK":
            data_ctx = f"Mode: Random Walk (GBM, {n_bars} bars, drift {drift:+.2f}%, vol {vol_s:.2f}%/bar)"
        else:
            data_ctx = f"Mode: Real market data ({start} to {end})"

        alloc = setup_info.get("allocation", {})
        alloc_str = "  ".join(f"{a.replace('USDT','')}: {p:.0f}%" for a, p in list(alloc.items())[:6]) if len(alloc) > 1 else ""

        return (
            f"You are an expert quantitative trading mentor teaching a student about their backtest configuration.\n\n"
            f"=== CURRENT SETUP ===\n"
            f"Strategy: {strat}\n"
            f"Assets: {assets}\n"
            f"Timeframe: {iv}\n"
            f"Capital: ${balance:,.0f}  Budget per trade: {budget}%\n"
            f"Pyramiding: {'ON' if pyramiding else 'OFF'}  "
            f"Cooldown: {cooldown} bars  "
            f"Cash sharing: {'ON' if cash_share else 'OFF'}  "
            f"Sell at end: {'ON' if sell_end else 'OFF'}\n"
            f"Commission: {commission}%  Slippage: {slippage}%\n"
            f"{data_ctx}\n"
            + (f"Allocation: {alloc_str}\n" if alloc_str else "")
            + (f"Strategy parameters:\n{params_lines}\n" if params_lines else "")
            + f"\n=== TEACHING TASK ===\n"
            f"Write a deep educational explanation of this setup as if teaching a new trader. "
            f"Cover ALL of the following in plain text paragraphs:\n\n"
            f"PART 1 — STRATEGY MECHANICS: Explain exactly how {strat} works. What triggers entries? "
            f"What triggers exits? What price signals drive the logic? How is it different from simpler strategies?\n\n"
            f"PART 2 — PARAMETER DEEP DIVE: For each key parameter above explain what it does, "
            f"why it was set to this value, and what happens if you increase or decrease it. "
            f"For example: what does {budget}% budget per trade mean for drawdown risk? "
            f"What does {cooldown}-bar cooldown prevent? How does pyramiding affect compound returns?\n\n"
            f"PART 3 — MARKET CONDITIONS: Describe exactly which market environments this strategy performs best in. "
            f"Describe exactly when it will lose money. Be specific: trending vs ranging, "
            f"high volatility vs low volatility, bull vs bear.\n\n"
            f"PART 4 — EXPECTED TRADE BEHAVIOR: What should the student expect to see in the results? "
            f"Typical win rate range? Expected drawdown profile? Trade frequency? "
            f"Average hold duration? Any characteristic patterns in the equity curve?\n\n"
            f"PART 5 — RISK PROFILE: What are the realistic best-case and worst-case outcomes for this setup? "
            f"What is the key risk that could blow up this configuration?\n\n"
            f"Plain text only. No markdown. No bullet points. Write in clear teaching paragraphs."
        )

    @staticmethod
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

        # Strategy-specific params for context
        adv = setup_info.get("adv_params", {})
        strat_params = {
            k: v for k, v in adv.items()
            if k not in ("STRATEGY", "STRATEGY_A", "STRATEGY_B", "PARAMS_A", "PARAMS_B")
            and not callable(v)
        }
        params_ctx = "  ".join(f"{k}={v}" for k, v in list(strat_params.items())[:12])

        sym_stats = results.get("symbol_stats", {})
        sym_lines = ""
        if sym_stats:
            sym_parts = [
                f"{s.replace('USDT','')}: {d.get('total_pct', 0.0):+.1f}% ({d.get('trades', 0)} trades)"
                for s, d in list(sym_stats.items())[:6]
            ]
            sym_lines = f"Per-asset: {', '.join(sym_parts)}\n"

        return (
            f"You are a senior quantitative analyst writing a professional post-backtest report for a student. "
            f"Plain text only. No markdown. No bullet points.\n\n"
            f"=== BACKTEST CONFIGURATION ===\n"
            f"Strategy: {strat}  Assets: {assets}  Timeframe: {iv}\n"
            f"{mode_line}\n"
            f"Capital: ${balance:,.0f}  Budget/trade: {budget}%"
            f"{'  Pyramiding: ON' if pyramiding else ''}"
            f"{'  Cooldown: ' + str(cooldown) + ' bars' if cooldown else ''}\n"
            f"{alloc_line}{cost_line}"
            + (f"Strategy params: {params_ctx}\n" if params_ctx else "")
            + f"\n=== PERFORMANCE RESULTS ===\n"
            f"ROI: {roi:+.1f}%  Buy&Hold: {bh:+.1f}%  WinRate: {wr:.1f}%  Trades: {n_t}\n"
            f"ProfitFactor: {pf:.2f}  Sharpe: {sharpe:.2f}  Sortino: {sortino:.2f}  Calmar: {calmar:.2f}\n"
            f"MaxDrawdown: -{max_dd:.1f}%  AvgTrade: {avg_t:+.2f}%  R:R: {rr:.2f}:1  AvgHold: {avg_h:.1f}h\n"
            f"AvgWin: {avg_w:+.2f}%  AvgLoss: {avg_l:+.2f}%\n"
            f"{sym_lines}"
            f"\n=== REPORT SECTIONS — write each as a labelled paragraph ===\n\n"
            f"OVERALL ASSESSMENT: Was this backtest successful? Compare ROI of {roi:+.1f}% against buy-and-hold of {bh:+.1f}%. "
            f"Is a {wr:.0f}% win rate and {pf:.2f} profit factor acceptable for this strategy type? "
            f"Give a clear verdict on whether this configuration should be taken forward.\n\n"
            f"STRENGTHS: Identify what genuinely worked. Reference specific numbers. "
            f"For example: drawdown control, trade consistency, Sharpe quality, win/loss ratio.\n\n"
            f"WEAKNESSES: Identify what failed. Be direct. "
            f"Was the strategy overtrading? Were losses concentrated? "
            f"Did the risk sizing cause unnecessary drawdown? Were exits too late or too early?\n\n"
            f"EXPECTED VS OBSERVED: Based on the theoretical behavior of {strat}, "
            f"describe what a well-functioning version of this strategy should produce "
            f"(typical win rate, drawdown profile, trade frequency, R:R ratio). "
            f"Then compare this to what actually occurred. Identify the specific deviations. "
            f"Did the strategy behave as theoretically predicted? If not, what broke?\n\n"
            f"PARAMETER IMPACT: Which specific parameters contributed to the outcome? "
            f"Was {budget}% budget appropriate given the {max_dd:.1f}% drawdown? "
            f"Was cooldown of {cooldown} bars useful given {n_t} trades over the period? "
            f"What parameter change would have the biggest positive effect?\n\n"
            f"IMPROVEMENT OPPORTUNITIES: List exactly 4 specific changes ranked HIGH/MEDIUM/LOW by expected impact. "
            f"For each: state the parameter, the suggested new value, and the reason why. "
            f"Be quantitative and specific. End with which single change would have the largest impact if only one change were allowed."
        )

    # ── Rich markup builders ──────────────────────────────────────────────────────
    @staticmethod
    def _score_bar(score: int, width: int = 16) -> str:
        filled = int(round(score / 100 * width))
        empty  = width - filled
        bar    = "█" * filled + "░" * empty
        if score >= 70:   color = "green"
        elif score >= 45: color = "yellow"
        else:             color = "red"
        return f"[{color}]{bar}[/{color}]"

    @staticmethod
    def _grade(score: int) -> str:
        if score >= 85:   return "[bold green]EXCELLENT[/bold green]"
        elif score >= 70: return "[green]GOOD[/green]"
        elif score >= 55: return "[yellow]FAIR[/yellow]"
        elif score >= 40: return "[red]WEAK[/red]"
        else:             return "[bold red]POOR[/bold red]"

    @classmethod
    def build_scores_markup(cls, scores: dict, setup_info: dict | None = None, is_setup: bool = False) -> str:
        if is_setup:
            rows = [
                ("OVERALL", "overall"),
                ("STABILITY", "stability"),
                ("RISK QUALITY", "risk_quality"),
                ("PORTFOLIO", "portfolio"),
                ("DIVERSIFY", "diversification"),
                ("REALISM", "realism"),
            ]
        else:
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
            bar = cls._score_bar(s)
            grade = cls._grade(s) if key == "overall" else f"[dim]{s:3d}[/dim]"
            lines.append(f" [dim]{label:<13}[/dim] {bar} {grade}")
        return "\n".join(lines)

    @classmethod
    def build_full_markup(
        cls,
        results:       dict,
        trades:        list,
        setup_info:    dict,
        patterns:      list[tuple[str, str]],
        recs:          list[str],
        enhanced_text: str = "",
        is_setup: bool = False,
        combined_feedback: list[tuple[str, str]] = None
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

        # ── AI analysis ───────────────────────────────────────────────────────────
        if enhanced_text.strip():
            lines.append("[bold dim]── AI ANALYSIS ─────────────────────────────[/bold dim]")
            lines.append(enhanced_text.strip())
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

        # ── Combined Insights (Setup -> Outcome) ──────────────────────────────────
        if combined_feedback:
            lines.append("[bold dim]── COMBINED INSIGHTS ───────────────────────[/bold dim]")
            for severity, msg in combined_feedback:
                if severity == "warn":
                    lines.append(f" [red]→[/red] {msg}")
                else:
                    lines.append(f" [cyan]→[/cyan] {msg}")
            lines.append("")

        # ── Recommendations ───────────────────────────────────────────────────────
        if recs:
            lines.append("[bold dim]── RECOMMENDATIONS ─────────────────────────[/bold dim]")
            for r in recs:
                lines.append(f" [cyan]→[/cyan] {r}")
            lines.append("")

        if is_setup:
            return "\n".join(lines)

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
