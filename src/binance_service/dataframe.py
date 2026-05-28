from core.constants import ConnectConstantsBinance, DataframeConstantsBinance
from binance_service.connect import Connect

import os
import time
import logging
import threading
from datetime import datetime

import pandas as pd
import dateparser
from concurrent.futures import ThreadPoolExecutor
from core.performance import default_worker_count

logger = logging.getLogger(__name__)

_CACHE_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
_EPOCH       = datetime(1970, 1, 1)


def _dt_to_epoch_ms(dt) -> int:
    """Datetime or pd.Timestamp → epoch milliseconds."""
    return int((dt - _EPOCH).total_seconds() * 1000)


class Dataframe:
    def __init__(self, actives: list[str] | None = None, interval: str | None = None,
                 start_date: str | None = None, end_date: str | None = None,
                 on_progress=None):
        self.connect_constants   = ConnectConstantsBinance()
        self.dataframe_constants = DataframeConstantsBinance()

        if actives:
            self.dataframe_constants.ACTIVES = actives
        if interval:
            self.dataframe_constants.KLINE_INTERVAL = interval
        if start_date:
            self.connect_constants.START_DATE = start_date

        self.end_date      = end_date
        self._on_progress  = on_progress
        self.connect       = Connect()

        self._purge_old_caches()

        self._completed      = 0
        self._completed_lock = threading.Lock()
        self._total_assets   = len(self.dataframe_constants.ACTIVES)

        t0: float = time.perf_counter()
        final_parts: list[pd.DataFrame] = []
        max_workers = min(max(1, self._total_assets), default_worker_count())
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for result in pool.map(self._process_asset, self.dataframe_constants.ACTIVES):
                if result is not None:
                    final_parts.append(result)

        if final_parts:
            full_df = pd.concat(final_parts, ignore_index=True).sort_values("timestamp")

            start_ts = dateparser.parse(self.connect_constants.START_DATE, settings={"RETURN_AS_TIMEZONE_AWARE": False})
            full_df  = full_df[full_df["timestamp"] >= start_ts]
            if self.end_date:
                end_ts  = dateparser.parse(self.end_date, settings={"RETURN_AS_TIMEZONE_AWARE": False})
                full_df = full_df[full_df["timestamp"] <= end_ts]

            if "symbol" in full_df.columns:
                full_df["symbol"] = full_df["symbol"].astype("category")
            self.df = full_df.set_index("timestamp")

            elapsed = time.perf_counter() - t0
            logger.info(
                "[PANDAS PIPELINE] %d symbol(s) → %d candles assembled in %.3fs with %d worker(s)",
                len(final_parts), len(self.df), elapsed, max_workers,
            )
        else:
            self.df = pd.DataFrame()

    # ── Cache helpers ─────────────────────────────────────────────────────────

    def _purge_old_caches(self):
        for interval in ("15m", "1h", "4h", "1d"):
            old = os.path.join(_CACHE_DIR, f"binance_klines_{interval}.parquet")
            if os.path.exists(old):
                try:
                    os.remove(old)
                except Exception:
                    pass
        old_pkl = os.path.join(_CACHE_DIR, "binance_klines.pkl")
        if os.path.exists(old_pkl):
            try:
                os.remove(old_pkl)
            except Exception:
                pass

    def _sym_cache_path(self, sym: str) -> str:
        interval = self.dataframe_constants.KLINE_INTERVAL
        return os.path.join(_CACHE_DIR, f"{sym}_{interval}.parquet")

    def _load_sym_cache(self, sym: str) -> pd.DataFrame | None:
        path = self._sym_cache_path(sym)
        if not os.path.exists(path):
            return None
        try:
            df = pd.read_parquet(path)
            if df.empty:
                return None
            if df.index.name == "timestamp":
                df = df.reset_index()
            if "timestamp" not in df.columns:
                raise ValueError("missing timestamp column")
            df["timestamp"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None)
            return df
        except Exception:
            try:
                os.remove(path)
            except Exception:
                pass
            return None

    def _save_sym_cache(self, sym: str, df: pd.DataFrame) -> None:
        if df is None or df.empty:
            return
        os.makedirs(_CACHE_DIR, exist_ok=True)
        df.to_parquet(self._sym_cache_path(sym), index=False)

    # ── Fetch helpers ─────────────────────────────────────────────────────────

    def _process_asset(self, sym: str) -> pd.DataFrame | None:
        t0     = time.perf_counter()
        cached = self._load_sym_cache(sym)
        parts: list[pd.DataFrame] = (
            [cached] if (cached is not None and not cached.empty) else []
        )

        # Forward fetch: new candles since the last cached timestamp (or full history)
        fwd_start = (
            str(_dt_to_epoch_ms(cached["timestamp"].max()))
            if parts else self.connect_constants.START_DATE
        )
        _, rates = self._fetch_klines(sym, fwd_start)
        new_fwd  = self._rates_to_df(sym, rates)
        if new_fwd is not None:
            parts.append(new_fwd)

        # Backward fetch: fill gap when the requested start is earlier than cache
        if cached is not None and not cached.empty:
            req_start  = dateparser.parse(self.connect_constants.START_DATE, settings={"RETURN_AS_TIMEZONE_AWARE": False})
            cached_min = cached["timestamp"].min()
            if req_start < cached_min:
                end_ms       = str(_dt_to_epoch_ms(cached_min))
                _, rates_old = self._fetch_klines(sym, self.connect_constants.START_DATE, end_ms=end_ms)
                new_bwd      = self._rates_to_df(sym, rates_old)
                if new_bwd is not None:
                    parts.append(new_bwd)

        with self._completed_lock:
            self._completed += 1
            pct = self._completed / max(self._total_assets, 1)

        if not parts:
            if self._on_progress:
                self._on_progress(pct, f"NO DATA: {sym}")
            return None

        combined = pd.concat(parts, ignore_index=True)
        result   = (combined.drop_duplicates(subset=["timestamp"], keep="last")
                             .sort_values("timestamp")
                             .reset_index(drop=True))
        result["symbol"] = result["symbol"].astype("category")

        self._save_sym_cache(sym, result)

        elapsed = time.perf_counter() - t0
        if self._on_progress:
            self._on_progress(pct, f"CACHED {sym}  ({len(result):,} candles)  [{elapsed:.3f}s]")

        return result

    def _fetch_klines(self, active: str, start: str,
                      end_ms: str | None = None) -> tuple[str, list]:
        effective_end = end_ms if end_ms is not None else self.end_date
        try:
            rates = self.connect.client.get_historical_klines(
                active, self.dataframe_constants.KLINE_INTERVAL,
                start, end_str=effective_end
            )
            return active, rates or []
        except Exception:
            return active, []

    def _rates_to_df(self, active: str, rates: list) -> pd.DataFrame | None:
        if not rates:
            return None

        cols   = self.dataframe_constants.KLINE_COLUMNS
        n_cols = len(cols)

        data = {col: [row[i] for row in rates] for i, col in enumerate(cols) if i < n_cols}
        df   = pd.DataFrame(data)

        # Timestamp: Binance returns int epoch-ms → pandas Timestamp
        df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms")

        # Drop internal Binance columns
        drop_cols = [c for c in self.dataframe_constants.DROP_COLUMNS if c in df.columns]
        if drop_cols:
            df = df.drop(columns=drop_cols)

        # OHLCV values arrive as strings from the Binance API → cast to float64
        for c in df.columns:
            if c != "timestamp":
                df[c] = pd.to_numeric(df[c], errors="coerce")

        df["symbol"] = pd.Categorical([active] * len(df))
        return df
