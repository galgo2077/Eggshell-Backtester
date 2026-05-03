from core.constants import BacktestConstants

import os
import pandas as pd
import numpy as np
import vectorbt as vbt

class BacktestEngine:
    def __init__(self, signals_df: pd.DataFrame, initial_balance: float | None = None,
                 position_size_pct: float = 100.0, max_positions: int = 999,
                 accumulate: bool = False):
        self.df = signals_df.copy()
        self.initial_balance = initial_balance or BacktestConstants.INITIAL_BALANCE
        self.position_size_pct = position_size_pct
        self.max_positions = max_positions
        self.accumulate = accumulate
        self.results: dict = {}
        self.trades: list[dict] = []

    def run(self, on_progress: callable = None):
        if on_progress:
            on_progress(0.1)
            
        # Ensure DatetimeIndex for vectorbt
        if not isinstance(self.df.index, pd.DatetimeIndex):
            self.df.index = pd.to_datetime(self.df.index)

        # 1. Prepare data for vectorbt
        # Use a more robust way to handle multiple assets with overlapping timestamps
        try:
            # We assume the index is already a DatetimeIndex
            close_df = self.df.set_index([self.df.index, 'symbol'])['close'].unstack('symbol')
            buy_df   = self.df.set_index([self.df.index, 'symbol'])['buy'].unstack('symbol').fillna(False).astype(bool)
            sell_df  = self.df.set_index([self.df.index, 'symbol'])['sell'].unstack('symbol').fillna(False).astype(bool)
        except Exception:
            # Fallback if unstack fails (e.g. duplicates within a symbol)
            close_df = self.df.pivot_table(index=self.df.index, columns='symbol', values='close')
            buy_df   = self.df.pivot_table(index=self.df.index, columns='symbol', values='buy', aggfunc='any').fillna(False).astype(bool)
            sell_df  = self.df.pivot_table(index=self.df.index, columns='symbol', values='sell', aggfunc='any').fillna(False).astype(bool)

        if on_progress:
            on_progress(0.4)

        # 2. Run highly optimized Numba backtest via VectorBT
        pos_size = round((self.position_size_pct / 100.0) * self.initial_balance, 2)
        
        # Build a size DataFrame to properly handle size and forced exits
        size_df = pd.DataFrame(np.nan, index=close_df.index, columns=close_df.columns)
        size_df[buy_df] = pos_size
        size_df[sell_df] = np.inf # Force sell 100% of accumulated position
        
        portfolio = vbt.Portfolio.from_signals(
            close=close_df,
            entries=buy_df,
            exits=sell_df,
            init_cash=self.initial_balance,
            size=size_df,
            size_type='value', # Use fixed dollar amount
            cash_sharing=True,
            call_seq='auto',   # Process signals sequentially (Greedy)
            accumulate=self.accumulate,
            group_by=True      # Group everything into a single portfolio
        )

        # ── HARD TRADE LIMIT LOGIC ──
        # If the user sets a limit, stop taking new trades after that limit is reached.
        limit = int(self.max_positions) if self.max_positions else 0
        if limit > 0:
            trades_df = portfolio.trades.records_readable
            if len(trades_df) > limit:
                # Sort trades by entry time to find the exact cutoff
                sorted_trades = trades_df.sort_values(by='Entry Timestamp')
                nth_entry_time = sorted_trades.iloc[limit - 1]['Entry Timestamp']
                
                # Disable all buy signals that happen AFTER the Nth trade's entry
                buy_df.loc[buy_df.index > nth_entry_time, :] = False
                
                # Re-run the portfolio simulation with the truncated signals
                limit_size_df = pd.DataFrame(np.nan, index=close_df.index, columns=close_df.columns)
                limit_size_df[buy_df] = pos_size
                limit_size_df[sell_df] = np.inf

                portfolio = vbt.Portfolio.from_signals(
                    close=close_df,
                    entries=buy_df,
                    exits=sell_df,
                    init_cash=self.initial_balance,
                    size=limit_size_df,
                    size_type='value',
                    cash_sharing=True,
                    call_seq='auto',
                    accumulate=self.accumulate,
                    group_by=True
                )

        if on_progress:
            on_progress(0.8)

        # 3. Extract comprehensive metrics
        full_stats_clean = {}
        try:
            stats = portfolio.stats()
            
            # Extract all stats safely
            raw_stats = stats.to_dict()
            for k, v in raw_stats.items():
                if pd.isna(v):
                    full_stats_clean[k] = "N/A"
                elif isinstance(v, pd.Timedelta):
                    full_stats_clean[k] = str(v)
                elif isinstance(v, pd.Timestamp):
                    full_stats_clean[k] = str(v)
                else:
                    full_stats_clean[k] = v

            total_ret = stats.get('Total Return [%]', 0.0)
            # We'll calculate win_rate and trades manually from records for higher accuracy in UI
            max_dd = stats.get('Max Drawdown [%]', 0.0)
            profit_factor = stats.get('Profit Factor', 0.0)
            sharpe = stats.get('Sharpe Ratio', 0.0)
            sortino = stats.get('Sortino Ratio', 0.0)
            calmar = stats.get('Calmar Ratio', 0.0)
            recovery = stats.get('Recovery Factor', 0.0)
            best_trade = stats.get('Best Trade [%]', 0.0)
            worst_trade = stats.get('Worst Trade [%]', 0.0)
            
            # VectorBT 'Total Return [%]' might be NA if no trades
            if pd.isna(total_ret): total_ret = 0.0
            if pd.isna(max_dd): max_dd = 0.0
            if pd.isna(profit_factor): profit_factor = 0.0
            if pd.isna(sharpe): sharpe = 0.0
            if pd.isna(sortino): sortino = 0.0
            if pd.isna(calmar): calmar = 0.0
            if pd.isna(recovery): recovery = 0.0
            if pd.isna(best_trade): best_trade = 0.0
            if pd.isna(worst_trade): worst_trade = 0.0
            
            net_profit = (total_ret / 100.0) * self.initial_balance
            final_balance = self.initial_balance + net_profit
            
            # Averages
            avg_win = stats.get('Avg Winning Trade [%]', 0.0)
            avg_loss = stats.get('Avg Losing Trade [%]', 0.0)
            if pd.isna(avg_win): avg_win = 0.0
            if pd.isna(avg_loss): avg_loss = 0.0
            
        except Exception:
            # Fallback if no trades or failure
            total_ret, max_dd, profit_factor = 0,0,0
            sharpe, sortino, calmar, recovery = 0,0,0,0
            best_trade, worst_trade = 0,0
            net_profit = 0
            final_balance = self.initial_balance

        # 4. Format Trade Records for the UI
        try:
            vbt_trades = portfolio.entry_trades.records_readable
        except Exception:
            vbt_trades = pd.DataFrame()

        formatted_trades = []
        sym_stats = {}
        wins = 0
        
        if not vbt_trades.empty:
            for _, r in vbt_trades.iterrows():
                sym = str(r['Column']) if 'Column' in r else "Unknown"
                if isinstance(r.get('Column'), tuple):
                    sym = r['Column'][0]
                
                b_time = r['Entry Timestamp']
                s_time = r['Exit Timestamp']
                b_price = r['Avg Entry Price']
                s_price = r['Avg Exit Price']
                qty = r['Size']
                pnl = r['PnL']
                inv = qty * b_price
                ret = r['Return']
                acct_ret = pnl / self.initial_balance if self.initial_balance > 0 else 0
                
                if ret > 0:
                    wins += 1
                
                formatted_trades.append({
                    "symbol": sym,
                    "buy_time": b_time,
                    "sell_time": s_time,
                    "buy_price": b_price,
                    "sell_price": s_price,
                    "profit_pct": ret * 100.0,
                    "account_profit_pct": acct_ret * 100.0,
                    "profit_usd": pnl,
                    "investment": inv,
                    "quantity": qty,
                    "reason": "Buy Sig -> Sell Sig"
                })
                
                if sym not in sym_stats:
                    sym_stats[sym] = {"trades": 0, "wins": 0, "total_pct": 0.0}
                sym_stats[sym]["trades"] += 1
                if ret > 0:
                    sym_stats[sym]["wins"] += 1
                sym_stats[sym]["total_pct"] += (ret * 100.0)
                
        # Final accurate win rate
        total_trades = len(formatted_trades)
        win_rate = (wins / total_trades * 100.0) if total_trades > 0 else 0.0
        avg_trade = (total_ret / total_trades) if total_trades > 0 else 0.0
        
        # Calculate avg hold hours
        avg_hold_hours = 0.0
        if formatted_trades:
            durations = [(t["sell_time"] - t["buy_time"]).total_seconds() / 3600.0 for t in formatted_trades]
            avg_hold_hours = sum(durations) / len(durations)

        self.trades = formatted_trades

        # 5. Extract charting data
        equity_series = portfolio.value()
        self.equity_history = list(equity_series.values)
        
        returns_series = portfolio.returns().cumsum()
        self.returns_history = list(returns_series.values * 100.0) # In percent
        
        drawdown_series = portfolio.drawdown()
        self.drawdown_history = list(drawdown_series.values * 100.0) # In percent
        
        all_timestamps = list(equity_series.index)
        
        # Benchmark price (we use the first asset's price to keep the scale consistent)
        
        if not close_df.empty:
            self.price_history = list(close_df.iloc[:, 0].ffill().fillna(0).values)
        else:
            self.price_history = []
            
        buy_hold = 0.0
        if not close_df.empty:
            b_h_returns = (close_df.iloc[-1] - close_df.iloc[0]) / close_df.iloc[0]
            buy_hold = b_h_returns.mean() * 100.0

        # Generate HTML Charts
        charts = {
            "main": os.path.abspath(os.path.join(os.getcwd(), "reports", "charts", "vectorbt_report.html")),
            "trades": os.path.abspath(os.path.join(os.getcwd(), "reports", "charts", "vectorbt_trades.html")),
            "underwater": os.path.abspath(os.path.join(os.getcwd(), "reports", "charts", "vectorbt_underwater.html")),
            "value": os.path.abspath(os.path.join(os.getcwd(), "reports", "charts", "vectorbt_value.html")),
            "drawdowns": os.path.abspath(os.path.join(os.getcwd(), "reports", "charts", "vectorbt_drawdowns.html")),
            "returns": os.path.abspath(os.path.join(os.getcwd(), "reports", "charts", "vectorbt_returns.html")),
            "cash": os.path.abspath(os.path.join(os.getcwd(), "reports", "charts", "vectorbt_cash.html")),
        }
        
        try:
            os.makedirs(os.path.join(os.getcwd(), "reports", "charts"), exist_ok=True)
            if len(close_df) > 0:
                try:
                    portfolio.plot().write_html(charts["main"])
                except Exception: pass
                
                try:
                    # If multiple columns, we try to plot the first one, or just let it fail
                    portfolio.plot_trades().write_html(charts["trades"])
                except Exception: pass
                
                try:
                    portfolio.plot_underwater().write_html(charts["underwater"])
                except Exception: pass
                
                try:
                    portfolio.plot_value().write_html(charts["value"])
                except Exception: pass

                try:
                    portfolio.plot_drawdowns().write_html(charts["drawdowns"])
                except Exception: pass

                try:
                    portfolio.plot_cum_returns().write_html(charts["returns"])
                except Exception: pass

                try:
                    portfolio.plot_cash_flow().write_html(charts["cash"])
                except Exception: pass
        except Exception:
            pass

        self.results = {
            "total_return_pct": total_ret,
            "win_rate": win_rate,
            "total_trades": len(self.trades),
            "net_profit": net_profit,
            "best_trade": best_trade,
            "worst_trade": worst_trade,
            "avg_trade_pct": avg_trade,
            "final_balance": final_balance,
            "max_drawdown_pct": max_dd,
            "avg_hold_hours": avg_hold_hours,
            "profit_factor": profit_factor,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "calmar_ratio": calmar,
            "recovery_factor": recovery,
            "buy_hold_pct": buy_hold,
            "symbol_stats": sym_stats,
            "equity_history": self.equity_history,
            "returns_history": self.returns_history,
            "drawdown_history": self.drawdown_history,
            "price_history": self.price_history,
            "timestamp_history": all_timestamps,
            "full_stats": full_stats_clean,
            "charts": charts
        }

        if on_progress:
            on_progress(1.0)
            
        return self.results