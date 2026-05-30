#!/usr/bin/env python3
"""
Pre-fetch market data at Docker build time.

1. Scans existing cache files and prints what's already downloaded.
2. For each symbol × interval that is missing or stale, fetches only the delta.
3. Skips anything that is already up-to-date (last candle within one interval period).

Usage:
    python prefetch_data.py              # all intervals
    python prefetch_data.py --interval 1d  # single interval (used by Docker layers)
"""

import sys
import os
import argparse
from datetime import datetime, timedelta

import pandas as pd

# Running from /eggshell/scripts → add /eggshell/src to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from core.constants import DataframeConstantsBinance
from binance_service.dataframe import Dataframe, _CACHE_DIR

_ALL_INTERVALS = ["1d", "4h", "1h", "15m"]
START_DATE     = "1 Jan, 2023"

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument("--interval", default=None, choices=_ALL_INTERVALS)
args, _ = parser.parse_known_args()

INTERVALS = [args.interval] if args.interval else _ALL_INTERVALS
NOW        = datetime.utcnow()
SYMBOLS    = DataframeConstantsBinance().ACTIVES

# How recent the last candle must be to be considered "up-to-date"
_STALE_THRESHOLD = {
    "15m": timedelta(minutes=30),
    "1h":  timedelta(hours=2),
    "4h":  timedelta(hours=8),
    "1d":  timedelta(hours=26),
}


# ── Phase 1: cache scan ───────────────────────────────────────────────────────

def _read_cache(sym: str, interval: str):
    """Return (last_ts, n_candles) for a cached file, or (None, 0) if missing."""
    path = os.path.join(_CACHE_DIR, f"{sym}_{interval}.parquet")
    if not os.path.exists(path):
        return None, 0
    try:
        df = pd.read_parquet(path)
        if df.empty:
            return None, 0
        if df.index.name == "timestamp":
            df = df.reset_index()
        ts_col = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
        return ts_col.max(), len(df)
    except Exception:
        return None, 0


def _is_fresh(last_ts, interval: str) -> bool:
    if last_ts is None:
        return False
    age = NOW - last_ts
    return age <= _STALE_THRESHOLD.get(interval, timedelta(hours=2))


print(f"\n{'='*64}")
print(f"  EGGSHELL DATA PREFETCH   {NOW.strftime('%Y-%m-%d %H:%M')} UTC")
print(f"{'='*64}")

needs_fetch: dict[str, list[str]] = {}   # interval → list of symbols to fetch

for interval in INTERVALS:
    fresh_count  = 0
    stale_syms   = []

    for sym in SYMBOLS:
        last_ts, n = _read_cache(sym, interval)
        if _is_fresh(last_ts, interval):
            fresh_count += 1
        else:
            stale_syms.append((sym, last_ts, n))

    if not stale_syms:
        print(f"\n  {interval:4s}  ✔  all {len(SYMBOLS)} symbols up-to-date — skipping")
    else:
        needs_fetch[interval] = [s for s, _, _ in stale_syms]
        print(f"\n  {interval:4s}  ↓  {len(stale_syms)} symbol(s) need update:")
        for sym, last_ts, n in stale_syms:
            age_str = f"last: {last_ts.strftime('%Y-%m-%d %H:%M')}" if last_ts else "no cache"
            print(f"       {sym:12s}  {n:>7,} candles   {age_str}")
        if fresh_count:
            print(f"       ({fresh_count} symbol(s) already fresh — will skip)")

print()

if not needs_fetch:
    print("  All data is up-to-date. Nothing to download.\n")
    print(f"{'='*64}\n")
    sys.exit(0)


# ── Phase 2: fetch deltas ─────────────────────────────────────────────────────

print(f"{'='*64}")
print(f"  Fetching deltas...")
print(f"{'='*64}\n")

errors = []

for interval, syms in needs_fetch.items():
    print(f"── {interval} ──────────────────────────────────────────────────")

    def _progress(pct: float, msg: str) -> None:
        print(f"  [{pct*100:5.1f}%]  {msg}", flush=True)

    try:
        df_obj = Dataframe(
            actives=syms,
            interval=interval,
            start_date=START_DATE,
            on_progress=_progress,
        )
        if df_obj.df is not None and not df_obj.df.empty:
            ts_max = df_obj.df.index.max()
            print(f"\n  ✔  {interval}: {len(df_obj.df):,} candles  up to {ts_max}")
        else:
            print(f"\n  ✘  {interval}: no data returned (Binance unreachable?)")
            errors.append(interval)
    except Exception as e:
        print(f"\n  ✘  {interval}: ERROR — {e}")
        errors.append(interval)

    print()

print(f"{'='*64}")
if errors:
    print(f"  DONE WITH ERRORS on: {errors}")
    print(f"  Container will retry missing data on first run.")
else:
    print(f"  PREFETCH COMPLETE — all intervals up-to-date.")
print(f"{'='*64}\n")
