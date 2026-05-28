# Eggshell Backtester

Ultra-fast TUI-based cryptocurrency backtesting engine. Connects directly to Binance for historical data, uses VectorBT for Numba-accelerated vectorized backtesting, and ships with a modular strategy ecosystem backed by AI and workflow automation.

## Features
- **Modular Strategy Registry**: Strategies auto-discovered from `src/strategies/` and the `Strategies-eggshell` git submodule. No manual wiring needed.
- **DUAL_STRATEGY Mode**: Combine any two strategies with AND / OR signal logic.
- **VectorBT Engine**: Sub-second backtesting over tens of thousands of candles.
- **Rich TUI Dashboard**: Interactive terminal dashboard with live progress tracking and log streaming.
- **Interactive HTML Charts**: Plotly-powered portfolio value, underwater, and drawdown charts.
- **AI Integration**: Ollama running `qwen2.5:0.5b` (direct) and `0xroyce/plutus:latest` (via n8n sentiment webhook).

---

## Quick Start

### Local Python
Ensure you have the required dependencies and a virtual environment set up:
```bash
git clone --recurse-submodules https://github.com/galgo2077/Eggshell-Backtester.git
cd Eggshell-Backtester
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python src/main.py
```

---

## Architecture

```text
Eggshell-Backtester/
├── config/                   # settings persistence (ui_settings.json)
├── docs/                     # diagrams, install guides, documentation
├── reports/                  # charts/, results/, errors/ (git-ignored content)
├── requirements.txt
└── src/
    ├── main.py               # CLI entry point
    ├── core/
    │   ├── signal_logic.py   # strategy dispatch + on_progress callback
    │   ├── backtest_engine.py
    │   └── constants.py      # CONFIG_REGISTRY (auto-built from STRATEGY_REGISTRY)
    ├── binance_service/
    │   ├── dataframe.py      # historical data fetch + parquet cache
    │   └── connect.py        # Binance API client
    ├── ui/
    │   └── tui.py            # Textual app — BacktestApp
    └── strategies/
        ├── __init__.py       # STRATEGY_REGISTRY auto-discover (local + submodule)
        ├── Ema_cross/        # EMA cross system (local)
        └── Strategies-eggshell/   # git submodule
            ├── Elliot_bollinger/  # Bollinger Wave + Ollama AI signals
            └── Sentiment_proxy/   # n8n webhook sentiment strategy
```

---

## Strategy Blueprint

Every strategy lives in its own package inside `src/strategies/` (or the `Strategies-eggshell` submodule). The registry auto-discovers any directory that has `__init__.py`, `strategy.py`, and `constants.py`.

### Minimal strategy scaffold

**`constants.py`**
```python
STRATEGY_NAME = "MY_STRATEGY"
RSI_PERIOD = 14
OVERSOLD = 30

CONFIG_ENTRIES = [
    {"Key": "RSI_PERIOD", "Type": "int", "Category": "STRATEGY", "Label": "RSI Length"},
    {"Key": "OVERSOLD",   "Type": "float", "Category": "RISK",   "Label": "Entry Level"},
]
```

**`strategy.py`**
```python
from strategies.base_strategy import BaseStrategy
from . import constants

class MyStrategy(BaseStrategy):
    def apply_indicators(self):
        period = self.params.get("RSI_PERIOD", constants.RSI_PERIOD)
        delta = self.df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=period).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
        self.df['RSI'] = 100 - (100 / (1 + gain / loss))
        return self.df

    def generate_signals(self):
        lvl = self.params.get("OVERSOLD", constants.OVERSOLD)
        self.df["buy"]  = self.df['RSI'] <= lvl
        self.df["sell"] = self.df['RSI'] >= 70
        return self.df
```

Drop the package into `src/strategies/` — it appears in the TUI on next launch automatically.

---

## Module Diagram
See [`estructura.mmd`](estructura.mmd) (render at [mermaid.live](https://mermaid.live)).
