import pandas as pd
import numpy as np

from . import constants

class EMACrossStrategy:
    def __init__(self, df, **kwargs):
        self.df = df.copy()
        self.params = kwargs

    def apply_indicators(self):
        # NATIVE EMA CALCULATION
        if self.params.get("ENABLED_EMA", constants.ENABLED_EMA):
            fast = self.params.get("FAST_EMA", constants.FAST_EMA)
            slow = self.params.get("SLOW_EMA", constants.SLOW_EMA)
            
            # No inner symbol loop needed as DataFrame contains single asset
            self.df["FAST_EMA"] = self.df["close"].ewm(span=fast, adjust=False).mean()
            self.df["SLOW_EMA"] = self.df["close"].ewm(span=slow, adjust=False).mean()
        
        # NATIVE MFI CALCULATION
        if self.params.get("ENABLED_MFI", constants.ENABLED_MFI):
            length = self.params.get("MFI_LENGTH", constants.MFI_LENGTH)
            
            typical_price = (self.df["high"] + self.df["low"] + self.df["close"]) / 3.0
            money_flow = typical_price * self.df["volume"]
            
            typical_price_diff = typical_price.diff(1)
            pos_flow = money_flow.where(typical_price_diff > 0, 0.0)
            neg_flow = money_flow.where(typical_price_diff < 0, 0.0)
            
            pos_mf = pos_flow.rolling(window=length).sum()
            neg_mf = neg_flow.rolling(window=length).sum()
            
            mfi_ratio = pos_mf / neg_mf.replace(0.0, np.nan)
            self.df["MFI"] = (100.0 - (100.0 / (1.0 + mfi_ratio))).fillna(50.0)
            
        return self.df

    def generate_signals(self):
        self.df["buy"] = False
        self.df["sell"] = False
        
        if not self.params.get("ENABLED_EMA", constants.ENABLED_EMA):
            return self.df

        if "FAST_EMA" not in self.df.columns or "SLOW_EMA" not in self.df.columns:
            return self.df

        # Generate EMA cross conditions
        fast_above_slow = self.df["FAST_EMA"] > self.df["SLOW_EMA"]
        fast_below_slow = self.df["FAST_EMA"] < self.df["SLOW_EMA"]
        
        cross_up = fast_above_slow & (~fast_above_slow).shift(1).fillna(False)
        cross_down = fast_below_slow & (~fast_below_slow).shift(1).fillna(False)

        # Risk Confirmations: MFI Logic Implementation
        buy_condition = cross_up.copy()
        sell_condition = cross_down.copy()

        if self.params.get("ENABLED_MFI", constants.ENABLED_MFI) and "MFI" in self.df.columns:
            buy_lvl = self.params.get("BUY_LEVEL", constants.BUY_LEVEL)
            sell_lvl = self.params.get("SELL_LEVEL", constants.SELL_LEVEL)
            
            # Confirmed cross UP only if asset is oversold/at loading levels
            buy_condition = buy_condition & (self.df["MFI"] <= buy_lvl)
            # Confirmed cross DOWN only if asset is overbought/exiting levels
            sell_condition = sell_condition & (self.df["MFI"] >= sell_lvl)

        self.df["buy"] = buy_condition

        if self.params.get("ENABLED_SELL", constants.ENABLED_SELL):
            self.df["sell"] = sell_condition
        # When disabled: sell=False everywhere; engine closes all positions on the last candle
                        
        return self.df

if __name__ == "__main__":
    # Simple localized testing
    dates = pd.date_range("2023-01-01", periods=100, freq="h")
    data = {
        "timestamp": dates,
        "symbol": "BTCUSDT",
        "close": np.random.uniform(20000, 30000, size=100),
        "high": np.random.uniform(30000, 31000, size=100),
        "low": np.random.uniform(19000, 20000, size=100),
        "volume": np.random.uniform(100, 1000, size=100)
    }
    test_df = pd.DataFrame(data).set_index("timestamp")
    
    strat = EMACrossStrategy(test_df, ENABLED_EMA=True, FAST_EMA=9, SLOW_EMA=21)
    test_df = strat.apply_indicators()
    test_df = strat.generate_signals()
    
    print("\n--- COMPONENT TEST SUCCESSFUL ---")
    print(test_df[["symbol", "close", "FAST_EMA", "SLOW_EMA", "buy", "sell"]].tail(10))
