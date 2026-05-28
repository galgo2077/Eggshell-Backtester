import os

class ConnectConstantsBinance:
    def __init__(self):
        self.API_KEY = os.environ.get("BINANCE_API_KEY", "")
        self.API_SECRET = os.environ.get("BINANCE_API_SECRET", "")
        self.START_DATE = "1 Jan, 2023"

class DataframeConstantsBinance:
    def __init__(self):
        self.ACTIVES = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "ADAUSDT", "MATICUSDT", "DOTUSDT", "AVAXUSDT"]
        self.KLINE_INTERVAL = "1h"
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

from strategies import STRATEGY_REGISTRY

CONFIG_REGISTRY = []

for pkg_name, pkg_mod in STRATEGY_REGISTRY.items():
    const = getattr(pkg_mod, "constants", None)
    if const is None:
        continue
    config_entries = getattr(const, "CONFIG_ENTRIES", None)
    strategy_name = getattr(const, "STRATEGY_NAME", pkg_name.upper())
    if config_entries is None:
        continue
    for entry in config_entries:
        key = entry["Key"]
        default = getattr(const, key, None)
        label = entry.get("Label", key.replace("_", " ").title())
        CONFIG_REGISTRY.append({
            "Strategy": strategy_name,
            "Category": entry["Category"],
            "Key": key,
            "Type": entry["Type"],
            "Default": default,
            "Label": label,
        })

# DUAL STRATEGY — combine any two strategies with AND / OR signal logic
CONFIG_REGISTRY.extend([
    {"Strategy": "DUAL_STRATEGY", "Category": "STRATEGY", "Key": "STRATEGY_A", "Type": "str", "Default": "EMA_CROSS", "Label": "STRATEGY A"},
    {"Strategy": "DUAL_STRATEGY", "Category": "STRATEGY", "Key": "STRATEGY_B", "Type": "str", "Default": "ELLIOT_BOLLINGER", "Label": "STRATEGY B"},
    {"Strategy": "DUAL_STRATEGY", "Category": "STRATEGY", "Key": "CONDITION", "Type": "str", "Default": "AND", "Label": "SIGNAL CONDITION"},
])

CONFIG = CONFIG_REGISTRY

def build_strategy_schemas_from_config(cfg_list):
    schemas = {}
    for row in cfg_list:
        strat = row["Strategy"]
        cat   = row["Category"]
        key   = row["Key"]
        if strat not in schemas:
            schemas[strat] = {}
        if cat not in schemas[strat]:
            schemas[strat][cat] = {}
        schemas[strat][cat][key] = {
            "type":    row["Type"],
            "default": row["Default"],
            "label":   row["Label"],
        }
    return schemas

STRATEGY_SCHEMAS = build_strategy_schemas_from_config(CONFIG)


