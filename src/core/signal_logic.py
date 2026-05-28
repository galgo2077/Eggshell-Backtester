"""
SignalLogic — Modular coordinator for applying indicators and generating signals.
"""

import pandas as pd
from strategies import STRATEGY_CLASSES, STRATEGY_REGISTRY


class SignalLogic:
    def __init__(self, df,
                 ENABLED_EMA: bool = True,
                 FAST_EMA: int = 9,
                 SLOW_EMA: int = 21,
                 ENABLED_MFI: bool = False,
                 MFI_LENGTH: int = 14,
                 BUY_LEVEL: float = 30.0,
                 SELL_LEVEL: float = 70.0,
                 on_progress: callable = None,
                 **kwargs):

        self.params = {
            "ENABLED_EMA": ENABLED_EMA,
            "FAST_EMA": FAST_EMA,
            "SLOW_EMA": SLOW_EMA,
            "ENABLED_MFI": ENABLED_MFI,
            "MFI_LENGTH": MFI_LENGTH,
            "BUY_LEVEL": BUY_LEVEL,
            "SELL_LEVEL": SELL_LEVEL,
            "on_progress": on_progress,
            **kwargs
        }
        
        self.input_df = df.copy()
        self.processed_dfs = []
        
        strategy_name = self.params.get("STRATEGY", "EMA_CROSS")
        
        unique_symbols = self.input_df["symbol"].unique() if "symbol" in self.input_df.columns else [None]
        
        for sym in unique_symbols:
            if sym is not None:
                current_df = self.input_df[self.input_df["symbol"] == sym].copy()
            else:
                current_df = self.input_df.copy()
                
            if current_df.empty:
                continue
                
            if strategy_name == "DUAL_STRATEGY":
                current_df = self._run_dual(current_df)
            else:
                strategy_cls = self._get_strategy_class(strategy_name)
                if strategy_cls is None:
                    raise ValueError(f"Unknown strategy: '{strategy_name}'. Check STRATEGY_CLASSES registry.")
                strategy = strategy_cls(current_df, **self.params)
                current_df = strategy.apply_indicators()
                current_df = strategy.generate_signals()
            
            self.processed_dfs.append(current_df)
            
        if self.processed_dfs:
            self.df = pd.concat(self.processed_dfs).sort_index()
        else:
            self.df = self.input_df.copy()
            self.df["buy"] = False
            self.df["sell"] = False
        
        self.indicators = self._build_indicators_df()
        self.signals    = self._build_signals_df()

    def _get_strategy_class(self, name: str):
        cls = STRATEGY_CLASSES.get(name)
        if cls is None:
            for mod in STRATEGY_REGISTRY.values():
                const = getattr(mod, "constants", None)
                if const and getattr(const, "STRATEGY_NAME", None) == name:
                    for attr in vars(mod).values():
                        if isinstance(attr, type) and attr.__name__.endswith("Strategy"):
                            return attr
        return cls

    def _run_dual(self, df: pd.DataFrame) -> pd.DataFrame:
        from core.constants import STRATEGY_SCHEMAS

        name_a    = self.params.get("STRATEGY_A", "EMA_CROSS")
        name_b    = self.params.get("STRATEGY_B", "ELLIOT_BOLLINGER")
        condition = self.params.get("CONDITION", "AND")
        on_prog   = self.params.get("on_progress")

        def _build_params(name: str, overrides: dict) -> dict:
            p = {"STRATEGY": name, "on_progress": on_prog}
            for section in STRATEGY_SCHEMAS.get(name, {}).values():
                for k, v in section.items():
                    p[k] = overrides.get(k, v["default"])
            return p

        def _execute(name: str, source: pd.DataFrame, p: dict) -> pd.DataFrame:
            cls = self._get_strategy_class(name)
            if cls is None:
                from strategies.Ema_cross import EMACrossStrategy
                cls = EMACrossStrategy
            s = cls(source, **p)
            s.apply_indicators()
            return s.generate_signals()

        df_a = _execute(name_a, df.copy(), _build_params(name_a, self.params.get("PARAMS_A", {})))
        df_b = _execute(name_b, df.copy(), _build_params(name_b, self.params.get("PARAMS_B", {})))

        result = df.copy()
        for col in list(df_a.columns) + list(df_b.columns):
            if col not in result.columns and col not in ("buy", "sell"):
                result[col] = df_a[col] if col in df_a.columns else df_b[col]

        if condition == "OR":
            result["buy"]  = df_a["buy"]  | df_b["buy"]
            result["sell"] = df_a["sell"] | df_b["sell"]
        else:
            result["buy"]  = df_a["buy"]  & df_b["buy"]
            result["sell"] = df_a["sell"] & df_b["sell"]

        return result

    def _build_indicators_df(self):
        # Dynamically include columns that are not OHLCV or metadata
        metadata_cols = ["open", "high", "low", "close", "volume", "buy", "sell"]
        cols = ["symbol"] + [c for c in self.df.columns if c not in metadata_cols and c != "symbol"]
        return self.df[cols].copy()

    def _build_signals_df(self):
        return self.df[["symbol", "close", "buy", "sell"]].copy()