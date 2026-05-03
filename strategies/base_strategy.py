import pandas as pd

class BaseStrategy:
    def __init__(self, df, **kwargs):
        self.df = df.copy()
        self.params = kwargs

    def apply_indicators(self):
        """Apply necessary indicators to self.df"""
        return self.df

    def generate_signals(self):
        """Generate 'buy' and 'sell' columns in self.df"""
        self.df["buy"] = False
        self.df["sell"] = False
        return self.df
