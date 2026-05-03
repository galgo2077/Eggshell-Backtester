import pandas as pd
from indicators.constants import IndicatorConstants

class EMA:
    def __init__(self, df, fast_span=IndicatorConstants.FAST_EMA_SPAN, slow_span=IndicatorConstants.SLOW_EMA_SPAN):
        self.fast_span = fast_span
        self.slow_span = slow_span
        self.df = df.copy()
        self._calculate()

    def _calculate(self):
        dfs = []
        for symbol in self.df["symbol"].unique():
            df_s = self.df[self.df["symbol"] == symbol].copy()
            df_s["FAST_EMA"] = df_s["close"].ewm(span=self.fast_span, adjust=False).mean()
            df_s["SLOW_EMA"] = df_s["close"].ewm(span=self.slow_span, adjust=False).mean()
            dfs.append(df_s)
        self.df = pd.concat(dfs).sort_index()
