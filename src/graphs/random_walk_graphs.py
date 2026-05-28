"""Random Walk visualization generators."""

from __future__ import annotations

import os


def generate_random_walk_graphs(close_df, results: dict, charts_dir: str) -> dict:
    import plotly.graph_objects as go

    os.makedirs(charts_dir, exist_ok=True)
    charts = {
        "rw_paths": os.path.join(charts_dir, "random_walk_stochastic_paths.html"),
        "rw_drift_volatility": os.path.join(charts_dir, "random_walk_drift_volatility.html"),
    }
    if close_df.empty:
        return charts

    fig = go.Figure()
    for col in close_df.columns:
        y = close_df[col].ffill()
        fig.add_trace(go.Scatter(
            x=close_df.index, y=y,
            mode="lines", name=f"Synthetic path {len(fig.data) + 1}",
            hovertemplate="Synthetic path<br>%{x}<br>%{y:.4f}<extra></extra>",
        ))
    fig.update_layout(
        title="Random Walk - Stochastic Synthetic Paths",
        paper_bgcolor="#0b0f19", plot_bgcolor="#111827",
        font=dict(color="#e5e7eb"),
        xaxis=dict(title="Synthetic time", gridcolor="#1f2937"),
        yaxis=dict(title="Synthetic price level", gridcolor="#1f2937"),
    )
    fig.write_html(charts["rw_paths"])

    returns = close_df.pct_change().replace([float("inf"), float("-inf")], 0).fillna(0)
    roll_vol = returns.rolling(30, min_periods=2).std() * 100
    roll_mean = returns.rolling(30, min_periods=2).mean() * 100
    fig2 = go.Figure()
    fig2.add_trace(go.Scatter(x=roll_mean.index, y=roll_mean.mean(axis=1), mode="lines", name="Rolling drift"))
    fig2.add_trace(go.Scatter(x=roll_vol.index, y=roll_vol.mean(axis=1), mode="lines", name="Rolling volatility"))
    fig2.update_layout(
        title="Random Walk - Drift and Volatility Propagation",
        paper_bgcolor="#0b0f19", plot_bgcolor="#111827",
        font=dict(color="#e5e7eb"),
        xaxis=dict(title="Synthetic time", gridcolor="#1f2937"),
        yaxis=dict(title="% per bar", gridcolor="#1f2937"),
    )
    fig2.write_html(charts["rw_drift_volatility"])
    return charts
