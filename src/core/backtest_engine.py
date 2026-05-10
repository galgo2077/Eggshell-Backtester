from core.constants import BacktestConstants

import os
import traceback
import pandas as pd
import numpy as np
import vectorbt as vbt


def _safe(val, default=0.0):
    return default if pd.isna(val) else val


class BacktestEngine:
    def __init__(self, signals_df: pd.DataFrame, initial_balance: float | None = None,
                 position_size_pct: float = 100.0, cooldown: int = 0,
                 accumulate: bool = False):
        self.df = signals_df.copy()
        self.initial_balance = initial_balance or BacktestConstants.INITIAL_BALANCE
        self.position_size_pct = position_size_pct
        self.cooldown = cooldown
        self.accumulate = accumulate
        self.results: dict = {}
        self.trades: list[dict] = []

    def run(self, on_progress: callable = None):
        if on_progress:
            on_progress(0.1)

        if not isinstance(self.df.index, pd.DatetimeIndex):
            self.df.index = pd.to_datetime(self.df.index)

        # Pivot signals into per-symbol columns
        try:
            close_df = self.df.set_index([self.df.index, 'symbol'])['close'].unstack('symbol')
            buy_df   = self.df.set_index([self.df.index, 'symbol'])['buy'].unstack('symbol').fillna(False).astype(bool)
            sell_df  = self.df.set_index([self.df.index, 'symbol'])['sell'].unstack('symbol').fillna(False).astype(bool)
        except Exception:
            close_df = self.df.pivot_table(index=self.df.index, columns='symbol', values='close')
            buy_df   = self.df.pivot_table(index=self.df.index, columns='symbol', values='buy',  aggfunc='any').fillna(False).astype(bool)
            sell_df  = self.df.pivot_table(index=self.df.index, columns='symbol', values='sell', aggfunc='any').fillna(False).astype(bool)

        # Force exit on the last candle
        if not sell_df.empty:
            sell_df.iloc[-1] = True

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
            on_progress(0.4)

        size_df = pd.DataFrame(np.nan, index=close_df.index, columns=close_df.columns)

        if self.accumulate:
            # Fixed dollar per entry: $1000 × 1% = $10/trade → max 100 trades before cash runs out
            pos_size = round((self.position_size_pct / 100.0) * self.initial_balance, 2)
            size_df[buy_df]  = pos_size
            size_df[sell_df] = np.inf   # liquidate entire accumulated position at once
            size_type = 'value'
        else:
            # Dynamic: each entry uses X% of current available cash
            size_df[buy_df]  = self.position_size_pct / 100.0
            size_df[sell_df] = 1.0      # close 100% of position
            size_type = 'percent'

        portfolio = vbt.Portfolio.from_signals(
            close=close_df,
            entries=buy_df,
            exits=sell_df,
            init_cash=self.initial_balance,
            size=size_df,
            size_type=size_type,
            cash_sharing=True,
            call_seq='auto',
            accumulate=self.accumulate,
            group_by=True,
        )

        if on_progress:
            on_progress(0.8)

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
        except Exception:
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

        formatted_trades = []
        sym_stats = {}
        wins = 0

        if not vbt_trades.empty:
            for _, r in vbt_trades.iterrows():
                sym = str(r['Column']) if 'Column' in r else "Unknown"
                if isinstance(r.get('Column'), tuple):
                    sym = r['Column'][0]

                ret     = r['Return']
                pnl     = r['PnL']
                qty     = r['Size']
                b_price = r['Avg Entry Price']

                if ret > 0:
                    wins += 1

                formatted_trades.append({
                    "symbol":              sym,
                    "buy_time":            r['Entry Timestamp'],
                    "sell_time":           r['Exit Timestamp'],
                    "buy_price":           b_price,
                    "sell_price":          r['Avg Exit Price'],
                    "profit_pct":          ret * 100.0,
                    "account_profit_pct":  pnl / self.initial_balance * 100.0 if self.initial_balance else 0.0,
                    "profit_usd":          pnl,
                    "investment":          qty * b_price,
                    "quantity":            qty,
                    "reason":              "Buy Sig -> Sell Sig",
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
            buy_hold = ((close_df.iloc[-1] - close_df.iloc[0]) / close_df.iloc[0]).mean() * 100.0

        charts = self._generate_charts(close_df, formatted_trades, portfolio)

        if on_progress:
            on_progress(1.0)

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
        }
        return self.results

    def _generate_charts(self, close_df, formatted_trades, portfolio) -> dict:
        proj_root  = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        charts_dir = os.path.join(proj_root, "reports", "charts")
        charts = {
            "main":       os.path.join(charts_dir, "vectorbt_report.html"),
            "trades":     os.path.join(charts_dir, "vectorbt_trades.html"),
            "underwater": os.path.join(charts_dir, "vectorbt_underwater.html"),
            "value":      os.path.join(charts_dir, "vectorbt_value.html"),
            "drawdowns":  os.path.join(charts_dir, "vectorbt_drawdowns.html"),
            "returns":    os.path.join(charts_dir, "vectorbt_returns.html"),
            "cash":       os.path.join(charts_dir, "vectorbt_cash.html"),
        }
        if close_df.empty:
            return charts

        try:
            os.makedirs(charts_dir, exist_ok=True)
            self._write_trades_chart(close_df, formatted_trades, charts["trades"])
            for key, method in [
                ("main",       portfolio.plot),
                ("underwater", portfolio.plot_underwater),
                ("value",      portfolio.plot_value),
                ("drawdowns",  portfolio.plot_drawdowns),
                ("returns",    portfolio.plot_cum_returns),
                ("cash",       portfolio.plot_cash_flow),
            ]:
                try:
                    method().write_html(charts[key])
                except Exception:
                    pass
        except Exception as e:
            self._log_error(f"chart generation: {e}")
        return charts

    def _write_trades_chart(self, close_df, formatted_trades, path: str):
        import plotly.graph_objects as go
        colors = ['#818cf8', '#34d399', '#fb7185', '#fbbf24', '#22d3ee', '#a78bfa']
        fig = go.Figure()

        for idx, symbol in enumerate(close_df.columns):
            color = colors[idx % len(colors)]
            fig.add_trace(go.Scatter(
                x=close_df.index, y=close_df[symbol],
                mode='lines', name=f'{symbol} Price',
                line=dict(color=color, width=2), opacity=0.85,
            ))
            sym_trades = [t for t in formatted_trades if t['symbol'] == symbol]
            if sym_trades:
                fig.add_trace(go.Scatter(
                    x=[t['buy_time'] for t in sym_trades],
                    y=[t['buy_price'] for t in sym_trades],
                    mode='markers', name=f'{symbol} Buy',
                    marker=dict(symbol='triangle-up', size=12, color='#22c55e',
                                line=dict(color='#15803d', width=1.5)),
                    hovertemplate='<b>BUY %{text}</b><br>%{x}<br>$%{y:,.2f}<extra></extra>',
                    text=[symbol] * len(sym_trades),
                ))
                fig.add_trace(go.Scatter(
                    x=[t['sell_time'] for t in sym_trades],
                    y=[t['sell_price'] for t in sym_trades],
                    mode='markers', name=f'{symbol} Sell',
                    marker=dict(symbol='triangle-down', size=12, color='#ef4444',
                                line=dict(color='#b91c1c', width=1.5)),
                    hovertemplate='<b>SELL %{text}</b><br>%{x}<br>$%{y:,.2f}<extra></extra>',
                    text=[symbol] * len(sym_trades),
                ))

        fig.update_layout(
            title=dict(text='Market Execution Map — Buy & Sell Markers',
                       font=dict(color='#f8fafc', size=22, family='Arial')),
            paper_bgcolor='#0b0f19', plot_bgcolor='#111827',
            hovermode='x unified',
            legend=dict(font=dict(color='#94a3b8', size=11),
                        bgcolor='rgba(11,15,25,0.8)', bordercolor='#334155', borderwidth=1),
            xaxis=dict(title=dict(text='Date', font=dict(color='#94a3b8', size=12)),
                       tickfont=dict(color='#94a3b8'), gridcolor='#1f2937',
                       rangeslider=dict(visible=True)),
            yaxis=dict(title=dict(text='Price ($)', font=dict(color='#94a3b8', size=12)),
                       tickfont=dict(color='#94a3b8'), gridcolor='#1f2937'),
            margin=dict(l=50, r=50, t=80, b=50),
        )
        fig.write_html(path)

    def _log_error(self, msg: str):
        proj_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        err_dir   = os.path.join(proj_root, "reports", "errors")
        os.makedirs(err_dir, exist_ok=True)
        with open(os.path.join(err_dir, "error.log"), "a") as f:
            f.write(f"{msg}\n{traceback.format_exc()}\n")
