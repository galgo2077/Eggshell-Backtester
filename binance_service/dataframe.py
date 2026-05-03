from core.constants import ConnectConstantsBinance, DataframeConstantsBinance
from binance_service.connect import Connect

import os
import threading
import pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed


# Simplified local cache
_CACHE_DIR    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
_CACHE_FILE   = os.path.join(_CACHE_DIR, "binance_klines.pkl")

_MAX_WORKERS = 8

class Dataframe:
    def __init__(self, actives: list[str] | None = None, interval: str | None = None, start_date: str | None = None, end_date: str | None = None):
        self.connect_constants    = ConnectConstantsBinance()
        self.dataframe_constants  = DataframeConstantsBinance()

        # Apply overrides
        if actives:
            self.dataframe_constants.ACTIVES = actives
        if interval:
            self.dataframe_constants.KLINE_INTERVAL = interval
        if start_date:
            self.connect_constants.START_DATE = start_date
        
        self.end_date = end_date # Store for cache key and fetching

        self.connect              = Connect()
        
        # Load partial or full cache
        self.df = self._load_cache()
        
        # Requested symbols
        requested_syms = self.dataframe_constants.ACTIVES
        
        # We will build the final dataframe by checking each asset
        final_parts = []
        
        def process_asset(sym):
            asset_cache = None
            if self.df is not None and not self.df.empty:
                asset_cache = self.df[self.df["symbol"] == sym]
            
            fetch_start = self.connect_constants.START_DATE
            
            if asset_cache is not None and not asset_cache.empty:
                last_time = asset_cache.index.max()
                # If cache already covers the start, we only need from last_time + 1 interval
                # For simplicity, we fetch from last_time to Now.
                fetch_start = str(int(last_time.timestamp() * 1000))
                
            _, rates = self._fetch_klines(sym, fetch_start)
            new_data = self._rates_to_df(sym, rates)
            
            if new_data is not None and not new_data.empty:
                if asset_cache is not None and not asset_cache.empty:
                    # Combine and drop duplicates (in case of overlap at the boundary)
                    combined = pd.concat([asset_cache, new_data])
                    combined = combined[~combined.index.duplicated(keep='last')].sort_index()
                    return combined
                else:
                    return new_data
            return asset_cache

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
            results = list(pool.map(process_asset, requested_syms))
            for res in results:
                if res is not None:
                    final_parts.append(res)

        if final_parts:
            self.df = pd.concat(final_parts).sort_index()
            # Filter to keep only the requested time window
            if self.connect_constants.START_DATE:
                start_ts = pd.to_datetime(self.connect_constants.START_DATE, utc=True).tz_localize(None)
                self.df = self.df[self.df.index >= start_ts]
            if self.end_date:
                end_ts = pd.to_datetime(self.end_date, utc=True).tz_localize(None)
                self.df = self.df[self.df.index <= end_ts]
            
        self._save_cache_sync()

    def _load_cache(self) -> pd.DataFrame | None:
        if not os.path.exists(_CACHE_FILE):
            return None
        try:
            df = pd.read_pickle(_CACHE_FILE)
            if "symbol" not in df.columns:
                return None
            if "interval" in df.attrs and df.attrs["interval"] != self.dataframe_constants.KLINE_INTERVAL:
                return None
            # Ensure the index is timezone-naive UTC
            if not df.empty:
                df.index = pd.to_datetime(df.index, utc=True).tz_localize(None)
            return df
        except Exception:
            return None

    def _save_cache_sync(self):
        if self.df is None or self.df.empty:
            return
        try:
            os.makedirs(_CACHE_DIR, exist_ok=True)
            # Save interval in metadata
            self.df.attrs["interval"] = self.dataframe_constants.KLINE_INTERVAL
            self.df.to_pickle(_CACHE_FILE)
        except Exception:
            pass

    def _save_cache(self):
        snapshot = self.df.copy() if self.df is not None else None
        if snapshot is None or snapshot.empty:
            return
        def _write():
            try:
                os.makedirs(_CACHE_DIR, exist_ok=True)
                snapshot.to_pickle(_CACHE_FILE)
            except Exception:
                pass
        threading.Thread(target=_write, daemon=True).start()

    def _fetch_klines(self, active: str, start: str) -> tuple[str, list]:
        try:
            rates = self.connect.client.get_historical_klines(
                active, self.dataframe_constants.KLINE_INTERVAL, start, end_str=self.end_date
            )
            return active, rates or []
        except Exception:
            return active, []

    def _rates_to_df(self, active: str, rates: list) -> pd.DataFrame | None:
        if not rates:
            return None
        df_temp = pd.DataFrame(rates, columns=self.dataframe_constants.KLINE_COLUMNS)
        df_temp["timestamp"] = pd.to_datetime(df_temp["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
        df_temp.set_index("timestamp", inplace=True)
        df_temp = df_temp.astype(float)
        df_temp["symbol"] = active
        return df_temp

    def _build_dataframe_for_assets(self, assets: list[str]) -> pd.DataFrame:
        try:
            partial_frames = []
            with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
                futures = {
                    pool.submit(self._fetch_klines, active, self.connect_constants.START_DATE): active
                    for active in assets
                }
                for future in as_completed(futures):
                    active, rates = future.result()
                    df_temp = self._rates_to_df(active, rates)
                    if df_temp is not None:
                        partial_frames.append(df_temp)
            if not partial_frames:
                return pd.DataFrame()
            df = pd.concat(partial_frames)
            df.sort_index(inplace=True)
            df.drop(columns=self.dataframe_constants.DROP_COLUMNS, inplace=True, errors="ignore")
            return df
        except Exception:
            return pd.DataFrame()

    def _build_dataframe(self) -> pd.DataFrame:
        return self._build_dataframe_for_assets(self.dataframe_constants.ACTIVES)

    def update(self) -> pd.DataFrame:
        try:
            symbol_starts: dict[str, str] = {}
            for active in self.dataframe_constants.ACTIVES:
                active_df = self.df[self.df["symbol"] == active]
                symbol_starts[active] = (
                    self.connect_constants.START_DATE
                    if active_df.empty
                    else active_df.index[-1].strftime("%Y-%m-%d %H:%M:%S")
                )
            partial_frames = []
            with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
                futures = {
                    pool.submit(self._fetch_klines, active, start): active
                    for active, start in symbol_starts.items()
                }
                for future in as_completed(futures):
                    active, rates = future.result()
                    df_temp = self._rates_to_df(active, rates)
                    if df_temp is not None:
                        partial_frames.append(df_temp)
            if not partial_frames:
                return self.df
            new_df = pd.concat(partial_frames)
            new_df.drop(columns=self.dataframe_constants.DROP_COLUMNS, inplace=True, errors="ignore")
            combined = pd.concat([self.df, new_df])
            combined.reset_index(inplace=True)
            combined.drop_duplicates(subset=["timestamp", "symbol"], keep="last", inplace=True)
            combined.set_index("timestamp", inplace=True)
            # Final safety check: ensure index is naive UTC
            combined.index = pd.to_datetime(combined.index, utc=True).tz_localize(None)
            combined.sort_index(inplace=True)
            self.df = combined
            self._save_cache()
        except Exception:
            pass
        return self.df