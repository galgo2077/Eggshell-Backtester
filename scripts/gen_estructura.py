"""
Universal SL/TP Resolver + Portfolio Exposure Manager — gen_estructura.py
=============================================
Centralizes the interpretation and normalization of all stop-loss and
take-profit definitions that strategies may produce.

Strategies keep their current contract: output a DataFrame with 'buy'/'sell'
boolean columns. Optionally they may also add 'sl' / 'tp' columns (or any
recognised alias — see _SL_COLS / _TP_COLS) containing raw exit definitions
in ANY of the supported formats below.  When those columns are absent the
engine falls back to the UI-supplied global percentages unchanged.

Supported formats (auto-detected, no strategy changes required):
  Fractional %    sl = 0.02          → 2 % below entry
  Percentage pts  sl = 2.0           → 2 % below entry
  Absolute price  sl = 42 850.0      → fixed price level
  ATR dict        sl = {"atr_mult": 2, "atr_value": 250.0}
  Callable        sl = lambda row: row["close"] * 0.98
  Structured dict sl = {"price": 42850.0}

Public API
----------
resolve_exit_levels(entry_price, sl_raw, tp_raw, market_row, side) -> ResolvedExit
build_exit_arrays(signals_df, fallback_sl_pct, fallback_tp_pct, side) -> (Series|None, Series|None)
has_valid_stops(val) -> bool
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


# ── Exit-type constants ────────────────────────────────────────────────────────

class ExitType:
    NONE       = "none"
    PERCENTAGE = "percentage"    # fractional or %-point distance from entry
    PRICE      = "price_level"   # absolute market price
    ATR        = "atr"           # ATR multiplier dict
    STRUCTURE  = "structure"     # candle/swing-based dict
    DYNAMIC    = "dynamic"       # callable
    MIXED      = "mixed"         # SL and TP have different types
    UNKNOWN    = "unknown"


# ── Resolved result ───────────────────────────────────────────────────────────

@dataclass
class ResolvedExit:
    """Normalized SL/TP ready for the execution engine."""
    stop_loss:   Optional[float]  # absolute price; None → not set
    take_profit: Optional[float]  # absolute price; None → not set
    exit_type:   str              # ExitType constant
    sl_pct:      Optional[float]  # fractional distance from entry (0.02 = 2 %)
    tp_pct:      Optional[float]  # fractional distance from entry (0.05 = 5 %)
    raw_sl:      Any = field(default=None, repr=False)
    raw_tp:      Any = field(default=None, repr=False)


# ── Detection heuristics ──────────────────────────────────────────────────────

# Scalar values below this are treated as fractions (0.02 → 2 %)
_FRACTION_LIMIT = 1.0
# Scalar values in [_FRACTION_LIMIT, _PERCENT_LIMIT] treated as %-points (2.0 → 2 %)
_PERCENT_LIMIT  = 50.0
# Proximity window: if |val − entry| / entry < this → price level
_PROXIMITY      = 0.25

# Column name aliases strategies may use for SL / TP
_SL_COLS = ("sl", "stop_loss", "SL", "sl_price", "sl_level", "sl_raw")
_TP_COLS = ("tp", "take_profit", "TP", "tp_price", "tp_level", "tp_raw")


# ── Type detection ────────────────────────────────────────────────────────────

def detect_exit_type(value: Any, entry_price: float = 0.0) -> str:
    """
    Classify a raw SL/TP value into an ExitType string.

    Heuristics (in priority order):
    1. None / NaN                        → NONE
    2. callable                          → DYNAMIC
    3. dict with atr_mult / atr key      → ATR
    4. dict with 'price' key             → PRICE
    5. dict with pct / percent / fraction→ PERCENTAGE
    6. other dict                        → STRUCTURE
    7. numeric, |v − entry| / entry < 25%→ PRICE
    8. numeric, v < 1.0                  → PERCENTAGE (fraction)
    9. numeric, 1.0 ≤ v ≤ 50            → PERCENTAGE (%-points)
    10. numeric, v > 50                  → PRICE (absolute)
    """
    if value is None:
        return ExitType.NONE
    if isinstance(value, float) and math.isnan(value):
        return ExitType.NONE

    if callable(value):
        return ExitType.DYNAMIC

    if isinstance(value, dict):
        keys = set(value.keys())
        if keys & {"atr_mult", "atr", "atr_multiplier", "atr_value"}:
            return ExitType.ATR
        if "price" in keys or "price_level" in keys:
            return ExitType.PRICE
        if keys & {"pct", "percent", "percentage", "fraction"}:
            return ExitType.PERCENTAGE
        return ExitType.STRUCTURE

    if isinstance(value, (int, float, np.floating, np.integer)):
        v = float(value)
        if v <= 0:
            return ExitType.NONE
        # Proximity to entry takes priority — catches pre-computed absolute prices
        if entry_price > 0 and abs(v - entry_price) / entry_price < _PROXIMITY:
            return ExitType.PRICE
        if v < _FRACTION_LIMIT:
            return ExitType.PERCENTAGE
        if v <= _PERCENT_LIMIT:
            return ExitType.PERCENTAGE
        return ExitType.PRICE   # large value → absolute price level

    return ExitType.UNKNOWN


# ── ATR helper ────────────────────────────────────────────────────────────────

def _get_atr(spec: dict, market_row: Optional[pd.Series], entry_price: float) -> Optional[float]:
    """Extract ATR from the spec dict or market_row indicators."""
    if "atr_value" in spec:
        return float(spec["atr_value"])
    if market_row is not None:
        for col in ("ATR", "atr", "ATR_14", "atr_14", "atr14"):
            if col in market_row.index:
                return float(market_row[col])
    # Last resort: estimate ATR as 1 % of entry price and warn once
    if entry_price > 0:
        logger.debug(
            "[SLTP RESOLVER] ATR not found in spec or market_row — "
            "approximating as 1 %% of entry (%.4f)", entry_price * 0.01
        )
        return entry_price * 0.01
    return None


# ── Single-value resolver ─────────────────────────────────────────────────────

def _resolve_one(
    raw: Any,
    entry_price: float,
    side: str,
    field: str,                          # "sl" or "tp"
    market_row: Optional[pd.Series],
) -> tuple[Optional[float], str]:
    """
    Map one raw SL/TP value to an absolute price and its detected type.
    Returns (absolute_price | None, exit_type).
    """
    exit_type = detect_exit_type(raw, entry_price)

    if exit_type == ExitType.NONE:
        return None, ExitType.NONE

    # ── Callable (dynamic) ────────────────────────────────────────────────────
    if exit_type == ExitType.DYNAMIC:
        try:
            result = raw(market_row) if market_row is not None else raw(entry_price)
            return float(result), ExitType.DYNAMIC
        except Exception as exc:
            logger.warning("[SLTP RESOLVER] Dynamic %s callable raised: %s", field, exc)
            return None, ExitType.NONE

    # ── ATR-based dict ────────────────────────────────────────────────────────
    if exit_type == ExitType.ATR:
        atr = _get_atr(raw, market_row, entry_price)
        if atr is None:
            return None, ExitType.NONE
        mult = float(raw.get("atr_mult", raw.get("atr_multiplier", 2.0)))
        if field == "sl":
            price = (entry_price - atr * mult) if side == "long" else (entry_price + atr * mult)
        else:
            price = (entry_price + atr * mult) if side == "long" else (entry_price - atr * mult)
        return price, ExitType.ATR

    # ── Absolute price level ──────────────────────────────────────────────────
    if exit_type == ExitType.PRICE:
        if isinstance(raw, dict):
            v = float(raw.get("price", raw.get("price_level", 0.0)))
        else:
            v = float(raw)
        return v, ExitType.PRICE

    # ── Percentage (fraction or %-points) ────────────────────────────────────
    if exit_type == ExitType.PERCENTAGE:
        if isinstance(raw, dict):
            v = float(raw.get("pct", raw.get("percent", raw.get("fraction", raw.get("percentage", 0.0)))))
        else:
            v = float(raw)
        frac = v if v < _FRACTION_LIMIT else v / 100.0
        if field == "sl":
            price = entry_price * (1.0 - frac) if side == "long" else entry_price * (1.0 + frac)
        else:
            price = entry_price * (1.0 + frac) if side == "long" else entry_price * (1.0 - frac)
        return price, ExitType.PERCENTAGE

    # ── Generic structured dict ───────────────────────────────────────────────
    if exit_type == ExitType.STRUCTURE:
        key = "stop_loss" if field == "sl" else "take_profit"
        nested = raw.get(key)
        if nested is not None:
            return _resolve_one(nested, entry_price, side, field, market_row)
        logger.warning("[SLTP RESOLVER] STRUCTURE dict has no '%s' key: %r", key, raw)
        return None, ExitType.STRUCTURE

    logger.warning("[SLTP RESOLVER] Unknown type for %s=%r", field, raw)
    return None, ExitType.UNKNOWN


# ── Validation ────────────────────────────────────────────────────────────────

def _validate(
    entry_price: float,
    sl_price: Optional[float],
    tp_price: Optional[float],
    side: str,
) -> tuple[Optional[float], Optional[float]]:
    """Enforce directional constraints; discard invalid levels with a warning."""
    if sl_price is not None:
        if side == "long" and sl_price >= entry_price:
            logger.warning(
                "[SLTP RESOLVER] INVALID SL %.4f >= entry %.4f for LONG — discarded",
                sl_price, entry_price,
            )
            sl_price = None
        elif side == "short" and sl_price <= entry_price:
            logger.warning(
                "[SLTP RESOLVER] INVALID SL %.4f <= entry %.4f for SHORT — discarded",
                sl_price, entry_price,
            )
            sl_price = None

    if tp_price is not None:
        if side == "long" and tp_price <= entry_price:
            logger.warning(
                "[SLTP RESOLVER] INVALID TP %.4f <= entry %.4f for LONG — discarded",
                tp_price, entry_price,
            )
            tp_price = None
        elif side == "short" and tp_price >= entry_price:
            logger.warning(
                "[SLTP RESOLVER] INVALID TP %.4f >= entry %.4f for SHORT — discarded",
                tp_price, entry_price,
            )
            tp_price = None

    return sl_price, tp_price


# ══════════════════════════════════════════════════════════════════════════════
# Public API
# ══════════════════════════════════════════════════════════════════════════════

def resolve_exit_levels(
    entry_price: float,
    sl_raw: Any = None,
    tp_raw: Any = None,
    market_row: Optional[pd.Series] = None,
    side: str = "long",
) -> ResolvedExit:
    """
    Resolve heterogeneous SL/TP definitions into normalized price levels.

    Args:
        entry_price: Trade entry price (close of buy candle).
        sl_raw:      Raw stop-loss definition — float, callable, dict, or None.
        tp_raw:      Raw take-profit definition — float, callable, dict, or None.
        market_row:  OHLCV + indicator Series at entry time (for ATR/dynamic).
        side:        "long" or "short".

    Returns:
        ResolvedExit with absolute prices and fractional percentages.

    Example — percentage:
        resolve_exit_levels(43000.0, sl_raw=0.02, tp_raw=0.05)
        → ResolvedExit(stop_loss=42140.0, take_profit=45150.0, exit_type="percentage", ...)

    Example — absolute price:
        resolve_exit_levels(43000.0, sl_raw=42500.0, tp_raw=44000.0)
        → ResolvedExit(stop_loss=42500.0, take_profit=44000.0, exit_type="price_level", ...)

    Example — ATR dict:
        resolve_exit_levels(43000.0, sl_raw={"atr_mult": 2, "atr_value": 250.0})
        → ResolvedExit(stop_loss=42500.0, ..., exit_type="atr", ...)
    """
    sl_price, sl_type = _resolve_one(sl_raw, entry_price, side, "sl", market_row)
    tp_price, tp_type = _resolve_one(tp_raw, entry_price, side, "tp", market_row)

    sl_price, tp_price = _validate(entry_price, sl_price, tp_price, side)

    # Fractional percentage distances (for vectorbt)
    sl_pct = (abs(entry_price - sl_price) / entry_price) if (sl_price is not None and entry_price > 0) else None
    tp_pct = (abs(tp_price - entry_price) / entry_price) if (tp_price is not None and entry_price > 0) else None

    # Combined type label
    active = {t for t in (sl_type, tp_type) if t != ExitType.NONE}
    if not active:
        combined = ExitType.NONE
    elif len(active) == 1:
        combined = active.pop()
    else:
        combined = ExitType.MIXED

    # Structured log (only when something was actually resolved)
    if combined != ExitType.NONE:
        sl_str = f"{sl_price:.4f}" if sl_price is not None else "None"
        tp_str = f"{tp_price:.4f}" if tp_price is not None else "None"
        logger.info(
            "[SLTP RESOLVER] Detected type: %s | entry=%.4f | "
            "Resolved SL: %s | Resolved TP: %s",
            combined, entry_price, sl_str, tp_str,
        )

    return ResolvedExit(
        stop_loss=sl_price,
        take_profit=tp_price,
        exit_type=combined,
        sl_pct=sl_pct,
        tp_pct=tp_pct,
        raw_sl=sl_raw,
        raw_tp=tp_raw,
    )


def build_exit_arrays(
    signals_df: pd.DataFrame,
    fallback_sl_pct: Optional[float] = None,
    fallback_tp_pct: Optional[float] = None,
    side: str = "long",
) -> tuple[Optional[pd.Series], Optional[pd.Series]]:
    """
    Build per-row fractional SL / TP Series for vectorbt from a signals DataFrame.

    Scans signals_df for optional sl / tp columns (any alias in _SL_COLS /
    _TP_COLS).  When found, resolves each buy-signal row via resolve_exit_levels
    and returns two Series indexed like signals_df with fractional percentages.
    NaN rows mean "no stop for this candle" — vectorbt ignores them.

    Returns (None, None) when the DataFrame carries no exit columns, signalling
    the engine to keep using its UI-supplied scalar fallbacks unchanged.

    Args:
        signals_df:      Full signals DataFrame (flat, multi-symbol with 'symbol' col).
        fallback_sl_pct: Fractional fallback SL (e.g. 0.02) from UI; used when
                         a strategy column is NaN on a specific row.
        fallback_tp_pct: Fractional fallback TP (e.g. 0.05) from UI.
        side:            "long" or "short".

    Returns:
        (sl_series, tp_series) as float64 Series aligned to signals_df.index,
        or (None, None) if no strategy exit columns exist.
    """
    sl_col = next((c for c in _SL_COLS if c in signals_df.columns), None)
    tp_col = next((c for c in _TP_COLS if c in signals_df.columns), None)

    if sl_col is None and tp_col is None:
        # Backward-compatible path — no strategy-level exits defined
        return None, None

    logger.info(
        "[SLTP RESOLVER] Strategy-level exit columns detected — SL: %r  TP: %r",
        sl_col, tp_col,
    )

    sl_series = pd.Series(np.nan, index=signals_df.index, dtype="float64")
    tp_series = pd.Series(np.nan, index=signals_df.index, dtype="float64")

    buy_mask = (
        signals_df["buy"].astype(bool)
        if "buy" in signals_df.columns
        else pd.Series(False, index=signals_df.index)
    )

    # Iterate row-by-row using integer positions to avoid duplicate-index ambiguity
    # (multiple symbols share the same timestamp, so .loc[ts] returns a DataFrame).
    buy_positions = [i for i, v in enumerate(buy_mask) if v]
    logger.info("[SLTP RESOLVER] Resolving exits for %d buy-signal row(s).", len(buy_positions))

    sl_values = sl_series.to_numpy(dtype="float64", na_value=np.nan, copy=True)
    tp_values = tp_series.to_numpy(dtype="float64", na_value=np.nan, copy=True)

    for pos in buy_positions:
        row      = signals_df.iloc[pos]
        entry_px = float(row["close"]) if "close" in row.index else 0.0
        if entry_px <= 0:
            continue

        raw_sl = row[sl_col] if sl_col else None
        raw_tp = row[tp_col] if tp_col else None

        # Row-level NaN falls back to UI global
        if raw_sl is None or (isinstance(raw_sl, float) and math.isnan(raw_sl)):
            raw_sl = fallback_sl_pct
        if raw_tp is None or (isinstance(raw_tp, float) and math.isnan(raw_tp)):
            raw_tp = fallback_tp_pct

        resolved = resolve_exit_levels(
            entry_price=entry_px,
            sl_raw=raw_sl,
            tp_raw=raw_tp,
            market_row=row,
            side=side,
        )
        sl_values[pos] = resolved.sl_pct if resolved.sl_pct is not None else np.nan
        tp_values[pos] = resolved.tp_pct if resolved.tp_pct is not None else np.nan

    sl_series = pd.Series(sl_values, index=signals_df.index, dtype="float64")
    tp_series = pd.Series(tp_values, index=signals_df.index, dtype="float64")

    # Return None series unchanged if every value is NaN (strategy columns existed
    # but contained no usable data — fall back to scalar UI values)
    sl_out = sl_series if sl_series.notna().any() else None
    tp_out = tp_series if tp_series.notna().any() else None
    return sl_out, tp_out


def has_valid_stops(val: Any) -> bool:
    """
    Return True when val contains at least one non-NaN stop level.
    Handles scalar floats, DataFrames, and Series uniformly.
    Used by BacktestEngine to set the vectorbt use_stops flag.
    """
    if val is None:
        return False
    if isinstance(val, (pd.DataFrame, pd.Series)):
        return bool(val.notna().any().any())
    try:
        return not math.isnan(float(val))
    except (TypeError, ValueError):
        return False


# ══════════════════════════════════════════════════════════════════════════════
# Portfolio Exposure Manager
# ══════════════════════════════════════════════════════════════════════════════

class PortfolioExposureManager:
    """
    Tracks GLOBAL reserved capital exposure across all open positions.

    Exposure is expressed as a percentage of initial_balance (0–100).
    Each entry reserves exactly `position_size_pct` percent from the shared
    pool — one slot per trade, regardless of which symbol fires the signal.
    The asset allocation weights (per_symbol_alloc) determine only the dollar
    amount deployed per position, not the slot cost.

    Global cap rule
    ---------------
    max_positions = floor(100 / position_size_pct)   ← across ALL symbols

    Example (equity=$1000, budget=1%, BTC=80%, ETH=20%):
        BTC trade: slot cost = 1%  → capital deployed = $8  (80% of $10 slot)
        ETH trade: slot cost = 1%  → capital deployed = $2  (20% of $10 slot)
        After 100 trades total → global pool = 100% → no more entries

    sell_at_end behaviour
    ---------------------
    True  → exposure locked until on_final_candle(); no intra-run release.
    False → exposure released immediately on each sell signal.
    """

    def __init__(
        self,
        position_size_pct: float,
        per_symbol_alloc: Optional[dict] = None,
        sell_at_end: bool = False,
        equity: float = 0.0,
    ) -> None:
        self.position_size_pct = position_size_pct
        self.per_symbol_alloc  = per_symbol_alloc or {}
        self.sell_at_end       = sell_at_end
        self.equity            = equity          # used for USD-amount log output only

        # Live state
        self.reserved_exposure_pct: float = 0.0
        self.open_positions:        dict  = {}    # symbol → open count
        self.used_margin:           float = 0.0   # alias for reserved (% units)

        # Audit trail
        self.rejected_entries: list[dict] = []
        self.accepted_entries: list[dict] = []

    # ── Internal helpers ───────────────────────────────────────────────────

    def _entry_exposure(self, symbol: str, n_symbols: int) -> float:
        """
        Exposure slot consumed per entry — always the full position_size_pct.

        The allocation weight determines how the slot's capital is distributed,
        not how much of the global pool is reserved.  This enforces a hard
        global cap of floor(100 / position_size_pct) simultaneous positions
        across ALL assets combined.
        """
        return self.position_size_pct

    def _position_capital_usd(self, symbol: str, n_symbols: int) -> float:
        """Dollar amount deployed for this symbol's position (uses alloc weights)."""
        if self.equity <= 0:
            return 0.0
        if self.per_symbol_alloc:
            alloc = self.per_symbol_alloc.get(symbol, 100.0 / max(n_symbols, 1))
        else:
            alloc = 100.0 / max(n_symbols, 1)
        return self.equity * (self.position_size_pct / 100.0) * (alloc / 100.0)

    def _alloc_pct(self, symbol: str, n_symbols: int) -> float:
        if self.per_symbol_alloc:
            return self.per_symbol_alloc.get(symbol, 100.0 / max(n_symbols, 1))
        return 100.0 / max(n_symbols, 1)

    # ── Public query ───────────────────────────────────────────────────────

    @property
    def available_exposure_pct(self) -> float:
        return max(0.0, 100.0 - self.reserved_exposure_pct)

    def can_open(self, symbol: str, n_symbols: int) -> bool:
        """True when the global pool can absorb one more position."""
        needed = self._entry_exposure(symbol, n_symbols)
        return (self.available_exposure_pct - needed) >= -1e-9

    # ── State mutations ────────────────────────────────────────────────────

    def on_entry(self, symbol: str, n_symbols: int, ts=None) -> None:
        exp     = self._entry_exposure(symbol, n_symbols)
        capital = self._position_capital_usd(symbol, n_symbols)
        alloc   = self._alloc_pct(symbol, n_symbols)

        self.reserved_exposure_pct = min(100.0, self.reserved_exposure_pct + exp)
        self.used_margin            = self.reserved_exposure_pct
        self.open_positions[symbol] = self.open_positions.get(symbol, 0) + 1
        self.accepted_entries.append({"ts": ts, "symbol": symbol, "exposure_added": exp})

        equity_str  = f"  Equity: ${self.equity:,.2f}\n" if self.equity > 0 else ""
        capital_str = f"  {symbol} Weight: {alloc:.1f}%\n  {symbol} Position Size: ${capital:,.2f}\n" if capital > 0 else ""
        logger.debug(
            "[PORTFOLIO EXPOSURE MANAGER]\n"
            "  Mode: REAL DATA BACKTEST\n"
            "%s"
            "  Budget Per Trade: %.2f%%\n\n"
            "  Global Exposure Used: %.2f%%\n"
            "  Remaining Exposure: %.2f%%\n\n"
            "%s",
            equity_str, exp,
            self.reserved_exposure_pct, self.available_exposure_pct,
            capital_str,
        )

    def on_exit(self, symbol: str, n_symbols: int, ts=None) -> None:
        """Release one slot when a position closes (no-op when sell_at_end=True)."""
        if self.sell_at_end:
            return
        count = self.open_positions.get(symbol, 0)
        if count > 0:
            exp = self._entry_exposure(symbol, n_symbols) * count
            self.reserved_exposure_pct = max(0.0, self.reserved_exposure_pct - exp)
            self.used_margin            = self.reserved_exposure_pct
            self.open_positions[symbol] = 0
            logger.debug(
                "[PORTFOLIO EXPOSURE MANAGER] Exit — %s  released %.2f%%  "
                "Global Exposure Used: %.2f%%  Remaining: %.2f%%",
                symbol, exp, self.reserved_exposure_pct, self.available_exposure_pct,
            )

    def on_final_candle(self) -> None:
        """Final liquidation: release all reserved exposure."""
        logger.info(
            "[PORTFOLIO EXPOSURE MANAGER] Final candle — releasing all exposure  "
            "(was %.2f%% reserved)", self.reserved_exposure_pct,
        )
        self.reserved_exposure_pct = 0.0
        self.used_margin            = 0.0
        self.open_positions         = {}

    def reject_entry(self, symbol: str, ts=None) -> None:
        self.rejected_entries.append({
            "ts": ts, "symbol": symbol,
            "reserved": self.reserved_exposure_pct,
            "available": self.available_exposure_pct,
        })
        logger.debug(
            "[PORTFOLIO EXPOSURE MANAGER]\n"
            "  Global Exposure Used: %.1f%%\n"
            "  Remaining Exposure: %.1f%%\n"
            "  Trade rejected: insufficient remaining portfolio exposure  (%s @ %s)",
            self.reserved_exposure_pct, self.available_exposure_pct, symbol, ts,
        )

    # ── Summary ────────────────────────────────────────────────────────────

    def summary(self) -> str:
        equity_line = f"  Equity: ${self.equity:,.2f}\n" if self.equity > 0 else ""
        return (
            f"[PORTFOLIO EXPOSURE MANAGER]\n"
            f"  Mode: REAL DATA BACKTEST\n\n"
            f"{equity_line}"
            f"  Budget Per Trade: {self.position_size_pct:.2f}%\n\n"
            f"  Global Exposure Used: {self.reserved_exposure_pct:.1f}%\n"
            f"  Remaining Exposure: {self.available_exposure_pct:.1f}%\n\n"
            f"  Accepted: {len(self.accepted_entries)}  "
            f"Rejected: {len(self.rejected_entries)}"
        )


_REAL_DATA_MODE = "real_market_backtest"


def apply_exposure_filter(
    buy_df: pd.DataFrame,
    sell_df: pd.DataFrame,
    position_size_pct: float,
    per_symbol_alloc: Optional[dict] = None,
    sell_at_end: bool = False,
    simulation_mode: str = _REAL_DATA_MODE,
    equity: float = 0.0,
) -> tuple[pd.DataFrame, PortfolioExposureManager]:
    """
    Walk the signal timeline and suppress buy signals that would exceed the
    available global portfolio exposure.

    ISOLATION CONTRACT
    ------------------
    This filter is active ONLY when simulation_mode == "real_market_backtest".
    Monte Carlo and random-walk runs bypass it entirely — their buy_df is
    returned unchanged so those modes can produce unrestricted trade counts
    for statistical analysis.

    Global exposure model
    ---------------------
    * Each entry reserves exactly `position_size_pct` from the shared pool,
      regardless of which symbol fires the signal.
    * max_positions = floor(100 / position_size_pct) across ALL symbols combined.
    * Dollar amount per position = equity × budget × (symbol_alloc / 100).

    sell_at_end behaviour
    ---------------------
    * True  : exposure locked until final candle; no intra-run releases.
    * False : exposure freed on each sell signal for future re-use.

    Args:
        buy_df:            Boolean DataFrame (time × symbol) of buy signals.
        sell_df:           Boolean DataFrame (time × symbol) of sell signals.
        position_size_pct: Global slot cost per entry (e.g. 1.0 = 1%).
        per_symbol_alloc:  Optional {symbol: alloc_%} for dollar sizing.
        sell_at_end:       True → locked, False → normal exits.
        simulation_mode:   "real_market_backtest" → enforce constraints;
                           any other value → bypass (Monte Carlo / random walk).
        equity:            Total account equity in USD (for log output).

    Returns:
        (filtered_buy_df, PortfolioExposureManager)
    """
    # ── Simulation bypass ──────────────────────────────────────────────────────
    if simulation_mode != _REAL_DATA_MODE:
        logger.info(
            "[PORTFOLIO EXPOSURE MANAGER] Bypassed — simulation_mode=%r "
            "(constraints apply only to real-data backtests).",
            simulation_mode,
        )
        _dummy = PortfolioExposureManager(position_size_pct, per_symbol_alloc, sell_at_end, equity)
        return buy_df, _dummy

    manager  = PortfolioExposureManager(position_size_pct, per_symbol_alloc, sell_at_end, equity)
    filtered = buy_df.copy()
    n_cols   = len(buy_df.columns)
    symbols  = [str(c) for c in buy_df.columns]
    last_ts  = buy_df.index[-1] if not buy_df.empty else None

    for ts in buy_df.index:
        is_last = (ts == last_ts)

        # ── 1. Process exits (frees exposure for sell_at_end=OFF) ─────────
        #       Do this before entries so a sell+buy on the same candle
        #       correctly frees capital before the new entry is evaluated.
        for col, sym in zip(buy_df.columns, symbols):
            if sell_df.loc[ts, col]:
                manager.on_exit(sym, n_cols, ts=ts)

        # ── 2. Process entries (accept or reject based on available exposure) ─
        for col, sym in zip(buy_df.columns, symbols):
            if filtered.loc[ts, col]:
                if manager.can_open(sym, n_cols):
                    manager.on_entry(sym, n_cols, ts=ts)
                else:
                    filtered.loc[ts, col] = False
                    manager.reject_entry(sym, ts=ts)

        # ── 3. Final-candle liquidation: release all reserved exposure ─────
        if is_last:
            manager.on_final_candle()

    logger.info("\n%s", manager.summary())
    return filtered, manager



