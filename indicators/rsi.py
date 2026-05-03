import pandas as pd
import pandas_ta_classic as ta
from indicators.constants import IndicatorConstants

class RSI:
    def __init__(self, df, length=IndicatorConstants.RSI_LENGTH):
        self.length = length
        self.df = df.copy()
        self._calculate()

    def _calculate(self):
        dfs = []
        for symbol in self.df["symbol"].unique():
            df_s = self.df[self.df["symbol"] == symbol].copy()
            df_s["RSI"] = ta.rsi(close=df_s["close"], length=self.length)
            dfs.append(df_s)
        self.df = pd.concat(dfs).sort_index()
