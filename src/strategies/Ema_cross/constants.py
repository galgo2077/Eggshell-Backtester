"""
Default Constants for EMA Cross Strategy
"""

STRATEGY_NAME = "EMA_CROSS"

CONFIG_ENTRIES = [
    {"Key": "ENABLED_EMA", "Type": "bool", "Category": "STRATEGY", "Label": "ENABLED EMA"},
    {"Key": "FAST_EMA", "Type": "int", "Category": "STRATEGY", "Label": "FAST EMA"},
    {"Key": "SLOW_EMA", "Type": "int", "Category": "STRATEGY", "Label": "SLOW EMA"},
    {"Key": "ENABLED_MFI", "Type": "bool", "Category": "STRATEGY", "Label": "ENABLED MFI"},
    {"Key": "MFI_LENGTH", "Type": "int", "Category": "STRATEGY", "Label": "MFI LENGTH"},
    {"Key": "ENABLED_SELL", "Type": "bool", "Category": "RISK", "Label": "ENABLE SELL"},
    {"Key": "BUY_LEVEL", "Type": "float", "Category": "RISK", "Label": "MFI BUY LEVEL"},
    {"Key": "SELL_LEVEL", "Type": "float", "Category": "RISK", "Label": "MFI SELL LEVEL"},
]

# Strategy Defaults
ENABLED_EMA = True
FAST_EMA = 9
SLOW_EMA = 21

# MFI Defaults
ENABLED_MFI = False
MFI_LENGTH = 14

# Risk Defaults
ENABLED_SELL = True
BUY_LEVEL = 30.0
SELL_LEVEL = 70.0
