"""Monte Carlo visualization generators."""

from __future__ import annotations

import os


def generate_montecarlo_graphs(simulation_results: list[dict], charts_dir: str) -> dict:
    import numpy as np
    import plotly.graph_objects as go

    os.makedirs(charts_dir, exist_ok=True)
    charts = {
        "mc_path_cloud": os.path.join(charts_dir, "montecarlo_path_cloud.html"),
        "mc_percentiles": os.path.join(charts_dir, "montecarlo_percentile_envelope.html"),
        "mc_terminal_distribution": os.path.join(charts_dir, "montecarlo_terminal_distribution.html"),
        "mc_drawdown_distribution": os.path.join(charts_dir, "montecarlo_drawdown_distribution.html"),
        "mc_3d": os.path.join(charts_dir, "montecarlo_3d_simulation_space.html"),
    }
    histories = [r.get("equity_history", []) for r in simulation_results if r.get("equity_history")]
    if not histories:
        return charts

    min_len = min(len(h) for h in histories)
    paths = np.array([h[:min_len] for h in histories], dtype=float)
    x = np.arange(min_len)

    cloud = go.Figure()
    step = max(1, len(paths) // 80)
    for i, path in enumerate(paths[::step]):
        cloud.add_trace(go.Scatter(
            x=x, y=path, mode="lines",
            line=dict(width=1, color="rgba(129,140,248,0.22)"),
            name=f"Simulation path {i * step + 1}",
            showlegend=False,
        ))
    cloud.update_layout(
        title="Monte Carlo - Simulation Path Cloud",
        paper_bgcolor="#0b0f19", plot_bgcolor="#111827",
        font=dict(color="#e5e7eb"),
        xaxis=dict(title="Simulation step", gridcolor="#1f2937"),
        yaxis=dict(title="Synthetic equity", gridcolor="#1f2937"),
    )
    cloud.write_html(charts["mc_path_cloud"])

    percentiles = {
        "p05": np.percentile(paths, 5, axis=0),
        "p25": np.percentile(paths, 25, axis=0),
        "p50": np.percentile(paths, 50, axis=0),
        "p75": np.percentile(paths, 75, axis=0),
        "p95": np.percentile(paths, 95, axis=0),
    }
    env = go.Figure()
    env.add_trace(go.Scatter(x=x, y=percentiles["p95"], line=dict(width=0), showlegend=False, name="95th"))
    env.add_trace(go.Scatter(x=x, y=percentiles["p05"], fill="tonexty", line=dict(width=0),
                             fillcolor="rgba(56,189,248,0.18)", name="5-95% band"))
    env.add_trace(go.Scatter(x=x, y=percentiles["p75"], line=dict(width=0), showlegend=False, name="75th"))
    env.add_trace(go.Scatter(x=x, y=percentiles["p25"], fill="tonexty", line=dict(width=0),
                             fillcolor="rgba(34,197,94,0.20)", name="25-75% band"))
    env.add_trace(go.Scatter(x=x, y=percentiles["p50"], mode="lines", name="Median path",
                             line=dict(color="#fbbf24", width=3)))
    env.update_layout(
        title="Monte Carlo - Percentile Envelope and Confidence Bands",
        paper_bgcolor="#0b0f19", plot_bgcolor="#111827",
        font=dict(color="#e5e7eb"),
        xaxis=dict(title="Simulation step", gridcolor="#1f2937"),
        yaxis=dict(title="Synthetic equity", gridcolor="#1f2937"),
    )
    env.write_html(charts["mc_percentiles"])

    terminal = paths[:, -1]
    hist = go.Figure(go.Histogram(x=terminal, nbinsx=40, marker_color="#38bdf8"))
    hist.update_layout(
        title="Monte Carlo - Terminal Value Distribution",
        paper_bgcolor="#0b0f19", plot_bgcolor="#111827",
        font=dict(color="#e5e7eb"),
        xaxis=dict(title="Terminal synthetic equity", gridcolor="#1f2937"),
        yaxis=dict(title="Path count", gridcolor="#1f2937"),
    )
    hist.write_html(charts["mc_terminal_distribution"])

    peaks = np.maximum.accumulate(paths, axis=1)
    drawdowns = (paths / np.where(peaks == 0, 1, peaks) - 1) * 100
    max_dd = drawdowns.min(axis=1)
    dd = go.Figure(go.Histogram(x=max_dd, nbinsx=40, marker_color="#fb7185"))
    dd.update_layout(
        title="Monte Carlo - Drawdown Distribution",
        paper_bgcolor="#0b0f19", plot_bgcolor="#111827",
        font=dict(color="#e5e7eb"),
        xaxis=dict(title="Worst path drawdown (%)", gridcolor="#1f2937"),
        yaxis=dict(title="Path count", gridcolor="#1f2937"),
    )
    dd.write_html(charts["mc_drawdown_distribution"])

    surface_paths = paths[: min(len(paths), 80)]
    fig3d = go.Figure(go.Surface(
        z=surface_paths,
        x=x,
        y=np.arange(surface_paths.shape[0]),
        colorscale="Viridis",
        showscale=True,
    ))
    fig3d.update_layout(
        title="Monte Carlo - 3D Simulation Space",
        paper_bgcolor="#0b0f19",
        font=dict(color="#e5e7eb"),
        scene=dict(
            xaxis_title="Simulation step",
            yaxis_title="Path index",
            zaxis_title="Synthetic equity",
        ),
    )
    fig3d.write_html(charts["mc_3d"])
    return charts
