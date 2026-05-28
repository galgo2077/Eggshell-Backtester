"""Ollama integration: availability check, text generation, and glossary keyword highlighting."""
import re

_SETUP_MODEL = "plutus"

_SETUP_GLOSSARY: dict[str, str] = {
    "EMA Cross":        "Buy when the fast EMA crosses above the slow EMA; sell when it crosses below.",
    "EMA":              "Exponential Moving Average — weights recent prices more heavily than older ones.",
    "Elliot Bollinger": "Strategy combining Elliott Wave pivot detection with Bollinger Band radius entries.",
    "pyramiding":       "Stacking multiple buy entries per asset before any position closes.",
    "cash sharing":     "All assets compete for the same shared capital pool instead of isolated budgets.",
    "sell at end":      "Force-close all open positions on the final candle of the backtest window.",
    "cooldown":         "Candles to wait after a position closes before a new entry is allowed.",
    "budget per trade": "% of total portfolio capital allocated to each individual buy signal.",
    "commission":       "Fee per trade as % of trade value (Binance spot charges ~0.1%).",
    "slippage":         "Execution cost: buys fill slightly above, sells slightly below signal price.",
    "stop loss":        "Pre-set price level that automatically closes a losing position.",
    "take profit":      "Pre-set price level that automatically closes a winning position in profit.",
    "allocation":       "How capital is split across multiple assets as % of total balance.",
    "conflict mode":    "Action taken when a buy AND sell signal fire on the same candle.",
    "random walk":      "Single synthetic price path generated with Geometric Brownian Motion.",
    "Monte Carlo":      "Batch of many independent synthetic paths to test strategy robustness.",
    "GBM":              "Geometric Brownian Motion — stochastic process used to simulate prices.",
    "drift":            "Mean directional trend per bar (positive = average upward bias).",
    "volatility":       "Std deviation of returns per bar (higher = wilder simulated swings).",
    "long only":        "Only buy signals execute; sell signals close positions (no short selling).",
}


def _list_ollama_models() -> list[str]:
    """Return all model names available in the local Ollama server, or [] on failure."""
    import urllib.request, json
    try:
        data = json.loads(
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2).read()
        )
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def _ollama_model_available(model: str = _SETUP_MODEL) -> bool:
    """Return True if Ollama server is reachable and the model is installed."""
    prefix = model.split(":")[0]
    return any(m.startswith(prefix) for m in _list_ollama_models())


def _ollama_generate(prompt: str, model: str = _SETUP_MODEL, timeout: int = 45) -> str:
    """Call Ollama HTTP API synchronously and return the response text."""
    import urllib.request, json
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode()).get("response", "")


def _highlight_keywords(text: str) -> str:
    """Wrap known glossary terms with blue+underline Rich markup (single pass, longest first)."""
    terms   = sorted(_SETUP_GLOSSARY.keys(), key=len, reverse=True)
    pattern = re.compile(r'\b(' + '|'.join(re.escape(t) for t in terms) + r')\b', re.IGNORECASE)
    return pattern.sub(r'[bold #4499ff][u]\1[/u][/bold #4499ff]', text)
