from core.constants import ConnectConstantsBinance

from datetime import datetime
from binance.client import Client

class Connect:
    def __init__(self):
        self.constants = ConnectConstantsBinance()
        # Initialize client. If keys are missing, it will still work for public data.
        self.client = Client(self.constants.API_KEY, self.constants.API_SECRET)
        self._health_check()

    def _health_check(self):
        try:
            klines = self.client.get_historical_klines(
                symbol="BTCUSDT",
                interval=Client.KLINE_INTERVAL_1DAY,
                start_str=self.constants.START_DATE,
            )
        except Exception:
            pass