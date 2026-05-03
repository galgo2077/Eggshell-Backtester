import pandas as pd
import pandas_ta_classic as ta
from indicators.constants import IndicatorConstants

class MFI:
    def __init__(self, df, length=IndicatorConstants.MFI_LENGTH):
        self.length = length
        self.df = df.copy()
        self._calculate()

    def _calculate(self):
        dfs = []
        for symbol in self.df["symbol"].unique():
            df_s = self.df[self.df["symbol"] == symbol].copy()
            df_s["MFI"] = ta.mfi(
                high=df_s["high"], low=df_s["low"], close=df_s["close"], volume=df_s["volume"],
                length=self.length
            )
            dfs.append(df_s)
        self.df = pd.concat(dfs).sort_index()
