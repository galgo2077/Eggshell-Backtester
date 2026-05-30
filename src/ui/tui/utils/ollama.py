"""
Ollama integration: availability check, streaming text generation, and
glossary keyword highlighting.

v2 changes
----------
- _ollama_generate() now uses a **streaming** HTTP reader instead of
  ``stream=False``. This means tokens arrive as they are generated rather than
  buffering the entire response server-side, which eliminates the post-generation
  HTTP-transfer idle gap and allows the caller to display tokens live.

- All requests include ``num_batch=512`` in options so Ollama uses the optimal
  prompt-eval micro-batch size (aligned to CUDA warp boundaries).

- ``keep_alive=-1`` is set on every request so the model stays loaded in VRAM
  between consecutive backtests — no repeated cold-start overhead.

- _ollama_generate_streaming() accepts an optional ``on_token`` callback that is
  called with each token string as it arrives; useful for live TUI updates.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Callable, Optional

_SETUP_MODEL = "plutus"

# Ollama request options applied to every inference call.
# num_batch=512 aligns the prompt-eval micro-batch with CUDA warp size (32 threads × 16 warp pairs).
# keep_alive=-1 keeps the model resident in VRAM permanently.
_OLLAMA_OPTIONS: dict = {
    "num_batch":   512,
}

_OLLAMA_BASE_URL = "http://localhost:11434"

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
    try:
        data = json.loads(
            urllib.request.urlopen(f"{_OLLAMA_BASE_URL}/api/tags", timeout=2).read()
        )
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def _ollama_model_available(model: str = _SETUP_MODEL) -> bool:
    """Return True if Ollama server is reachable and the model is installed."""
    prefix = model.split(":")[0]
    return any(m.startswith(prefix) for m in _list_ollama_models())


def _ollama_generate_streaming(
    prompt: str,
    model: str = _SETUP_MODEL,
    on_token: Optional[Callable[[str], None]] = None,
    extra_options: Optional[dict] = None,
) -> str:
    """
    Call Ollama's streaming HTTP API and return the complete response text.

    Unlike the previous ``stream=False`` variant, this function reads tokens
    as they are generated rather than waiting for the full response to buffer.
    This eliminates the post-generation HTTP-transfer idle gap and allows the
    caller to display tokens live via the ``on_token`` callback.

    Parameters
    ----------
    prompt :
        The full prompt string sent to the model.
    model :
        Ollama model name.
    on_token :
        Optional callable invoked with each token string as it arrives.
        Called synchronously from this thread — keep it fast.
    extra_options :
        Additional Ollama options merged over ``_OLLAMA_OPTIONS``.

    Returns
    -------
    str
        The full generated text (concatenation of all token chunks).
    """
    opts = {**_OLLAMA_OPTIONS, **(extra_options or {})}
    payload = json.dumps({
        "model":      model,
        "prompt":     prompt,
        "stream":     True,
        "keep_alive": -1,
        "options":    opts,
    }).encode()

    req = urllib.request.Request(
        f"{_OLLAMA_BASE_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    chunks: list[str] = []
    with urllib.request.urlopen(req, timeout=None) as resp:
        for raw_line in resp:
            line = raw_line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            if data.get("done"):
                break

            tok = data.get("response", "")
            if tok:
                chunks.append(tok)
                if on_token is not None:
                    on_token(tok)

    return "".join(chunks)


def _ollama_generate(
    prompt: str,
    model: str = _SETUP_MODEL,
    on_token: Optional[Callable[[str], None]] = None,
) -> str:
    """
    Generate text via Ollama. Thin wrapper over _ollama_generate_streaming.

    This is the primary call-site used by the TUI. Accepts an optional
    ``on_token`` callback for live streaming display — pass a function that
    updates a UI widget to render tokens as they arrive.
    """
    return _ollama_generate_streaming(prompt, model=model, on_token=on_token)


def _highlight_keywords(text: str) -> str:
    """Wrap known glossary terms with blue+underline Rich markup (single pass, longest first)."""
    import re
    terms   = sorted(_SETUP_GLOSSARY.keys(), key=len, reverse=True)
    pattern = re.compile(r'\b(' + '|'.join(re.escape(t) for t in terms) + r')\b', re.IGNORECASE)
    return pattern.sub(r'[bold #4499ff][u]\1[/u][/bold #4499ff]', text)
