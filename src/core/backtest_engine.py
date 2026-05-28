from core.constants import BacktestConstants

import os
import traceback
import pandas as pd
import numpy as np
import vectorbt as vbt

from analysis.modes import MONTE_CARLO, RANDOM_WALK, REAL_MARKET_BACKTEST, normalize_mode
from graphs.portfolio_graphs import generate_portfolio_graphs
from graphs.random_walk_graphs import generate_random_walk_graphs
from core.performance import enable_high_performance_mode

enable_high_performance_mode()
vbt.settings["engine"] = "rust"


def _safe(val, default=0.0):
    return default if pd.isna(val) else val


class BacktestEngine:
    def __init__(self, signals_df: pd.DataFrame, initial_balance: float | None = None,
                 position_size_pct: float = 100.0, cooldown: int = 0,
                 accumulate: bool = False, per_symbol_alloc: dict | None = None,
                 vbt_params: dict | None = None, sell_at_end: bool = False,
                 simulation_mode: str = "real_market_backtest",
                 generate_charts: bool = True):
        self.df = signals_df.copy(deep=False)
        if "symbol" in self.df.columns:
            self.df["symbol"] = self.df["symbol"].astype("category")
        self.initial_balance = initial_balance if initial_balance is not None else BacktestConstants.INITIAL_BALANCE
        self.position_size_pct = position_size_pct
        self.cooldown = cooldown
        self.accumulate = accumulate
        self.per_symbol_alloc = per_symbol_alloc
        self.vbt_params = vbt_params or {}
        self.sell_at_end = sell_at_end
        self.simulation_mode = normalize_mode(simulation_mode)
        self.generate_charts = generate_charts
        self.results: dict = {}
        self.trades: list[dict] = []

    def run(self, on_progress: callable = None):
        if on_progress:
            on_progress(0.1, "PIVOTING SIGNAL MATRICES...")

        if not isinstance(self.df.index, pd.DatetimeIndex):
            self.df.index = pd.to_datetime(self.df.index)

        p = self.vbt_params

        # Pivot OHLCV + signals into per-symbol columns
        def _pivot(col, default=None):
            if col not in self.df.columns:
                return default
            try:
                return self.df.set_index([self.df.index, 'symbol'])[col].unstack('symbol')
            except Exception:
                try:
                    return self.df.pivot_table(index=self.df.index, columns='symbol', values=col)
                except Exception:
                    return default

        def _fill_bool(s):
            # fillna on object-dtype columns triggers a FutureWarning in pandas ≥2.
            # Convert to float first so fillna receives a numeric array, then cast.
            return s.astype(float).fillna(0.0).astype(bool)

        try:
            close_df = self.df.set_index([self.df.index, 'symbol'])['close'].unstack('symbol')
            buy_df   = _fill_bool(self.df.set_index([self.df.index, 'symbol'])['buy'].unstack('symbol'))
            sell_df  = _fill_bool(self.df.set_index([self.df.index, 'symbol'])['sell'].unstack('symbol'))
        except Exception:
            close_df = self.df.pivot_table(index=self.df.index, columns='symbol', values='close')
            buy_df   = _fill_bool(self.df.pivot_table(index=self.df.index, columns='symbol', values='buy',  aggfunc='any'))
            sell_df  = _fill_bool(self.df.pivot_table(index=self.df.index, columns='symbol', values='sell', aggfunc='any'))

        open_df  = _pivot('open',  np.nan)
        high_df  = _pivot('high',  np.nan)
        low_df   = _pivot('low',   np.nan)

        if self.sell_at_end:
            # SELL BLOCKED - sell_at_end enabled: wipe all intermediate exits so
            # positions are held regardless of strategy signals, TP, or SL.
            if on_progress:
                on_progress(0.25, "SELL BLOCKED - sell_at_end enabled")
            sell_df[:] = False
            # FINAL CANDLE - Closing all positions at market price.
            if not sell_df.empty:
                if on_progress:
                    on_progress(0.28, "FINAL CANDLE - Closing all positions")
                sell_df.iloc[-1] = True

            # Warn when pyramiding is off — only 1 trade per symbol will fire.
            if not self.accumulate and on_progress:
                on_progress(0.29, "SELL AT END + no pyramiding: each symbol limited to 1 trade")

        else:
            # Normal mode: force exit on the last candle in addition to strategy exits.
            if not sell_df.empty:
                sell_df.iloc[-1] = True

        # ── Exposure manager: enforce global capital reservation before vbt ──────
        # Active only for real-data backtests; bypassed for Monte Carlo / RW.
        from gen_estructura import apply_exposure_filter
        buy_df, _exp_mgr = apply_exposure_filter(
            buy_df, sell_df,
            position_size_pct=self.position_size_pct,
            per_symbol_alloc=self.per_symbol_alloc,
            sell_at_end=self.sell_at_end,
            simulation_mode=self.simulation_mode,
            equity=self.initial_balance,
        )
        if on_progress and _exp_mgr.rejected_entries:
            on_progress(0.32,
                f"[PORTFOLIO EXPOSURE MANAGER] "
                f"Global Exposure Used: {_exp_mgr.reserved_exposure_pct:.1f}%  "
                f"Remaining Exposure: {_exp_mgr.available_exposure_pct:.1f}%  "
                f"Trade rejected: insufficient remaining portfolio exposure "
                f"({len(_exp_mgr.rejected_entries)} rejected)"
            )

        # Cooldown: suppress entries within N candles of the previous one
        if self.cooldown > 0:
            for col in buy_df.columns:
                col_idx = buy_df.columns.get_loc(col)
                last_entry = -self.cooldown - 1
                for i in range(len(buy_df)):
                    if buy_df.iat[i, col_idx]:
                        if i - last_entry <= self.cooldown:
                            buy_df.iat[i, col_idx] = False
                        else:
                            last_entry = i

        if on_progress:
            on_progress(0.4, "APPLYING TRADE SIZING & COOLDOWN...")

        size_df   = pd.DataFrame(np.nan, index=close_df.index, columns=close_df.columns)
        n_cols    = len(buy_df.columns)
        size_type = p.get("size_type", "value")

        for col in buy_df.columns:
            sym       = str(col)
            alloc_frac = (
                self.per_symbol_alloc.get(sym, 100.0 / n_cols) / 100.0
                if self.per_symbol_alloc else 1.0 / n_cols
            )
            if size_type == "value":
                size_df.loc[buy_df[col], col] = round(
                    (self.position_size_pct / 100.0) * alloc_frac * self.initial_balance, 2
                )
            else:  # percent
                size_df.loc[buy_df[col], col] = (self.position_size_pct / 100.0) * alloc_frac

        size_df[sell_df] = np.inf if size_type == "value" else 1.0

        sl_stop = p.get("sl_stop", np.nan)
        tp_stop = p.get("tp_stop", np.nan)
        if self.sell_at_end:
            # Disable stop orders — positions must be held until the final candle.
            sl_stop = np.nan
            tp_stop = np.nan
        else:
            # Ask the resolver whether the strategy provided its own SL/TP columns.
            # When it does, build per-candle fractional arrays and pivot them to
            # (time × symbol) so vectorbt can use per-trade stop levels.
            from gen_estructura import build_exit_arrays, has_valid_stops
            _sl_series, _tp_series = build_exit_arrays(
                self.df,
                fallback_sl_pct=sl_stop if not (isinstance(sl_stop, float) and np.isnan(sl_stop)) else None,
                fallback_tp_pct=tp_stop if not (isinstance(tp_stop, float) and np.isnan(tp_stop)) else None,
            )
            if _sl_series is not None or _tp_series is not None:
                # Strategy provided exit levels — pivot flat series → (time × symbol)
                _tmp = self.df[["symbol"]].copy()
                _tmp["_sl"] = _sl_series if _sl_series is not None else np.nan
                _tmp["_tp"] = _tp_series if _tp_series is not None else np.nan
                try:
                    sl_stop = _tmp.set_index([_tmp.index, "symbol"])["_sl"].unstack("symbol")
                    tp_stop = _tmp.set_index([_tmp.index, "symbol"])["_tp"].unstack("symbol")
                except Exception:
                    sl_stop = _tmp.pivot_table(index=_tmp.index, columns="symbol", values="_sl")
                    tp_stop = _tmp.pivot_table(index=_tmp.index, columns="symbol", values="_tp")

        # has_valid_stops handles both scalar NaN and DataFrame/Series
        from gen_estructura import has_valid_stops
        use_stops = has_valid_stops(sl_stop) or has_valid_stops(tp_stop)

        portfolio = vbt.Portfolio.from_signals(
            close=close_df,
            open=open_df if open_df is not None else np.nan,
            high=high_df if high_df is not None else np.nan,
            low=low_df  if low_df  is not None else np.nan,
            entries=buy_df,
            exits=sell_df,
            init_cash=self.initial_balance,
            size=size_df,
            size_type=size_type,
            cash_sharing=p.get("cash_sharing", True),
            call_seq='auto',
            accumulate=self.accumulate,
            group_by=True,
            engine="rust",
            # ── Trading costs ──────────────────────────────
            fees=p.get("fees", 0.0),
            fixed_fees=p.get("fixed_fees", 0.0),
            slippage=p.get("slippage", 0.0),
            # ── Stop orders ────────────────────────────────
            sl_stop=sl_stop,
            sl_trail=p.get("sl_trail", False),
            tp_stop=tp_stop,
            stop_exit_price=p.get("stop_exit_price", 0),
            use_stops=use_stops,
            # ── Order behaviour ────────────────────────────
            # sell_at_end: forbid sub-penny fills so entries stop cleanly when cash
            # is exhausted (e.g. 1 % budget → ≤ 100 entries per $1 000 balance).
            allow_partial=False if self.sell_at_end else p.get("allow_partial", True),
            lock_cash=p.get("lock_cash", False),
            reject_prob=p.get("reject_prob", 0.0),
            min_size=p.get("min_size", 0.0),
            max_size=p.get("max_size", np.inf),
            upon_opposite_entry=p.get("upon_opposite_entry", 4),
            direction=p.get("direction", 0),
            # upon_long_conflict replaces the removed conflict_mode from older vbt API
            upon_long_conflict=p.get("upon_long_conflict", 0),
        )

        if on_progress:
            on_progress(0.8, "COMPUTING PERFORMANCE STATISTICS...")

        # ── Stats ─────────────────────────────────────────────────────────────
        try:
            stats = portfolio.stats()
            full_stats = {
                str(k).replace("[", "(").replace("]", ")"): (
                    "N/A"   if pd.isna(v)
                    else str(v) if isinstance(v, (pd.Timedelta, pd.Timestamp))
                    else v
                )
                for k, v in stats.to_dict().items()
            }
            total_ret     = _safe(stats.get('Total Return [%]'))
            max_dd        = _safe(stats.get('Max Drawdown [%]'))
            profit_factor = _safe(stats.get('Profit Factor'))
            sharpe        = _safe(stats.get('Sharpe Ratio'))
            sortino       = _safe(stats.get('Sortino Ratio'))
            calmar        = _safe(stats.get('Calmar Ratio'))
            recovery      = _safe(stats.get('Recovery Factor'))
            best_trade    = _safe(stats.get('Best Trade [%]'))
            worst_trade   = _safe(stats.get('Worst Trade [%]'))
            avg_win       = _safe(stats.get('Avg Winning Trade [%]'))
            avg_loss      = _safe(stats.get('Avg Losing Trade [%]'))
        except Exception as stats_err:
            self._log_error(f"portfolio.stats() failed: {stats_err}")
            full_stats = {}
            total_ret = max_dd = profit_factor = sharpe = 0.0
            sortino = calmar = recovery = best_trade = worst_trade = 0.0
            avg_win = avg_loss = 0.0

        net_profit    = (total_ret / 100.0) * self.initial_balance
        final_balance = self.initial_balance + net_profit

        # ── Trade records ─────────────────────────────────────────────────────
        try:
            vbt_trades = portfolio.entry_trades.records_readable
        except Exception:
            vbt_trades = pd.DataFrame()

        # Scalar SL/TP from params used for exit-reason inference (DataFrame
        # per-candle stops can't be matched exactly, so fall back to "Sell Signal").
        _sl_scalar = p.get("sl_stop", np.nan)
        _tp_scalar = p.get("tp_stop", np.nan)
        _sl_scalar = float(_sl_scalar) if np.isscalar(_sl_scalar) else np.nan
        _tp_scalar = float(_tp_scalar) if np.isscalar(_tp_scalar) else np.nan
        _last_ts = close_df.index[-1] if not close_df.empty else None

        def _exit_reason(ret: float, exit_ts) -> str:
            if _last_ts is not None and exit_ts == _last_ts:
                return "Final Candle"
            tol = 0.003  # 0.3 % tolerance for floating-point stop matching
            if not np.isnan(_sl_scalar) and abs(ret + _sl_scalar) < tol:
                return "Stop Loss"
            if not np.isnan(_tp_scalar) and abs(ret - _tp_scalar) < tol:
                return "Take Profit"
            return "Sell Signal"

        formatted_trades = []
        sym_stats = {}
        wins = 0

        if not vbt_trades.empty:
            for row in vbt_trades.to_dict("records"):
                col = row.get("Column", "Unknown")
                sym = str(col[0] if isinstance(col, tuple) else col)

                ret     = row["Return"]
                pnl     = row["PnL"]
                qty     = row["Size"]
                b_price = row["Avg Entry Price"]

                if ret > 0:
                    wins += 1

                formatted_trades.append({
                    "symbol":              sym,
                    "buy_time":            row["Entry Timestamp"],
                    "sell_time":           row["Exit Timestamp"],
                    "buy_price":           b_price,
                    "sell_price":          row["Avg Exit Price"],
                    "profit_pct":          ret * 100.0,
                    "account_profit_pct":  pnl / self.initial_balance * 100.0 if self.initial_balance else 0.0,
                    "profit_usd":          pnl,
                    "investment":          qty * b_price,
                    "quantity":            qty,
                    "reason":              _exit_reason(ret, row["Exit Timestamp"]),
                })

                s = sym_stats.setdefault(sym, {"trades": 0, "wins": 0, "total_pct": 0.0})
                s["trades"] += 1
                if ret > 0:
                    s["wins"] += 1
                s["total_pct"] += ret * 100.0

        total_trades   = len(formatted_trades)
        win_rate       = wins / total_trades * 100.0 if total_trades else 0.0
        avg_trade      = total_ret / total_trades     if total_trades else 0.0
        avg_hold_hours = 0.0
        if formatted_trades:
            avg_hold_hours = sum(
                (t["sell_time"] - t["buy_time"]).total_seconds() / 3600.0
                for t in formatted_trades
            ) / total_trades

        self.trades = formatted_trades

        # ── Chart series ──────────────────────────────────────────────────────
        equity_series         = portfolio.value()
        self.equity_history   = list(equity_series.values)
        self.returns_history  = list(((1 + portfolio.returns()).cumprod() - 1).values * 100.0)
        self.drawdown_history = list(portfolio.drawdown().values * 100.0)
        self.price_history    = list(close_df.iloc[:, 0].ffill().fillna(0).values) if not close_df.empty else []

        buy_hold = 0.0
        if not close_df.empty:
            first = close_df.iloc[0].replace(0, np.nan)
            buy_hold = float(((close_df.iloc[-1] - first) / first).mean() * 100.0) if first.notna().any() else 0.0

        charts = self._generate_charts(close_df, formatted_trades, portfolio) if self.generate_charts else {}

        if on_progress:
            on_progress(1.0, "GENERATING CHART REPORTS...")

        self.results = {
            "total_return_pct":  total_ret,
            "win_rate":          win_rate,
            "total_trades":      total_trades,
            "net_profit":        net_profit,
            "best_trade":        best_trade,
            "worst_trade":       worst_trade,
            "avg_trade_pct":     avg_trade,
            "avg_win_pct":       avg_win,
            "avg_loss_pct":      avg_loss,
            "final_balance":     final_balance,
            "max_drawdown_pct":  max_dd,
            "avg_hold_hours":    avg_hold_hours,
            "profit_factor":     profit_factor,
            "sharpe_ratio":      sharpe,
            "sortino_ratio":     sortino,
            "calmar_ratio":      calmar,
            "recovery_factor":   recovery,
            "buy_hold_pct":      buy_hold,
            "symbol_stats":      sym_stats,
            "equity_history":    self.equity_history,
            "returns_history":   self.returns_history,
            "drawdown_history":  self.drawdown_history,
            "price_history":     self.price_history,
            "timestamp_history": list(equity_series.index),
            "full_stats":        full_stats,
            "charts":            charts,
            "execution_mode":    self.simulation_mode,
        }
        return self.results

    def _generate_charts(self, close_df, formatted_trades, portfolio) -> dict:
        proj_root  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        charts_dir = os.path.join(proj_root, "reports", "charts")
        try:
            if self.simulation_mode == REAL_MARKET_BACKTEST:
                return generate_portfolio_graphs(close_df, formatted_trades, portfolio, charts_dir)
            if self.simulation_mode == RANDOM_WALK:
                return generate_random_walk_graphs(close_df, self.results, charts_dir)
            if self.simulation_mode == MONTE_CARLO:
                return {}
        except Exception as e:
            self._log_error(f"chart generation: {e}")
        return {}

    def _log_error(self, msg: str):
        proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        err_dir   = os.path.join(proj_root, "reports", "errors")
        os.makedirs(err_dir, exist_ok=True)
        with open(os.path.join(err_dir, "error.log"), "a") as f:
            f.write(f"{msg}\n{traceback.format_exc()}\n")
