"""
Elliott Wave Bollinger Strategy
================================
Buy when price sits within the Bollinger radius of a corrective wave bottom
(Wave 2, 4, or A) AND the fast EMA slope is bullish. Sell on rolling high.
"""

import re
import json
import numpy as np
import pandas as pd
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.append(project_root)

from . import constants


def get_best_ollama_model() -> str:
    import urllib.request
    preferences = ["0xroyce/plutus:latest", "deepseek-r1:7b", "gemma4:latest", "qwen2.5:0.5b", "llava:latest"]
    try:
        req  = urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
        data = json.loads(req.read().decode("utf-8"))
        installed = [m["name"] for m in data.get("models", [])]
        for pref in preferences:
            if pref in installed:
                return pref
        if installed:
            return installed[0]
    except Exception:
        pass
    return "qwen2.5:0.5b"


class ElliotBollingerStrategy:
    def __init__(self, df, **kwargs):
        self.df = df.copy()
        self.params = kwargs

    def apply_indicators(self):
        fast_span = self.params.get("FAST_EMA") or self.params.get("EMA_FAST") or constants.EMA_FAST
        self.df["EMA_10"] = self.df["close"].ewm(span=fast_span, adjust=False).mean()
        return self.df

    def generate_signals(self):
        self.df["buy"]  = False
        self.df["sell"] = False
        if self.df.empty:
            return self.df
        self._generate_signals_ai()
        if not self.params.get("ENABLED_SELL", True):
            self.df["sell"] = False  # engine closes everything on the last candle
        return self.df

    # ── Static mode (vectorized) ───────────────────────────────────────────────

    def _generate_signals_static(self):
        bollinger_sd_ratio   = self.params.get("BOLLINGER_SD_RATIO", constants.BOLLINGER_SD_RATIO)
        pivot_window_divisor = self.params.get("PIVOT_WINDOW_DIVISOR", constants.PIVOT_WINDOW_DIVISOR)

        price_range = self.df["high"].max() - self.df["low"].min() or 1.0
        radius      = price_range * bollinger_sd_ratio

        window      = max(int(len(self.df) / pivot_window_divisor), 2) if len(self.df) >= pivot_window_divisor else 5
        pivots      = self._find_pivots(self.df["close"], window)

        in_radius   = pd.Series(False, index=self.df.index)
        for pivot_price in pivots:
            in_radius |= (self.df["close"] - pivot_price).abs() <= radius

        ema_bullish     = self.df["EMA_10"] > self.df["EMA_10"].shift(1)
        self.df["buy"]  = in_radius & ema_bullish

        window_sell     = max(window * 2, 5)
        rolling_max     = self.df["close"].rolling(window_sell).max()
        self.df["sell"] = (self.df["close"] >= rolling_max * 0.99) & (~self.df["buy"])

        on_progress = self.params.get("on_progress")
        if on_progress:
            on_progress(1.0)
        return self.df

    # ── AI-optimized mode (rolling re-optimization via Ollama) ────────────────

    def _generate_signals_ai(self):
        if not isinstance(self.df.index, pd.DatetimeIndex):
            self.df.index = pd.to_datetime(self.df.index)

        on_progress = self.params.get("on_progress")
        model_name  = get_best_ollama_model()

        # Derive candle size in hours
        freq_hours = (
            max(0.25, (self.df.index[1] - self.df.index[0]).total_seconds() / 3600)
            if len(self.df) > 1 else 1.0
        )
        interval_hours   = max(1, int(self.params.get("AI_ANALYSIS_INTERVAL_HOURS", 24)))
        interval_candles = max(1, round(interval_hours / freq_hours))

        curr_A  = float(self.params.get("FAST_EMA") or self.params.get("EMA_FAST") or constants.EMA_FAST) / 10.0
        curr_r2 = float(self.params.get("BOLLINGER_SD_RATIO", constants.BOLLINGER_SD_RATIO)) * 10.0
        pw_div  = self.params.get("PIVOT_WINDOW_DIVISOR", constants.PIVOT_WINDOW_DIVISOR)

        block_indices = list(range(0, len(self.df), interval_candles))
        num_blocks    = len(block_indices) or 1

        for b_idx, start_i in enumerate(block_indices):
            if on_progress:
                ts = self.df.index[start_i]
                on_progress(
                    b_idx / num_blocks,
                    f"[PLUTUS AI] Block {b_idx+1}/{num_blocks} ({ts.strftime('%Y-%m-%d %H:%M')})..."
                )

            end_i    = min(start_i + interval_candles, len(self.df))
            block_df = self.df.iloc[start_i:end_i]
            hist_df  = self.df.iloc[:start_i]

            if len(hist_df) >= 20:
                curr_A, curr_r2 = self._ai_optimize(hist_df, curr_A, curr_r2, model_name)

            # Include recent history for proper EMA warmup
            fast_span   = max(2, min(int(curr_A * 10), 100))
            warmup      = hist_df.tail(fast_span * 3 + 10) if not hist_df.empty else pd.DataFrame()
            context_df  = pd.concat([warmup, block_df]) if not warmup.empty else block_df

            ema_full    = context_df["close"].ewm(span=fast_span, adjust=False).mean()
            block_ema   = ema_full.loc[block_df.index]
            ema_prev    = ema_full.shift(1).loc[block_df.index]

            sd_ratio = max(0.01, min(curr_r2 / 10.0, 1.0))
            radius   = (context_df["high"].max() - context_df["low"].min() or 1.0) * sd_ratio

            window = max(int(len(context_df) / pw_div), 2) if len(context_df) >= pw_div else 5
            pivots = self._find_pivots(context_df["close"], window)

            in_radius = pd.Series(False, index=block_df.index)
            for pivot_price in pivots:
                in_radius |= (block_df["close"] - pivot_price).abs() <= radius

            block_buy = in_radius & (block_ema > ema_prev)

            window_sell = max(window * 2, 5)
            roll_ctx    = pd.concat([hist_df.tail(window_sell), block_df]) if not hist_df.empty else block_df
            rolling_max = roll_ctx["close"].rolling(window_sell).max().loc[block_df.index]
            block_sell  = (block_df["close"] >= rolling_max * 0.99) & (~block_buy)

            self.df.loc[block_df.index, "buy"]  = block_buy
            self.df.loc[block_df.index, "sell"] = block_sell

        if on_progress:
            on_progress(1.0, "[PLUTUS AI] Optimization complete!")
        return self.df

    def _find_pivots(self, close: pd.Series, window: int) -> list[float]:
        pivots = close.rolling(window=window, center=True).min().dropna().unique().tolist()
        if len(pivots) < 3:
            pivots = [close.quantile(0.10), close.quantile(0.35), close.quantile(0.60)]
        return pivots[:3]

    def _ai_optimize(self, hist_df: pd.DataFrame, curr_A: float, curr_r2: float, model: str) -> tuple[float, float]:
        import urllib.request
        window = hist_df.tail(150)
        prices = window["close"].round(2).tolist()
        n      = max(10, len(prices) // 5)

        prompt = constants.SYSTEM_PROMPT_1_TEMPLATE.format(
            active_wave_desc="Wave 1 + Wave 2 (impulse + retracement)",
            llm_total=len(prices),
            llm_prices=prices,
            recent_n=n,
            recent_high=window["high"].round(2).tolist()[-n:],
            recent_low=window["low"].round(2).tolist()[-n:],
            curr_A=curr_A,
            curr_r2=curr_r2,
        )
        try:
            body = json.dumps({"model": model, "prompt": prompt, "stream": False, "format": "json"}).encode()
            req  = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=body, headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                text  = json.loads(resp.read().decode())["response"]
                match = re.search(r"\{.*\}", text, re.DOTALL)
                data  = json.loads(match.group(0) if match else text)
                return float(data.get("A", curr_A)), float(data.get("r2", curr_r2))
        except Exception:
            return curr_A, curr_r2


if __name__ == "__main__":
    dates = pd.date_range("2023-01-01", periods=50, freq="h")
    test_df = pd.DataFrame({
        "symbol": "BTCUSDT",
        "close":  np.random.uniform(20000, 22000, 50),
        "high":   np.random.uniform(21500, 22500, 50),
        "low":    np.random.uniform(19500, 20500, 50),
        "volume": np.random.uniform(100,   1000,  50),
    }, index=dates)

    strat   = ElliotBollingerStrategy(test_df, EMA_FAST=10)
    test_df = strat.apply_indicators()
    test_df = strat.generate_signals()
    print(test_df[["symbol", "close", "EMA_10", "buy", "sell"]].tail(10))
