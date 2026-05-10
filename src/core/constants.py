import os
import pandas as pd

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

from strategies.Ema_cross import constants as ema_const
from strategies.Elliot_bollinger import constants as elliot_const

# ── CENTRAL CONFIGURATION REGISTRY ────────────────────────────────────────────
# This defines the definitive state of all parameters across all strategies.
# Add new variables as rows to this table to expose them throughout the entire system instantly.

CONFIG_REGISTRY = [
    # EMA CROSS STRATEGY
    {"Strategy": "EMA_CROSS", "Category": "STRATEGY", "Key": "ENABLED_EMA", "Type": "bool", "Default": ema_const.ENABLED_EMA, "Label": "ENABLED EMA"},
    {"Strategy": "EMA_CROSS", "Category": "STRATEGY", "Key": "FAST_EMA", "Type": "int", "Default": ema_const.FAST_EMA, "Label": "FAST EMA"},
    {"Strategy": "EMA_CROSS", "Category": "STRATEGY", "Key": "SLOW_EMA", "Type": "int", "Default": ema_const.SLOW_EMA, "Label": "SLOW EMA"},
    {"Strategy": "EMA_CROSS", "Category": "STRATEGY", "Key": "ENABLED_MFI", "Type": "bool", "Default": ema_const.ENABLED_MFI, "Label": "ENABLED MFI"},
    {"Strategy": "EMA_CROSS", "Category": "STRATEGY", "Key": "MFI_LENGTH", "Type": "int", "Default": ema_const.MFI_LENGTH, "Label": "MFI LENGTH"},
    {"Strategy": "EMA_CROSS", "Category": "RISK", "Key": "ENABLED_SELL", "Type": "bool", "Default": ema_const.ENABLED_SELL, "Label": "ENABLE SELL"},
    {"Strategy": "EMA_CROSS", "Category": "RISK", "Key": "BUY_LEVEL", "Type": "float", "Default": ema_const.BUY_LEVEL, "Label": "BUY CONDITION (MFI)"},
    {"Strategy": "EMA_CROSS", "Category": "RISK", "Key": "SELL_LEVEL", "Type": "float", "Default": ema_const.SELL_LEVEL, "Label": "SELL CONDITION (MFI)"},
    
    # ELLIOTT BOLLINGER STRATEGY
    {"Strategy": "ELLIOT_BOLLINGER", "Category": "STRATEGY", "Key": "FAST_EMA", "Type": "int", "Default": elliot_const.EMA_FAST, "Label": "FAST EMA (EMA 10)"},
    {"Strategy": "ELLIOT_BOLLINGER", "Category": "STRATEGY", "Key": "MEDIUM_EMA", "Type": "int", "Default": elliot_const.EMA_MEDIUM, "Label": "MEDIUM EMA (EMA 20)"},
    {"Strategy": "ELLIOT_BOLLINGER", "Category": "STRATEGY", "Key": "SLOW_EMA", "Type": "int", "Default": elliot_const.EMA_SLOW, "Label": "SLOW EMA (EMA 50)"},
    {"Strategy": "ELLIOT_BOLLINGER", "Category": "STRATEGY", "Key": "BOLLINGER_SD_RATIO", "Type": "float", "Default": elliot_const.BOLLINGER_SD_RATIO, "Label": "SD RATIO (Y-AXIS)"},
    {"Strategy": "ELLIOT_BOLLINGER", "Category": "STRATEGY", "Key": "PIVOT_WINDOW_DIVISOR", "Type": "int", "Default": elliot_const.PIVOT_WINDOW_DIVISOR, "Label": "PIVOT WINDOW DIVISOR"},
    {"Strategy": "ELLIOT_BOLLINGER", "Category": "STRATEGY", "Key": "PIVOT_MIN_DIST_DIVISOR", "Type": "int", "Default": elliot_const.PIVOT_MIN_DIST_DIVISOR, "Label": "PIVOT MIN DIST DIVISOR"},
    {"Strategy": "ELLIOT_BOLLINGER", "Category": "RISK", "Key": "ENABLED_SELL", "Type": "bool", "Default": True, "Label": "ENABLE SELL"},
    {"Strategy": "ELLIOT_BOLLINGER", "Category": "RISK", "Key": "AI_ANALYSIS_INTERVAL_HOURS", "Type": "int", "Default": 24, "Label": "AI RE-ANALYSIS (HOURS)"},
]

# GENERATE DYNAMIC DATAFRAME REPRESENTATION
CONFIG = pd.DataFrame(CONFIG_REGISTRY)

def build_strategy_schemas_from_config(cfg_df):
    """
    Converts the flat configuration DataFrame into the hierarchical 
    dictionary structure utilized by the UI logic.
    """
    schemas = {}
    for _, row in cfg_df.iterrows():
        strat = row["Strategy"]
        cat = row["Category"]
        key = row["Key"]
        
        if strat not in schemas:
            schemas[strat] = {}
        if cat not in schemas[strat]:
            schemas[strat][cat] = {}
            
        schemas[strat][cat][key] = {
            "type": row["Type"],
            "default": row["Default"],
            "label": row["Label"]
        }
    return schemas

# EXPORT GLOBAL SCHEMAS 
STRATEGY_SCHEMAS = build_strategy_schemas_from_config(CONFIG)


def get_settings_dataframe():
    """
    Alias to existing systems requesting copy of configuration settings.
    """
    return CONFIG.copy()