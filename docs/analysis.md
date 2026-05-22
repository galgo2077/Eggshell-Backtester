# Eggshell Backtester — Python File Analysis
<!-- Auto-maintained by scripts/gen_estructura.py -->
<!-- New modules get a skeleton section. **What/How/Why** is hand-written and preserved on update. -->
<!-- **Structure:** and **Key imports:** are auto-regenerated from AST on every Write/Edit. -->

---

## `main.py`

**What:** Application entry point. Offers two runtime modes: the Textual TUI (default) and a legacy Rich console CLI (`--cli`). Clears `reports/errors/error.log` on every startup.

**How:** Checks `sys.argv` for `--cli`; if present runs `run_backtest()` — a sequential Rich-prompt wizard (asset/strategy/balance/timeframe) feeding into `Dataframe → SignalLogic → BacktestEngine` with a live `Progress` bar and final result panels. Default path calls `BacktestApp().run()`.

**Why:** Two modes exist because the TUI requires a real terminal (won't work in pipes/Docker exec), while `--cli` is scriptable. Error log is cleared on startup so stale tracebacks from a previous crash don't mislead debugging.

**Structure:**
- `display_summary(results)` — returns `Columns` with 4 Rich Panel performance cards
- `display_trades_table(trades)` — returns `Table` of last 15 trades, color-coded profit
- `get_user_preferences()` — Rich Prompt wizard, returns config dict
- `run_backtest()` — sequential flow: preferences → fetch → signals → simulate → print

**Key imports:** `rich`, `binance_service.dataframe.Dataframe`, `core.signal_logic.SignalLogic`, `core.backtest_engine.BacktestEngine`, `ui.tui.BacktestApp`

---

## `ui/tui.py`

**What:** ~2 000-line Textual TUI application (`BacktestApp`). Full interactive backtester with tabs for config form, live results, charts, trade list, and multi-asset allocation controls.

**How:** Textual reactive widgets drive the parameter form. `_run_backtest_thread()` spawns a daemon thread that calls `Dataframe → SignalLogic → BacktestEngine`, passing an `on_progress(pct, msg)` callback that posts updates back to the Textual event loop to advance a `ProgressBar`. Plotly HTML charts are injected into a WebView widget. Save/Load round-trips through `reports/results/NAME/`.

**Why:** Background threading prevents the Textual event loop from blocking during multi-second data fetches and simulations — without it the UI would freeze. The `on_progress` contract is a clean boundary: the engine emits floats, the UI decides how to render them. Textual avoids the browser dependency that web-based dashboards require.

**Structure:**
- `BacktestApp(App)`
  - `_run_backtest_thread()` — thread body: Dataframe → SignalLogic → BacktestEngine → update UI
  - `_save_backtest()` — writes stats.txt, trades.csv, results.json, chart copies to results/NAME/
  - `_load_backtest()` — reads results.json and restores all widget state
  - `_draw_pie_chart()` — braille-art pie from per-asset allocation inputs

**Key imports:** `textual`, `core.backtest_engine.BacktestEngine`, `core.signal_logic.SignalLogic`, `core.constants.STRATEGY_SCHEMAS`, `binance_service.dataframe.Dataframe`

---

## `core/signal_logic.py`

**What:** Strategy coordinator. Applies indicator computation and buy/sell signal generation per symbol, dispatching to the correct registered strategy class. Supports single-strategy mode and DUAL_STRATEGY (AND/OR combination of two independent strategies).

**How:** Iterates unique symbols in the input DataFrame; for each calls `_get_strategy_class(name)` to look up the class in `STRATEGY_CLASSES`; instantiates and calls `apply_indicators()` then `generate_signals()`; concatenates per-symbol results. `DUAL_STRATEGY` runs two strategies on the same symbol independently and combines their boolean `buy`/`sell` columns with `|` (OR) or `&` (AND).

**Why:** Per-symbol dispatch keeps strategy classes stateless — they receive one symbol's slice and return it modified. DUAL_STRATEGY lives here rather than as a real strategy class to avoid circular imports (it needs `STRATEGY_SCHEMAS` from `core.constants`) and to keep strategy implementations decoupled from composition logic.

**Structure:**
- `SignalLogic(df, **kwargs)` — constructor applies strategy immediately, populates `self.df`, `self.indicators`, `self.signals`
  - `_get_strategy_class(name)` — registry lookup with fallback module scan
  - `_run_dual(df)` — runs two strategies, merges signals via AND/OR
  - `_build_indicators_df()` — non-OHLCV columns only
  - `_build_signals_df()` — `[symbol, close, buy, sell]` slice

**Key imports:** `pandas`, `strategies.STRATEGY_CLASSES`, `strategies.STRATEGY_REGISTRY`

---

## `core/backtest_engine.py`

**What:** Vectorbt-powered portfolio simulator. Takes a signal DataFrame and runs a realistic multi-asset trade simulation with configurable position sizing, cooldown suppression, and accumulation mode.

**How:** Pivots the long-format signal DataFrame to wide (one column per symbol) for vectorbt. Builds `size_df` matrices depending on mode: `percent` (fractional of portfolio) or `value` (fixed USD). Calls `vbt.Portfolio.from_signals()` with `cash_sharing=True` and `group_by=True` for true shared-capital multi-asset simulation. Computes stats from `portfolio.stats()`, rebuilds trade records from `portfolio.entry_trades.records_readable`, generates 6 vectorbt HTML charts plus a custom Plotly trade-execution chart with per-asset dropdown.

**Why:** Vectorbt is the performance-critical path — it runs the entire simulation in vectorized NumPy. `cash_sharing=True` is essential: without it each asset gets the full initial capital making multi-asset results meaningless. Cooldown logic suppresses whipsawing entries when a strategy oscillates rapidly. Chart output goes to `reports/charts/` so the TUI can display them without re-running the engine.

**Structure:**
- `BacktestEngine(signals_df, initial_balance, position_size_pct, cooldown, accumulate, per_symbol_alloc)`
  - `run(on_progress)` → `dict` — full simulation pipeline, populates `self.results` and `self.trades`
  - `_generate_charts(close_df, formatted_trades, portfolio)` → `dict` — writes HTML chart files
  - `_write_trades_chart(close_df, formatted_trades, path)` — custom Plotly chart with hash-based asset routing
  - `_log_error(msg)` — appends to `reports/errors/error.log`

**Key imports:** `vectorbt`, `pandas`, `numpy`, `plotly.graph_objects`, `core.constants.BacktestConstants`

---

## `core/constants.py`

**What:** Central configuration registry. Aggregates all strategy parameter definitions into a unified pandas DataFrame and derives the hierarchical `STRATEGY_SCHEMAS` dict that the UI uses to generate its settings form dynamically.

**How:** At import time iterates `STRATEGY_REGISTRY`, reads each strategy's `CONFIG_ENTRIES` list and `STRATEGY_NAME`; builds flat `CONFIG_REGISTRY` list → `pandas.DataFrame` (`CONFIG`). `build_strategy_schemas_from_config()` pivots flat rows to `{strategy: {category: {key: {type, default, label}}}}`. Also defines the three base constant classes (`ConnectConstantsBinance`, `DataframeConstantsBinance`, `BacktestConstants`) and appends the hardcoded DUAL_STRATEGY entries.

**Why:** Centralizing config in a DataFrame (not hardcoded dicts per strategy) means adding a strategy's `CONFIG_ENTRIES` automatically registers all its parameters in the TUI settings panel — no other file needs to change. The hierarchical schema keeps the UI form generation generic.

**Structure:**
- `ConnectConstantsBinance` — API_KEY, API_SECRET from env, default START_DATE
- `DataframeConstantsBinance` — ACTIVES list, KLINE_INTERVAL, column definitions
- `BacktestConstants` — INITIAL_BALANCE, TAKE_PROFIT_PCT, STOP_LOSS_PCT
- `build_strategy_schemas_from_config(cfg_df)` → `dict` — flat DataFrame → nested schema
- `get_settings_dataframe()` → `DataFrame` — returns copy of CONFIG

**Key imports:** `pandas`, `strategies.STRATEGY_REGISTRY`

---

## `binance_service/dataframe.py`

**What:** Historical OHLCV data fetcher with per-symbol parquet cache and bi-directional gap filling. Fetches up to 8 assets in parallel and exposes a unified `self.df` DataFrame filtered to the requested date range.

**How:** `ThreadPoolExecutor(max_workers=8)` maps `_process_asset` over each symbol. Per asset: loads existing parquet cache → forward-fetches new candles since `cache.index.max()` → backward-fetches if `start_date < cache.index.min()` → deduplicates and saves updated cache. Thread-safe progress tracking via `threading.Lock`. Final `self.df` is sliced to `[start_date, end_date]`.

**Why:** Parallel fetch is ~8× faster than sequential. Bi-directional gap filling means requesting an earlier start date only fetches the missing historical range rather than wiping and re-downloading everything. Per-symbol cache files (`{SYM}_{interval}.parquet`) let individual assets be invalidated without affecting others.

**Structure:**
- `Dataframe(actives, interval, start_date, end_date, on_progress)` — constructor fetches and stores `self.df`
  - `_process_asset(sym)` → `DataFrame | None` — cache-aware fetch for one symbol
  - `_fetch_klines(active, start, end_ms)` → `(str, list)` — raw Binance API call
  - `_rates_to_df(active, rates)` → `DataFrame | None` — raw kline list → typed, indexed DataFrame
  - `_load_sym_cache(sym)` / `_save_sym_cache(sym, df)` — parquet read/write
  - `_purge_old_caches()` — removes legacy monolithic cache files

**Key imports:** `pandas`, `concurrent.futures.ThreadPoolExecutor`, `binance_service.connect.Connect`, `core.constants.ConnectConstantsBinance`, `core.constants.DataframeConstantsBinance`

---

## `binance_service/connect.py`

**What:** Minimal python-binance `Client` wrapper. Loads credentials from environment and exposes `self.client` ready for kline requests. Works unauthenticated for public market data.

**How:** `ConnectConstantsBinance` reads `BINANCE_API_KEY`/`BINANCE_API_SECRET` from env (empty strings if missing). `Client(key, secret)` from python-binance accepts empty keys and still serves public endpoints. `_health_check()` makes a silent test request — bare `except: pass` ensures a dead exchange doesn't block startup.

**Why:** Public OHLCV klines require no authentication, so the app works in demo mode with zero configuration. Silencing the health check error prevents startup failures in Docker/offline environments where the exchange is unreachable.

**Structure:**
- `Connect()` — sets `self.client`
  - `_health_check()` — test BTCUSDT kline fetch, silently ignores all exceptions

**Key imports:** `binance.client.Client`, `core.constants.ConnectConstantsBinance`

---

## `strategies/__init__.py`

**What:** Zero-config plugin discovery system for strategy packages. Builds `STRATEGY_REGISTRY` (package name → module) and `STRATEGY_CLASSES` (strategy name → class) by scanning two directories at import time.

**How:** `_discover()` scans `strategies/` (local) and `strategies/Strategies-eggshell/` (git submodule) for directories that contain exactly `__init__.py + strategy.py + constants.py`. Imports each via `importlib.import_module`. Reads `constants.STRATEGY_NAME` for the canonical display key. Inspects module attributes for a class whose name ends in `Strategy` to register in `STRATEGY_CLASSES`. Submodule path is prepended to `sys.path` for transparent import resolution.

**Why:** Drop-in registration — create a folder with the three required files and the strategy appears everywhere (TUI, constants, signal logic) without editing any existing file. Import failures are logged to stderr but never crash the app, allowing partial loading when a strategy has broken dependencies.

**Structure:**
- `STRATEGY_REGISTRY: dict` — auto-populated at module import
- `STRATEGY_CLASSES: dict` — strategy name → class, auto-populated
- `_discover()` — private, called once at import time

**Key imports:** `os`, `sys`, `importlib`

---

## `strategies/Ema_cross/strategy.py`

**What:** EMA (Exponential Moving Average) crossover strategy with optional MFI (Money Flow Index) confirmation filter. Generates buy signals on fast-EMA-crosses-above-slow-EMA and sell signals on the reverse.

**How:** `apply_indicators()` computes FAST/SLOW EMA via `pandas.ewm(span=N, adjust=False).mean()` and optionally MFI natively (typical_price × volume rolling positive/negative ratio). `generate_signals()` detects crossovers using boolean shift: `fast_above & (~fast_above).shift(1)`. MFI optionally gates: buy only when `MFI <= BUY_LEVEL`, sell only when `MFI >= SELL_LEVEL`.

**Why:** Native pandas/numpy implementation avoids the pandas-ta dependency for simple indicators — reducing Docker image size and startup time. `adjust=False` makes EMA recursive (like TradingView), not corrected, which is the industry-standard formula. MFI filtering reduces whipsaw signals in ranging/sideways markets.

**Structure:**
- `EMACrossStrategy(df, **kwargs)`
  - `apply_indicators()` → `DataFrame` — adds `FAST_EMA`, `SLOW_EMA`, optionally `MFI`
  - `generate_signals()` → `DataFrame` — adds boolean `buy`, `sell` columns

**Key imports:** `pandas`, `numpy`, `strategies.Ema_cross.constants`
