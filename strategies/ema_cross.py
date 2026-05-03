import os
import sys

# Add the project root to sys.path to allow direct execution
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from strategies.base_strategy import BaseStrategy
    from indicators.ema import EMA
    from indicators.mfi import MFI
except ImportError:
    from base_strategy import BaseStrategy
    from indicators.ema import EMA
    from indicators.mfi import MFI

class EMACrossStrategy(BaseStrategy):
    def apply_indicators(self):
        # EMA
        if self.params.get("ENABLED_EMA", True):
            fast = self.params.get("FAST_EMA", 9)
            slow = self.params.get("SLOW_EMA", 21)
            ema = EMA(self.df, fast_span=fast, slow_span=slow)
            self.df = ema.df
        
        # MFI (Test Modularity)
        if self.params.get("ENABLED_MFI", False):
            length = self.params.get("MFI_LENGTH", 14)
            mfi = MFI(self.df, length=length)
            self.df = mfi.df
            
        return self.df

    def generate_signals(self):
        self.df["buy"] = False
        self.df["sell"] = False
        
        if not self.params.get("ENABLED_EMA", True):
            return self.df

        if "FAST_EMA" not in self.df.columns or "SLOW_EMA" not in self.df.columns:
            return self.df

        # Generate cross signals
        fast_above_slow = self.df["FAST_EMA"] > self.df["SLOW_EMA"]
        fast_below_slow = self.df["FAST_EMA"] < self.df["SLOW_EMA"]
        
        cross_up = fast_above_slow & (~fast_above_slow).shift(1).fillna(False)
        cross_down = fast_below_slow & (~fast_below_slow).shift(1).fillna(False)

        self.df["buy"] = cross_up
        
        enabled_sell = self.params.get("ENABLED_SELL", True)
        if enabled_sell:
            self.df["sell"] = cross_down
        else:
            # Force exit at the very end if sell signals are disabled
            if not self.df.empty:
                # We need to find the last index for each symbol
                for symbol in self.df["symbol"].unique():
                    symbol_indices = self.df[self.df["symbol"] == symbol].index
                    if not symbol_indices.empty:
                        self.df.loc[symbol_indices[-1], "sell"] = True
                        
        return self.df

if __name__ == "__main__":
    import numpy as np
    # Simple test data
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
    
    # Initialize and test
    strat = EMACrossStrategy(test_df, ENABLED_EMA=True, FAST_EMA=9, SLOW_EMA=21)
    test_df = strat.apply_indicators()
    test_df = strat.generate_signals()
    
    print("\n--- TEST RUN SUCCESSFUL ---")
    print(test_df[["symbol", "close", "FAST_EMA", "SLOW_EMA", "buy", "sell"]].tail(10))
