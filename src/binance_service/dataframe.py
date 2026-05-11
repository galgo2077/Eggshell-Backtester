from core.constants import ConnectConstantsBinance, DataframeConstantsBinance
from binance_service.connect import Connect

import os
import threading
import pandas as pd
from concurrent.futures import ThreadPoolExecutor


_CACHE_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
_MAX_WORKERS = 8


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

        # Purge legacy all-in-one cache files
        self._purge_old_caches()

        self._completed      = 0
        self._completed_lock = threading.Lock()
        self._total_assets   = len(self.dataframe_constants.ACTIVES)

        final_parts = []
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            for result in pool.map(self._process_asset, self.dataframe_constants.ACTIVES):
                if result is not None:
                    final_parts.append(result)

        if final_parts:
            full_df  = pd.concat(final_parts).sort_index()
            start_ts = pd.to_datetime(self.connect_constants.START_DATE).tz_localize(None)
            self.df  = full_df[full_df.index >= start_ts]
            if self.end_date:
                end_ts  = pd.to_datetime(self.end_date).tz_localize(None)
                self.df = self.df[self.df.index <= end_ts]
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
            df.index = pd.to_datetime(df.index).tz_localize(None)
            return df
        except Exception:
            return None

    def _save_sym_cache(self, sym: str, df: pd.DataFrame):
        if df is None or df.empty:
            return
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            df.to_parquet(self._sym_cache_path(sym))
        except Exception:
            pass

    # ── Fetch helpers ─────────────────────────────────────────────────────────

    def _process_asset(self, sym: str) -> pd.DataFrame | None:
        cached = self._load_sym_cache(sym)
        parts  = [cached] if (cached is not None and not cached.empty) else []

        # Forward fetch: new candles since last cached (or full history if no cache)
        fwd_start = (
            str(int(cached.index.max().timestamp() * 1000))
            if parts else self.connect_constants.START_DATE
        )
        _, rates = self._fetch_klines(sym, fwd_start)
        new_fwd  = self._rates_to_df(sym, rates)
        if new_fwd is not None:
            parts.append(new_fwd)

        # Backward fetch: fill gap when user requests earlier data than cache holds
        if cached is not None and not cached.empty:
            req_start = pd.to_datetime(self.connect_constants.START_DATE).tz_localize(None)
            if req_start < cached.index.min():
                end_ms     = str(int(cached.index.min().timestamp() * 1000))
                _, rates_old = self._fetch_klines(sym, self.connect_constants.START_DATE, end_ms=end_ms)
                new_bwd    = self._rates_to_df(sym, rates_old)
                if new_bwd is not None:
                    parts.append(new_bwd)

        with self._completed_lock:
            self._completed += 1
            pct = self._completed / max(self._total_assets, 1)

        if not parts:
            if self._on_progress:
                self._on_progress(pct, f"NO DATA: {sym}")
            return None

        combined = pd.concat(parts)
        result   = combined[~combined.index.duplicated(keep='last')].sort_index()

        # Save per-symbol cache (full unfiltered history)
        self._save_sym_cache(sym, result)

        if self._on_progress:
            self._on_progress(pct, f"CACHED {sym}  ({len(result):,} candles)")

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
        df = pd.DataFrame(rates, columns=self.dataframe_constants.KLINE_COLUMNS)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
        df.set_index("timestamp", inplace=True)
        df.drop(columns=self.dataframe_constants.DROP_COLUMNS, inplace=True, errors="ignore")
        df = df.astype(float)
        df["symbol"] = active
        return df
