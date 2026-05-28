"""Execution-environment identifiers and normalization helpers."""

MONTE_CARLO = "monte_carlo"
RANDOM_WALK = "random_walk"
REAL_MARKET_BACKTEST = "real_market_backtest"
LIVE_TRADING = "live_trading"

DATA_SOURCE_TO_MODE = {
    "MONTE_CARLO": MONTE_CARLO,
    "RANDOM_WALK": RANDOM_WALK,
    "REAL": REAL_MARKET_BACKTEST,
    "LIVE": LIVE_TRADING,
}


def normalize_mode(value: str | None) -> str:
    raw = str(value or "REAL").strip()
    upper = raw.upper()
    if upper in DATA_SOURCE_TO_MODE:
        return DATA_SOURCE_TO_MODE[upper]

    lower = raw.lower()
    aliases = {
        "montecarlo": MONTE_CARLO,
        "monte_carlo": MONTE_CARLO,
        "randomwalk": RANDOM_WALK,
        "random_walk": RANDOM_WALK,
        "real": REAL_MARKET_BACKTEST,
        "real_market": REAL_MARKET_BACKTEST,
        "real_market_backtest": REAL_MARKET_BACKTEST,
        "live": LIVE_TRADING,
        "live_trading": LIVE_TRADING,
    }
    return aliases.get(lower, REAL_MARKET_BACKTEST)


def mode_from_setup(setup_info: dict | None) -> str:
    setup_info = setup_info or {}
    return normalize_mode(
        setup_info.get("execution_mode")
        or setup_info.get("simulation_mode")
        or setup_info.get("data_source")
    )
