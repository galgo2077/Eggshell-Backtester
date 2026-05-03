import os

class ConnectConstantsBinance:
    def __init__(self):
        self.API_KEY = os.environ.get("BINANCE_API_KEY", "")
        self.API_SECRET = os.environ.get("BINANCE_API_SECRET", "")
        self.START_DATE = "1 Jan, 2023"  # Fetching more history for backtest

class DataframeConstantsBinance:
    def __init__(self):
        self.ACTIVES = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT", "MATICUSDT", "DOTUSDT", "AVAXUSDT"]
        self.KLINE_INTERVAL = "1h"  # Using 1h for more granular backtesting
        self.KLINE_COLUMNS = [
            "timestamp", "open", "high", "low", "close", "volume",
            "close_time", "quote_volume", "trades",
            "taker_base", "taker_quote", "ignore",
        ]
        self.DROP_COLUMNS = [
            "close_time", "quote_volume", "trades",
            "taker_base", "taker_quote", "ignore",
        ]
        
class BacktestConstants:
    INITIAL_BALANCE = 1000.0
    TAKE_PROFIT_PCT = 0.05  # 5% target
    STOP_LOSS_PCT = 0.02    # 2% stop