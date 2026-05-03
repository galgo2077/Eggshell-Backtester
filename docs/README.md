# 🥚 Eggshell Backtester

Eggshell is a high-performance, broker-agnostic backtesting engine designed for professional strategy evaluation. While it currently features a robust **Binance Connector**, its modular architecture allows for easy integration with any exchange or data provider.

## 🧠 How it Works

1.  **Data Connectors**: The system uses specialized services (like `binance_service`) to fetch historical market data. These services are designed to be swapped or extended for other brokers (e.g., Bybit, OKX, or local CSV files).
2.  **Indicator Studio**: A modular pipeline applies technical indicators (RSI, CCI, MFI, Stochastic, etc.) to the raw data. 
3.  **Signal Logic**: The engine calculates a "Normalized Average" of all enabled indicators to generate cross-indicator signals.
4.  **Backtest Engine**: A realistic simulation environment that respects capital constraints, position sizing, and risk management rules.

---

## 🛠️ Installation

Choose the guide for your operating system:
- [🐧 Linux Installation Guide](INSTALLATION_LINUX.md)
- [🪟 Windows Installation Guide](INSTALLATION_WINDOWS.md)

---

## ⚙️ Customization Guide

### 1. Adding New Symbols
To add more assets to the selection menu:
1.  Open `Elliot/constants.py`.
2.  Locate `DataframeConstantsBinance.ACTIVES` (or the equivalent for your connector).
3.  Add the symbol (e.g., `"LINKUSDT"`).

### 2. Adding New Indicators
1.  **Create the File**: Add a new `.py` file in `Elliot/indicators/` (e.g., `sma.py`).
2.  **Implement the Class**: Follow the pattern in `rsi.py`.
3.  **Register in Logic**:
    *   Import it in `Elliot/signal_logic.py`.
    *   Add it to the `_apply_indicators` method.

### 3. Modifying the Strategy
The core strategy logic resides in `Elliot/signal_logic.py`. You can change the "promedio" calculation to implement weighted averages, trend-following logic, or mean-reversion conditions.

### 4. Adding New Brokers/Data Sources
To add a new data source:
1.  Create a new service folder (e.g., `Elliot/bybit_service/`).
2.  Implement a `Dataframe` class that returns a Pandas DataFrame with the standard columns (`timestamp`, `open`, `high`, `low`, `close`, `volume`).
3.  Update the entry point in `main.py` or the TUI to use your new connector.

---

## 📜 License
MIT License - Developed for Advanced Strategy Testing.
