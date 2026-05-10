# Eggshell Backtester v1.1

Eggshell Backtester is an ultra-fast, Terminal User Interface (TUI) based cryptocurrency backtesting engine. Designed for rapid iteration, Eggshell connects directly to Binance for historical data, leverages the **VectorBT** engine for Numba-accelerated vectorized backtesting, and features a structured, modular strategy injection ecosystem.

## 🚀 Features
- **Dynamic Blueprint Architecture**: Modernized modular framework separating each strategy into standardized independent packages.
- **Unified Schema Management**: A single source of configurations driving the Textual dashboard dynamically.
- **VectorBT Engine**: Sub-second backtesting over tens of thousands of candles.
- **Rich TUI Dashboard**: Fully interactive terminal dashboard featuring live progress tracking and log streaming.
- **Interactive HTML Charts**: Generates deep-dive analytics (Portfolio Value, Underwater maps, Drawdowns) automatically powered by Plotly.

---

## 💻 Getting Started

### 1. Requirements
Ensure you have the required dependencies installed:
```bash
pip install pandas numpy vectorbt-pro textual rich
```

### 2. Running the Application
Launch the terminal dashboard from the repository root by executing the main source module:
```bash
python src/main.py
```
*Note: Ensure you possess appropriate `.env` variables for Binance API access stored at the root level if necessary for newer data.*

---

## 🛠️ The Strategy Blueprint (How It Works)

Eggshell is strictly standardized. Every trading strategy conforms to a clean, inheritance-based contract. You no longer manipulate central core files to define your formulas; instead, you wrap your ideas into self-contained packages inside the `src/strategies/` container.

### Project Architecture Overview
```text
Eggshell-Backtester/
├── config/                # System parameters & settings persistence
├── reports/               # Live charting outputs and error stacks
└── src/
    ├── core/              # Engine heart: signal_logic, backtest, & central registry
    ├── binance_service/   # Historical datastreams & memory caches
    └── strategies/        # THE MODULAR CONTAINER FOR STRATEGY PACKAGES
        ├── base_strategy.py           # Global abstract base blueprint
        ├── Elliot_bollinger/          # Dynamic Bollinger Wave Package
        └── Ema_cross/                 # Standard Cross System Template
```

### Creating a New Strategy

#### Step 1: Scaffold the Package
Create a new directory inside `src/strategies/`, for example `src/strategies/My_New_Strat/`. Populate it with three files:
- `__init__.py`: Standard empty module marker.
- `constants.py`: To contain default numeric/bool parameters.
- `strategy.py`: Where the algorithmic logic is written.

#### Step 2: Write local constants
In `My_New_Strat/constants.py`:
```python
ENABLED_RSI = True
RSI_PERIOD = 14
OVERBOUGHT = 70
OVERSOLD = 30
```

#### Step 3: Implement the Blueprint
In `My_New_Strat/strategy.py`, extend `BaseStrategy` and replace the default methods. The base automatically yields single-symbol DataFrames, keeping calculations completely linear.

```python
from strategies.base_strategy import BaseStrategy
from . import constants
import pandas as pd

class MyNewStrategy(BaseStrategy):
    def apply_indicators(self):
        # Read from provided run parameters OR local default constants
        period = self.params.get("RSI_PERIOD", constants.RSI_PERIOD)
        
        # Write your standard pandas computation logic
        delta = self.df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
        rs = gain / loss
        self.df['RSI'] = 100 - (100 / (1 + rs))
        return self.df

    def generate_signals(self):
        self.df["buy"] = False
        self.df["sell"] = False
        
        buy_lvl = self.params.get("OVERSOLD", constants.OVERSOLD)
        
        # Trigger signals instantly
        self.df["buy"] = (self.df['RSI'] <= buy_lvl)
        self.df["sell"] = (self.df['RSI'] >= 70)
        return self.df
```

#### Step 4: Link to Core
Open `src/core/constants.py`. Add your strategy mapping to the `STRATEGY_SCHEMAS` global dictionary to make it appear in the TUI instantly:

```python
# Import local defaults first
from strategies.My_New_Strat import constants as my_const

STRATEGY_SCHEMAS = {
    "MY_NEW_STRATEGY": {
        "STRATEGY": {
             "RSI_PERIOD": {"type": "int", "default": my_const.RSI_PERIOD, "label": "RSI Length"},
        },
        "RISK": {
             "OVERSOLD": {"type": "float", "default": my_const.OVERSOLD, "label": "Entry Oversold Level"},
        }
    }
}
```
*And finally, register the instantiation link inside `src/core/signal_logic.py` within the factory builder.*

---

## 📈 Viewing Analytics
After launching simulations, navigate to the **CHART** tab inside the dashboard. Fully interactive Plotly reports are pushed instantly into your local `reports/charts/` folder, including:
- **Market Execution Map**: Precise overlay of triangle-markers indicating precise fill timestamps.
- **Underwater Chart**: Visualizes the continuous historical drawdown timeline.
- **Returns Flow**: Aggregated cumulative account equity expansion.

Simply hit the specific chart button in the UI and your desktop default web browser loads the interactive map instantly.
