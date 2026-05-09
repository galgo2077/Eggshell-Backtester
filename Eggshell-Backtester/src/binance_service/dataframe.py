from core.constants import ConnectConstantsBinance, DataframeConstantsBinance
from binance_service.connect import Connect

import os
import pandas as pd
from concurrent.futures import ThreadPoolExecutor


_CACHE_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
_CACHE_FILE = os.path.join(_CACHE_DIR, "binance_klines.pkl")
_MAX_WORKERS = 8


class Dataframe:
    def __init__(self, actives: list[str] | None = None, interval: str | None = None,
                 start_date: str | None = None, end_date: str | None = None):
        self.connect_constants   = ConnectConstantsBinance()
        self.dataframe_constants = DataframeConstantsBinance()

        if actives:
            self.dataframe_constants.ACTIVES = actives
        if interval:
            self.dataframe_constants.KLINE_INTERVAL = interval
        if start_date:
            self.connect_constants.START_DATE = start_date

        self.end_date    = end_date
        self.connect     = Connect()
        self._full_cache = self._load_cache()   # full history, never filtered

        final_parts = []
        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            for result in pool.map(self._process_asset, self.dataframe_constants.ACTIVES):
                if result is not None:
                    final_parts.append(result)

        if final_parts:
            full_df = pd.concat(final_parts).sort_index()
            self._save_cache(full_df)           # persist BEFORE filtering

            start_ts = pd.to_datetime(self.connect_constants.START_DATE, utc=True).tz_localize(None)
            self.df  = full_df[full_df.index >= start_ts]
            if self.end_date:
                end_ts  = pd.to_datetime(self.end_date, utc=True).tz_localize(None)
                self.df = self.df[self.df.index <= end_ts]
        else:
            self.df = pd.DataFrame()

    def _process_asset(self, sym: str) -> pd.DataFrame | None:
        cached = None
        if self._full_cache is not None and not self._full_cache.empty:
            cached = self._full_cache[self._full_cache["symbol"] == sym]

        parts = [cached] if (cached is not None and not cached.empty) else []

        # Forward fetch: new candles since last cached (or full history if no cache)
        fwd_start = (
            str(int(cached.index.max().timestamp() * 1000))
            if parts else self.connect_constants.START_DATE
        )
        _, rates = self._fetch_klines(sym, fwd_start)
        new_fwd = self._rates_to_df(sym, rates)
        if new_fwd is not None:
            parts.append(new_fwd)

        # Backward fetch: fill the gap when user requests earlier data than cache holds
        if cached is not None and not cached.empty:
            req_start = pd.to_datetime(
                self.connect_constants.START_DATE, utc=True
            ).tz_localize(None)
            if req_start < cached.index.min():
                end_ms = str(int(cached.index.min().timestamp() * 1000))
                _, rates_old = self._fetch_klines(sym, self.connect_constants.START_DATE, end_ms=end_ms)
                new_bwd = self._rates_to_df(sym, rates_old)
                if new_bwd is not None:
                    parts.append(new_bwd)

        if not parts:
            return None
        combined = pd.concat(parts)
        return combined[~combined.index.duplicated(keep='last')].sort_index()

    def _load_cache(self) -> pd.DataFrame | None:
        if not os.path.exists(_CACHE_FILE):
            return None
        try:
            df = pd.read_pickle(_CACHE_FILE)
            if "symbol" not in df.columns:
                return None
            if df.attrs.get("interval") != self.dataframe_constants.KLINE_INTERVAL:
                return None
            if not df.empty:
                df.index = pd.to_datetime(df.index, utc=True).tz_localize(None)
            return df
        except Exception:
            return None

    def _save_cache(self, df: pd.DataFrame):
        if df is None or df.empty:
            return
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            df.attrs["interval"] = self.dataframe_constants.KLINE_INTERVAL
            df.to_pickle(_CACHE_FILE)
        except Exception:
            pass

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
