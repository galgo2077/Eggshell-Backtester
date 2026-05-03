# Eggshell Backtester v1.0

Eggshell Backtester is an ultra-fast, Terminal User Interface (TUI) based cryptocurrency backtesting engine. Designed for rapid iteration, Eggshell connects directly to Binance for historical data, leverages the **VectorBT** engine for Numba-accelerated vectorized backtesting, and features a purely dynamic parameter injection system.

## 🚀 Features
- **Dynamic Introspection Architecture**: The User Interface builds itself based on your Python code! Simply add arguments to your Strategy class, and the UI will automatically generate inputs and switches.
- **VectorBT Engine**: Sub-second backtesting over tens of thousands of candles.
- **Rich TUI Dashboard**: Fully interactive terminal dashboard built with Textual, featuring live progress bars, aesthetic metrics, and trade logs.
- **Interactive HTML Charts**: Automatically generates deep-dive analytics (Drawdowns, Portfolio Value, Underwater charts, etc.) using VectorBT and Plotly.
- **Zero-Config State Persistence**: Strategy settings automatically save and load via `ui_settings.json`.

---

## 💻 Getting Started

### 1. Requirements
Ensure you have the required dependencies installed:
```bash
pip install pandas numpy vectorbt textual rich
```

### 2. Running the Application
Launch the terminal dashboard by running:
```bash
python main.py
```
*Note: For the CLI (Command Line Interface) version without the dashboard, you can run `python main.py --cli`.*

---

## 🛠️ The Dynamic Strategy Engine (How It Works)

Eggshell is built on a **100% modular, dynamically introspective architecture**. 

You do **not** need to touch UI code, layout definitions, or JSON configuration files to add new strategy parameters. The Textual UI literally reads the arguments of your `SignalLogic` class and generates the user interface on the fly.

### How to Add or Modify a Strategy

All strategy logic lives in `core/signal_logic.py`. 

#### Step 1: Define your parameters
Open `core/signal_logic.py`. Find the `__init__` function of the `SignalLogic` class. 
To add a new parameter to your strategy, simply add it as an argument with a **Type Hint** (`bool`, `int`, `float`) and a **Default Value**.

```python
class SignalLogic:
    def __init__(self, 
                 df, 
                 ENABLED_EMA: bool = True, 
                 FAST_EMA: int = 9, 
                 SLOW_EMA: int = 21, 
                 ENABLED_SELL: bool = True,
                 
                 # ---> ADD NEW PARAMETERS HERE! <---
                 USE_MACD: bool = False,
                 MACD_FAST: int = 12,
                 MACD_SLOW: int = 26,
                 
                 **kwargs):
        
        # Save them to the class instance
        self.ENABLED_EMA = ENABLED_EMA
        self.FAST_EMA = FAST_EMA
        self.SLOW_EMA = SLOW_EMA
        self.ENABLED_SELL = ENABLED_SELL
        
        # Save new parameters
        self.USE_MACD = USE_MACD
        self.MACD_FAST = MACD_FAST
        self.MACD_SLOW = MACD_SLOW
        
        self.df = df.copy()
        self._apply_indicators()
        self._generate_signals()
        self.indicators = self._build_indicators_df()
        self.signals    = self._build_signals_df()
```

> [!TIP]
> **What happens when you do this?**
> The moment you save the file and run `python main.py`, the TUI will instantly detect `USE_MACD`, `MACD_FAST`, and `MACD_SLOW`. 
> - It will create a **Toggle Switch** for `USE_MACD` because you typed `bool`.
> - It will create **Text Inputs** for `MACD_FAST` and `MACD_SLOW` because you typed `int`.
> - The inputs will pre-fill with `12` and `26`.
> - If you change them in the UI, they will automatically save to `ui_settings.json` for your next session!

#### Step 2: Write the math
Scroll down to the `_apply_indicators` method in the same file to calculate your new logic. You can use standard `pandas` calculations:

```python
    def _apply_indicators(self):
        # Existing EMA logic
        if self.ENABLED_EMA:
            self.df["FAST_EMA"] = self.df["close"].ewm(span=self.FAST_EMA, adjust=False).mean()
            self.df["SLOW_EMA"] = self.df["close"].ewm(span=self.SLOW_EMA, adjust=False).mean()

        # Your new logic!
        if self.USE_MACD:
            fast = self.df["close"].ewm(span=self.MACD_FAST, adjust=False).mean()
            slow = self.df["close"].ewm(span=self.MACD_SLOW, adjust=False).mean()
            self.df["MACD"] = fast - slow
```

#### Step 3: Define Buy/Sell signals
Scroll down to `_generate_signals`. You must populate `self.df["buy"]` and `self.df["sell"]` with boolean (`True`/`False`) values.

```python
    def _generate_signals(self):
        # Default states
        self.df["buy"] = False
        self.df["sell"] = False
        
        # Your custom trade entry triggers
        if self.ENABLED_EMA:
            fast_above_slow = self.df["FAST_EMA"] > self.df["SLOW_EMA"]
            cross_up = fast_above_slow & (~fast_above_slow).shift(1).fillna(False)
            self.df["buy"] = cross_up
```

#### Step 4: Add to output reports (Optional)
If you want to see your custom indicator values in the trade logs or terminal tables, add them to `_build_indicators_df`:

```python
    def _build_indicators_df(self):
        cols = ["symbol"]
        if self.ENABLED_EMA:
            cols.extend(["FAST_EMA", "SLOW_EMA"])
        if self.USE_MACD:
            cols.append("MACD")
            
        return self.df[cols].copy()
```

---

## 📈 Viewing Analytics
After a successful backtest, navigate to the **CHART** tab. Eggshell automatically generates fully interactive HTML reports:
- **Full Portfolio Chart**: Master view of entries and exits.
- **Top Drawdowns**: Highlights the 5 worst historical drawdown periods.
- **Underwater Chart**: Visualizes the depth and duration of your losses.
- **Cash Flow Balance**: Tracks liquid cash vs allocated margin.
- **Cumulative Returns**: Net ROI growth curve.

These charts are saved locally in `reports/charts/` and automatically open in your default web browser!
