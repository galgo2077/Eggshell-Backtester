from indicators.constants import IndicatorConstants
from strategies.ema_cross import EMACrossStrategy

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
            **kwargs
        }
        
        self.df = df.copy()
        
        # Initialize Strategy (Modular)
        # In a fully modular setup, this could be passed as an argument
        self.strategy = EMACrossStrategy(self.df, **self.params)
        
        # Execute Pipeline
        self.df = self.strategy.apply_indicators()
        self.df = self.strategy.generate_signals()
        
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