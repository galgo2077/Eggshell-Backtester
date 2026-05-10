from strategies.Ema_cross import EMACrossStrategy

"""
SignalLogic — Modular coordinator for applying indicators and generating signals.
"""

import pandas as pd


class SignalLogic:
    def __init__(self, df, 
                 ENABLED_EMA: bool = True, 
                 FAST_EMA: int = 9, 
                 SLOW_EMA: int = 21, 
                 ENABLED_MFI: bool = False,
                 MFI_LENGTH: int = 14,
                 ENABLED_SELL: bool = True, 
                 BUY_LEVEL: float = 30.0, 
                 SELL_LEVEL: float = 70.0, 
                 on_progress: callable = None,
                 **kwargs):
        
        self.params = {
            "ENABLED_EMA": ENABLED_EMA,
            "FAST_EMA": FAST_EMA,
            "SLOW_EMA": SLOW_EMA,
            "ENABLED_MFI": ENABLED_MFI,
            "MFI_LENGTH": MFI_LENGTH,
            "ENABLED_SELL": ENABLED_SELL,
            "BUY_LEVEL": BUY_LEVEL,
            "SELL_LEVEL": SELL_LEVEL,
            "on_progress": on_progress,
            **kwargs
        }
        
        self.input_df = df.copy()
        self.processed_dfs = []
        
        strategy_name = self.params.get("STRATEGY", "EMA_CROSS")
        
        # Partition incoming dataframe by symbol to guarantee technical correctness per-asset
        unique_symbols = self.input_df["symbol"].unique() if "symbol" in self.input_df.columns else [None]
        
        for sym in unique_symbols:
            if sym is not None:
                current_df = self.input_df[self.input_df["symbol"] == sym].copy()
            else:
                current_df = self.input_df.copy()
                
            if current_df.empty:
                continue
                
            # Initialize Strategy for current partitioned chunk
            if strategy_name == "ELLIOT_BOLLINGER":
                from strategies.Elliot_bollinger import ElliotBollingerStrategy
                strategy = ElliotBollingerStrategy(current_df, **self.params)
            else:
                strategy = EMACrossStrategy(current_df, **self.params)
            
            # Execute Pipeline on single-asset chunk
            current_df = strategy.apply_indicators()
            current_df = strategy.generate_signals()
            
            self.processed_dfs.append(current_df)
            
        # Recombine results maintaining integrity
        if self.processed_dfs:
            self.df = pd.concat(self.processed_dfs).sort_index()
        else:
            self.df = self.input_df.copy()
            self.df["buy"] = False
            self.df["sell"] = False
        
        # Build Result Dataframes
        self.indicators = self._build_indicators_df()
        self.signals    = self._build_signals_df()

    def _build_indicators_df(self):
        # Dynamically include columns that are not OHLCV or metadata
        metadata_cols = ["open", "high", "low", "close", "volume", "buy", "sell"]
        cols = ["symbol"] + [c for c in self.df.columns if c not in metadata_cols and c != "symbol"]
        return self.df[cols].copy()

    def _build_signals_df(self):
        return self.df[["symbol", "close", "buy", "sell"]].copy()