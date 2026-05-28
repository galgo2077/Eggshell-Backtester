"""Live trading visualization placeholders.

Live execution is intentionally separate from synthetic simulation and historical
backtesting. The live pipeline should call these generators only when broker /
exchange execution data is available.
"""

from __future__ import annotations


def generate_live_graphs(*_args, **_kwargs) -> dict:
    return {}
