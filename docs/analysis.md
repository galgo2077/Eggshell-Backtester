# Eggshell Backtester Prober v1.2 - Python File Analysis
<!-- Updated: 2026-05-28 -->

---

## `main.py`

**What:** Application entry point. Runs the Textual TUI by default or the legacy Rich CLI with `--cli`.

**How:** Clears `reports/errors/error.log`, then either calls `BacktestApp().run()` or executes the prompt-driven CLI pipeline: `Dataframe -> SignalLogic -> BacktestEngine`.

**Why:** Keeps the interactive terminal app and scriptable CLI in one launcher while preserving shared backtest behavior.

**Key imports:** `rich`, `binance_service.dataframe.Dataframe`, `core.signal_logic.SignalLogic`, `core.backtest_engine.BacktestEngine`, `ui.tui.BacktestApp`

---

## `ui/tui/composer.py`

**What:** Main Textual app orchestrator (`BacktestApp`). Owns layout, settings persistence, run execution, save/load, chart launching, mode-aware UI switching, and AI analysis refresh.

**How:** Builds a two-panel Textual layout from tab modules. `_collect_params()` reads widgets and normalizes mode-specific configuration. `_run_backtest()` dispatches real data, Random Walk, and Monte Carlo paths separately. `_update_results()` switches tables, metrics, chart buttons, and pie/allocation behavior based on execution mode.

**Why:** The UI is the coordination layer, but the analysis and graph logic are now delegated to mode-specific modules so simulation, real market, and live concepts do not mix.

**Important functions:**
- `BacktestApp.on_mount()` - starts the embedded reports server and settings restore.
- `_collect_params()` - reads all UI inputs and blocks invalid real-market allocation only in real mode.
- `_generate_synthetic_df()` - creates GBM-like synthetic OHLCV paths for Random Walk and Monte Carlo.
- `_run_backtest()` - strict execution-mode routing.
- `_update_results()` - mode-aware stats/trades/symbol table updates.
- `_draw_pie_chart()` - real allocation pie for real-market mode; simulation summaries for synthetic modes.
- `_apply_asset_filter()` - switches chart buttons using `CHART_LAYOUTS`.
- `_save_backtest()` / `_load_backtest()` - snapshot round-trip.
- `_run_ai_analysis()` - calls the mode-aware AI analyzer.

**Key imports:** `textual`, `Dataframe`, `SignalLogic`, `BacktestEngine`, `analysis.modes`, `graphs.montecarlo_graphs`, TUI tabs/components/utils

---

## `ui/tui/tabs/data_tab.py`

**What:** Data configuration tab for Real Market Data, Random Walk, and Monte Carlo.

**How:** Uses one permanent `DataTabScrollManager` + `DataTabScroll` for stable scrolling. `VerticalGroup` content gives the scroll container real overflow. The data source selector toggles the three mode-specific sections and asks the app to rebuild allocation visibility.

**Why:** The Data tab had duplicated/brittle scroll behavior. It now has one authoritative scroll owner and keeps simulation controls separate from real-market controls.

**Key classes:** `DataTabScrollManager`, `DataTabScroll`, `_DataContent`, `DataTab`

---

## `ui/tui/tabs/*.py`

**What:** Thin tab modules for strategy selection, dynamic params, risk settings, trades, charts, stats, pie, AI setup, and logs.

**How:** Each tab composes its widgets and delegates cross-tab behavior back to `BacktestApp`.

**Why:** Splitting the old monolithic TUI keeps widgets small and lets `composer.py` own orchestration.

**Files:** `strategy_picker_tab.py`, `strategy_params_tab.py`, `risk_tab.py`, `trades_tab.py`, `chart_tab.py`, `stats_tab.py`, `pie_tab.py`, `setup_tab.py`, `logs_tab.py`

---

## `ui/tui/utils/helpers.py`

**What:** Shared TUI helpers, chart URL builder, tooltip factory, and embedded reports HTTP server.

**How:** `ensure_chart_server()` serves `reports/` on port `8080`; `_chart_url()` starts the server defensively and returns `http://HOST:8080/...`.

**Why:** Browser chart buttons need an actual HTTP target. This prevents `ERR_CONNECTION_REFUSED` when opening generated Plotly reports.

---

## `ui/tui/utils/ai_analyzer.py`

**What:** Mode-aware AI/report facade.

**How:** Uses `analysis.modes.mode_from_setup()` to dispatch scoring, pattern detection, recommendations, and prompts to the correct analysis engine. Real-market logic remains here; Monte Carlo, Random Walk, and Live Trading logic live in their own packages.

**Why:** Monte Carlo and Random Walk reports must not use real asset, portfolio, or market interpretation language.

---

## `analysis/modes.py`

**What:** Canonical execution-mode constants and normalization helpers.

**How:** Maps UI data-source values (`REAL`, `RANDOM_WALK`, `MONTE_CARLO`, `LIVE`) to internal mode ids (`real_market_backtest`, `random_walk`, `monte_carlo`, `live_trading`).

**Why:** Every pipeline branch uses the same vocabulary, reducing accidental mode mixing.

---

## `analysis/montecarlo/analyzer.py`

**What:** Monte Carlo-only analysis engine.

**How:** Scores and reports simulation-path outcomes, probability of positive terminal value, percentile bands, variance, drawdown distribution, and sample robustness.

**Why:** Monte Carlo is a probabilistic simulator, not real asset analysis.

---

## `analysis/random_walk/analyzer.py`

**What:** Random Walk-only analysis engine.

**How:** Scores synthetic movement response, stochastic risk, signal behavior, and path sample size.

**Why:** Random Walk is a stochastic model and should not infer live/real market conditions.

---

## `analysis/real_market/analyzer.py`

**What:** Real-market analysis package boundary.

**How:** Documents the real OHLCV/portfolio terminology boundary. The existing real-market heuristics remain in `ui/tui/utils/ai_analyzer.py`.

**Why:** Keeps real symbol, portfolio allocation, and asset-contribution concepts scoped to real-market backtesting.

---

## `analysis/live_trading/analyzer.py`

**What:** Live-trading analysis boundary.

**How:** Returns placeholder live-analysis messaging until broker/exchange execution records are available.

**Why:** Live trading must not reuse simulation analytics.

---

## `graphs/portfolio_graphs.py`

**What:** Real-market chart generator.

**How:** Writes vectorbt portfolio charts and a custom Plotly trade chart with hash-based asset routing.

**Why:** These charts only make sense for real OHLCV/portfolio backtests.

---

## `graphs/montecarlo_graphs.py`

**What:** Monte Carlo chart generator.

**How:** Builds path cloud, percentile envelope, terminal-value histogram, drawdown distribution, and 3D simulation surface from per-path equity histories.

**Why:** Monte Carlo needs probability/distribution visuals instead of asset allocation or trade charts.

---

## `graphs/random_walk_graphs.py`

**What:** Random Walk chart generator.

**How:** Builds stochastic path charts and drift/volatility propagation charts.

**Why:** Random Walk visualization should describe synthetic path behavior, not real portfolio exposure.

---

## `graphs/live_graphs.py`

**What:** Live-chart package boundary.

**How:** Currently returns no charts until live execution data exists.

**Why:** Live monitoring should be built on active positions, broker data, execution fills, and real PnL.

---

## `core/backtest_engine.py`

**What:** Vectorbt-powered execution engine.

**How:** Pivots long-format signals to wide per-symbol matrices, applies exposure filtering for real-market mode, runs `vbt.Portfolio.from_signals()`, computes stats/trades/equity history, and delegates chart generation by mode.

**Why:** Vectorbt remains the performance-critical simulation core, while chart semantics are now isolated by execution environment.

**Key mode behavior:**
- `real_market_backtest` -> portfolio charts via `graphs/portfolio_graphs.py`
- `random_walk` -> stochastic charts via `graphs/random_walk_graphs.py`
- `monte_carlo` -> no per-path portfolio charts; aggregate charts are generated by the TUI after all paths complete

---

## `core/signal_logic.py`

**What:** Strategy coordinator.

**How:** Dispatches each symbol/path slice to the selected strategy class, supports `DUAL_STRATEGY`, and returns unified indicator/signal DataFrames.

**Why:** Strategy classes stay stateless and reusable across real and synthetic data.

---

## `core/constants.py`

**What:** Strategy schema and app constant registry.

**How:** Discovers strategy `CONFIG_ENTRIES`, builds `STRATEGY_SCHEMAS`, and defines Binance/backtest constants.

**Why:** New strategy parameters appear in the TUI without hardcoding UI fields.

---

## `scripts/gen_estructura.py`

**What:** SL/TP resolver and portfolio exposure manager imported at runtime as `gen_estructura`.

**How:** Normalizes stop-loss/take-profit formats and filters entries when real-market portfolio exposure would exceed configured allocation.

**Why:** Stop order interpretation and capital reservation need one shared resolver across strategies and engine code.

---

## `binance_service/dataframe.py`

**What:** Historical OHLCV fetcher and cache manager.

**How:** Fetches Binance klines in parallel, fills cache gaps forward/backward, saves per-symbol parquet files, and returns a unified DataFrame.

**Why:** Real-market mode needs fast repeatable historical data loading.

---

## `binance_service/connect.py`

**What:** Minimal python-binance client wrapper.

**How:** Reads credentials from env but supports public unauthenticated market data.

**Why:** The app should work in demo mode without API keys.

---

## `strategies/__init__.py`

**What:** Strategy plugin discovery.

**How:** Scans local strategies and `strategies/Strategies-eggshell/`, imports valid packages, and builds `STRATEGY_REGISTRY` / `STRATEGY_CLASSES`.

**Why:** Drop-in strategies become available to the TUI and signal logic without editing central code.

---

## `strategies/Ema_cross/strategy.py`

**What:** EMA crossover strategy with optional MFI confirmation.

**How:** Computes fast/slow EMA and detects crossovers; optional MFI gates buy/sell signals.

**Why:** Provides a compact baseline strategy for real and synthetic modes.
