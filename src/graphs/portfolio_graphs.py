"""Real-market portfolio chart generation."""

from __future__ import annotations

import json
import os


def generate_portfolio_graphs(close_df, formatted_trades, portfolio, charts_dir: str) -> dict:
    charts = {
        "main":       os.path.join(charts_dir, "real_market_portfolio_report.html"),
        "trades":     os.path.join(charts_dir, "real_market_trades.html"),
        "underwater": os.path.join(charts_dir, "real_market_underwater.html"),
        "value":      os.path.join(charts_dir, "real_market_value.html"),
        "drawdowns":  os.path.join(charts_dir, "real_market_drawdowns.html"),
        "returns":    os.path.join(charts_dir, "real_market_returns.html"),
        "cash":       os.path.join(charts_dir, "real_market_cash.html"),
    }
    if close_df.empty:
        return charts

    os.makedirs(charts_dir, exist_ok=True)
    write_trades_chart(close_df, formatted_trades, charts["trades"])
    for key, method in [
        ("main",       portfolio.plot),
        ("underwater", portfolio.plot_underwater),
        ("value",      portfolio.plot_value),
        ("drawdowns",  portfolio.plot_drawdowns),
        ("returns",    portfolio.plot_cum_returns),
        ("cash",       portfolio.plot_cash_flow),
    ]:
        try:
            method().write_html(charts[key])
        except Exception:
            pass
    return charts


def write_trades_chart(close_df, formatted_trades, path: str) -> None:
    import plotly.graph_objects as go

    colors = ['#818cf8', '#34d399', '#fb7185', '#fbbf24', '#22d3ee', '#a78bfa']
    symbols = list(close_df.columns)
    traces_per_symbol = 3

    fig = go.Figure()
    for idx, symbol in enumerate(symbols):
        color = colors[idx % len(colors)]
        is_first = idx == 0
        sym_trades = [t for t in formatted_trades if t['symbol'] == symbol]

        fig.add_trace(go.Scatter(
            x=close_df.index, y=close_df[symbol],
            mode='lines', name=f'{symbol} Price',
            line=dict(color=color, width=2), opacity=0.9,
            visible=is_first,
        ))
        fig.add_trace(go.Scatter(
            x=[t['buy_time'] for t in sym_trades],
            y=[t['buy_price'] for t in sym_trades],
            mode='markers', name='BUY',
            marker=dict(symbol='triangle-up', size=16, color='#22c55e',
                        line=dict(color='#15803d', width=2)),
            hovertemplate='<b>BUY</b><br>%{x}<br>$%{y:,.4f}<extra></extra>',
            visible=is_first,
        ))
        fig.add_trace(go.Scatter(
            x=[t['sell_time'] for t in sym_trades],
            y=[t['sell_price'] for t in sym_trades],
            mode='markers', name='SELL',
            marker=dict(symbol='triangle-down', size=16, color='#ef4444',
                        line=dict(color='#b91c1c', width=2)),
            hovertemplate='<b>SELL</b><br>%{x}<br>$%{y:,.4f}<extra></extra>',
            visible=is_first,
        ))

    buttons = []
    for idx, symbol in enumerate(symbols):
        visible = [False] * (len(symbols) * traces_per_symbol)
        for j in range(traces_per_symbol):
            visible[idx * traces_per_symbol + j] = True
        buttons.append(dict(
            label=symbol,
            method='update',
            args=[{'visible': visible},
                  {'title': {'text': f'Trade Execution - {symbol}',
                             'font': {'color': '#f8fafc', 'size': 22, 'family': 'Arial'}}}]
        ))

    fig.update_layout(
        title=dict(text=f'Trade Execution - {symbols[0] if symbols else ""}',
                   font=dict(color='#f8fafc', size=22, family='Arial')),
        paper_bgcolor='#0b0f19', plot_bgcolor='#111827',
        hovermode='x unified',
        updatemenus=[dict(
            buttons=buttons,
            direction='down',
            showactive=True,
            x=0.0, xanchor='left',
            y=1.18, yanchor='top',
            bgcolor='#1e293b', bordercolor='#00ffff',
            font=dict(color='#f8fafc', size=13),
        )],
        legend=dict(font=dict(color='#94a3b8', size=12),
                    bgcolor='rgba(11,15,25,0.85)', bordercolor='#334155', borderwidth=1),
        xaxis=dict(title=dict(text='Date', font=dict(color='#94a3b8', size=12)),
                   tickfont=dict(color='#94a3b8'), gridcolor='#1f2937',
                   rangeslider=dict(visible=True)),
        yaxis=dict(title=dict(text='Price ($)', font=dict(color='#94a3b8', size=12)),
                   tickfont=dict(color='#94a3b8'), gridcolor='#1f2937'),
        margin=dict(l=50, r=50, t=110, b=50),
    )

    html = fig.to_html(full_html=True, include_plotlyjs='cdn')
    symbols_js = json.dumps(symbols)
    js = f"""
<script>
(function() {{
  function applyHash() {{
    var symbols = {symbols_js};
    var hash = decodeURIComponent(window.location.hash.replace('#', ''));
    var idx = symbols.indexOf(hash);
    if (idx < 0) return;
    var n = {traces_per_symbol};
    var visible = [];
    for (var i = 0; i < symbols.length * n; i++) {{
      visible.push(Math.floor(i / n) === idx);
    }}
    var gd = document.querySelector('.js-plotly-plot');
    if (gd) {{
      Plotly.restyle(gd, {{visible: visible}});
      Plotly.relayout(gd, {{title: {{text: 'Trade Execution - ' + hash}}}});
    }}
  }}
  if (document.readyState === 'complete') {{ applyHash(); }}
  else {{ window.addEventListener('load', applyHash); }}
}})();
</script>
"""
    with open(path, 'w') as f:
        f.write(html.replace('</body>', js + '</body>'))
