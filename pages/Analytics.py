"""Slippage Analytics and Edge Performance Analysis for DeepThinkTrader."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

from config import Config
from utils.database import Database

from utils.brand import ICON_PATH as _ICON
st.set_page_config(page_title="DeepThinkTrader — Analytics", page_icon=_ICON, layout="wide")

# ── Chart Theme ────────────────────────────────────────────────
CHART_COLORS = {
    "primary": "#6c63ff",
    "secondary": "#00d4aa",
    "positive": "#4caf50",
    "negative": "#f44336",
    "neutral": "#8892b0",
    "accent": "#ffd700",
    "bg": "#0e1117",
    "grid": "#1a1a2e",
    "text": "#ccd6f6"
}

CHART_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="#0e1117",
    font=dict(family="'SF Mono', 'Fira Code', monospace", color="#ccd6f6", size=12),
    xaxis=dict(gridcolor="#1a1a2e"),
    yaxis=dict(gridcolor="#1a1a2e"),
    margin=dict(l=0, r=0, t=30, b=0)
)

db = Database()

st.title("Analytics")
st.caption("Slippage analytics and edge performance analysis")

# ── Section 1: Slippage Analytics ──────────────────────────────
st.header("Slippage Analytics")

# Fetch slippage data
with db._get_conn() as conn:
    # KPI metrics
    total_records = conn.execute("SELECT COUNT(*) as count FROM slippage_records").fetchone()
    avg_slippage = conn.execute("SELECT AVG(slippage_pct) as avg FROM slippage_records").fetchone()

    market_avg = conn.execute(
        "SELECT AVG(slippage_pct) as avg FROM slippage_records WHERE order_type = 'market'"
    ).fetchone()

    limit_avg = conn.execute(
        "SELECT AVG(slippage_pct) as avg FROM slippage_records WHERE order_type = 'limit'"
    ).fetchone()

    worst = conn.execute(
        "SELECT MAX(ABS(slippage_pct)) as worst FROM slippage_records"
    ).fetchone()

# KPI Row
col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("Total Records", total_records["count"] if total_records else 0)
col2.metric("Avg Slippage", f"{avg_slippage['avg']:.3f}%" if avg_slippage and avg_slippage['avg'] else "0.000%")
col3.metric("Market Orders", f"{market_avg['avg']:.3f}%" if market_avg and market_avg['avg'] else "0.000%")
col4.metric("Limit Orders", f"{limit_avg['avg']:.3f}%" if limit_avg and limit_avg['avg'] else "0.000%")
col5.metric("Worst Slippage", f"{worst['worst']:.3f}%" if worst and worst['worst'] else "0.000%")

st.markdown("---")

# Slippage by Ticker
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Slippage by Ticker")

    with db._get_conn() as conn:
        ticker_data = conn.execute("""
            SELECT ticker,
                   AVG(slippage_pct) as avg_slippage,
                   COUNT(*) as trade_count
            FROM slippage_records
            GROUP BY ticker
            ORDER BY avg_slippage DESC
            LIMIT 20
        """).fetchall()

    if ticker_data:
        tickers = [row["ticker"] for row in ticker_data]
        slippages = [row["avg_slippage"] for row in ticker_data]
        counts = [row["trade_count"] for row in ticker_data]

        # Color bars based on slippage threshold
        colors = []
        for s in slippages:
            abs_s = abs(s)
            if abs_s > Config.MAX_SLIPPAGE_PCT:  # > 0.3%
                colors.append(CHART_COLORS["negative"])
            elif abs_s > 0.1:  # 0.1-0.3%
                colors.append(CHART_COLORS["accent"])
            else:  # < 0.1%
                colors.append(CHART_COLORS["positive"])

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=tickers,
            y=slippages,
            marker_color=colors,
            text=[f"{s:.3f}% ({c})" for s, c in zip(slippages, counts)],
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Avg: %{y:.3f}%<br>Trades: %{text}<extra></extra>"
        ))

        fig.update_layout(
            **CHART_LAYOUT,
            title="Average Slippage by Ticker",
            xaxis_title="Ticker",
            yaxis_title="Avg Slippage %",
            height=400
        )

        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No slippage data available")

with col_right:
    st.subheader("Slippage by Order Type")

    with db._get_conn() as conn:
        order_type_data = conn.execute("""
            SELECT order_type,
                   AVG(slippage_pct) as avg_slippage,
                   COUNT(*) as trade_count
            FROM slippage_records
            GROUP BY order_type
        """).fetchall()

    if order_type_data:
        order_types = [row["order_type"] for row in order_type_data]
        avg_slips = [row["avg_slippage"] for row in order_type_data]
        trade_counts = [row["trade_count"] for row in order_type_data]

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=order_types,
            y=avg_slips,
            marker_color=[CHART_COLORS["primary"], CHART_COLORS["secondary"]],
            text=[f"{s:.3f}%" for s in avg_slips],
            textposition="outside",
            customdata=trade_counts,
            hovertemplate="<b>%{x}</b><br>Avg: %{y:.3f}%<br>Count: %{customdata}<extra></extra>"
        ))

        fig.update_layout(
            **CHART_LAYOUT,
            title="Market vs Limit Orders",
            xaxis_title="Order Type",
            yaxis_title="Avg Slippage %",
            height=400
        )

        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No order type data available")

# Slippage Over Time
st.subheader("Slippage Over Time")

with db._get_conn() as conn:
    time_data = conn.execute("""
        SELECT timestamp, slippage_pct, order_type, ticker
        FROM slippage_records
        ORDER BY timestamp DESC
        LIMIT 500
    """).fetchall()

if time_data:
    timestamps = [datetime.fromisoformat(row["timestamp"]) for row in time_data]
    slippages = [row["slippage_pct"] for row in time_data]
    order_types = [row["order_type"] for row in time_data]
    tickers = [row["ticker"] for row in time_data]

    fig = go.Figure()

    # Separate market and limit orders
    market_x = [t for t, ot in zip(timestamps, order_types) if ot == "market"]
    market_y = [s for s, ot in zip(slippages, order_types) if ot == "market"]
    market_tickers = [tk for tk, ot in zip(tickers, order_types) if ot == "market"]

    limit_x = [t for t, ot in zip(timestamps, order_types) if ot == "limit"]
    limit_y = [s for s, ot in zip(slippages, order_types) if ot == "limit"]
    limit_tickers = [tk for tk, ot in zip(tickers, order_types) if ot == "limit"]

    if market_x:
        fig.add_trace(go.Scatter(
            x=market_x,
            y=market_y,
            mode="markers",
            name="Market",
            marker=dict(color=CHART_COLORS["primary"], size=6),
            customdata=market_tickers,
            hovertemplate="<b>%{customdata}</b><br>%{x}<br>Slippage: %{y:.3f}%<extra></extra>"
        ))

    if limit_x:
        fig.add_trace(go.Scatter(
            x=limit_x,
            y=limit_y,
            mode="markers",
            name="Limit",
            marker=dict(color=CHART_COLORS["secondary"], size=6),
            customdata=limit_tickers,
            hovertemplate="<b>%{customdata}</b><br>%{x}<br>Slippage: %{y:.3f}%<extra></extra>"
        ))

    # Add threshold line
    fig.add_hline(
        y=Config.MAX_SLIPPAGE_PCT,
        line_dash="dash",
        line_color=CHART_COLORS["negative"],
        annotation_text=f"Max Threshold ({Config.MAX_SLIPPAGE_PCT}%)",
        annotation_position="right"
    )

    fig.update_layout(
        **CHART_LAYOUT,
        title="Slippage Distribution Over Time",
        xaxis_title="Timestamp",
        yaxis_title="Slippage %",
        height=400,
        showlegend=True
    )

    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No time-series slippage data available")

# Slippage by Portfolio
st.subheader("Slippage by Portfolio")

col_main, col_penny = st.columns(2)

with col_main:
    with db._get_conn() as conn:
        main_stats = conn.execute("""
            SELECT AVG(slippage_pct) as avg,
                   MIN(slippage_pct) as min,
                   MAX(slippage_pct) as max,
                   COUNT(*) as count
            FROM slippage_records
            WHERE portfolio = 'main'
        """).fetchone()

    if main_stats and main_stats["count"] > 0:
        st.metric("Main Portfolio", f"{main_stats['avg']:.3f}%")
        st.caption(f"Range: {main_stats['min']:.3f}% to {main_stats['max']:.3f}% ({main_stats['count']} trades)")
    else:
        st.metric("Main Portfolio", "No data")

with col_penny:
    with db._get_conn() as conn:
        penny_stats = conn.execute("""
            SELECT AVG(slippage_pct) as avg,
                   MIN(slippage_pct) as min,
                   MAX(slippage_pct) as max,
                   COUNT(*) as count
            FROM slippage_records
            WHERE portfolio = 'penny'
        """).fetchone()

    if penny_stats and penny_stats["count"] > 0:
        st.metric("Penny Portfolio", f"{penny_stats['avg']:.3f}%")
        st.caption(f"Range: {penny_stats['min']:.3f}% to {penny_stats['max']:.3f}% ({penny_stats['count']} trades)")
    else:
        st.metric("Penny Portfolio", "No data")

st.markdown("---")

# ── Section 2: Edge Performance Analysis ───────────────────────
st.header("Edge Performance Analysis")

# Fetch closed trades with edge details
with db._get_conn() as conn:
    edge_trades = conn.execute("""
        SELECT id, ticker, pnl, conviction, edges_fired, edge_details, portfolio
        FROM trades
        WHERE status = 'CLOSED' AND edge_details IS NOT NULL AND edge_details != '[]'
    """).fetchall()

if not edge_trades:
    st.info("No closed trades with edge data available. Complete some trades to see edge performance.")
else:
    # Parse edge combos
    combo_data = {}

    for trade in edge_trades:
        try:
            edges = json.loads(trade["edge_details"])
            fund = any(e.get("label") == "Fundamental" and e.get("passed") for e in edges)
            tech = any(e.get("label") == "Technical" and e.get("passed") for e in edges)
            sent = any(e.get("label") == "Sentiment" and e.get("passed") for e in edges)

            combo_key = f"F{'✓' if fund else '✗'} T{'✓' if tech else '✗'} S{'✓' if sent else '✗'}"

            if combo_key not in combo_data:
                combo_data[combo_key] = {
                    "count": 0,
                    "wins": 0,
                    "total_pnl": 0,
                    "fund": fund,
                    "tech": tech,
                    "sent": sent
                }

            combo_data[combo_key]["count"] += 1
            if trade["pnl"] > 0:
                combo_data[combo_key]["wins"] += 1
            combo_data[combo_key]["total_pnl"] += trade["pnl"] or 0
        except (json.JSONDecodeError, TypeError):
            continue

    # Calculate win rates and avg P&L
    for combo in combo_data.values():
        combo["win_rate"] = (combo["wins"] / combo["count"]) * 100 if combo["count"] > 0 else 0
        combo["avg_pnl"] = combo["total_pnl"] / combo["count"] if combo["count"] > 0 else 0

    # Edge Combo Heatmap
    st.subheader("Edge Combination Win Rate Matrix")

    # Create matrix data
    combos = sorted(combo_data.keys())
    win_rates = [combo_data[c]["win_rate"] for c in combos]
    trade_counts = [combo_data[c]["count"] for c in combos]
    avg_pnls = [combo_data[c]["avg_pnl"] for c in combos]

    # Create annotated bar chart (easier to read than heatmap with 8 combos)
    fig = go.Figure()

    colors = [CHART_COLORS["positive"] if wr >= 50 else CHART_COLORS["negative"] for wr in win_rates]

    fig.add_trace(go.Bar(
        x=combos,
        y=win_rates,
        marker_color=colors,
        text=[f"{wr:.1f}%<br>({cnt} trades)<br>${pnl:+.0f}" for wr, cnt, pnl in zip(win_rates, trade_counts, avg_pnls)],
        textposition="outside",
        hovertemplate="<b>%{x}</b><br>Win Rate: %{y:.1f}%<br>Trades: %{customdata[0]}<br>Avg P&L: $%{customdata[1]:+.2f}<extra></extra>",
        customdata=list(zip(trade_counts, avg_pnls))
    ))

    fig.update_layout(
        **CHART_LAYOUT,
        title="Win Rate by Edge Combination",
        xaxis_title="Edge Combo (F=Fundamental, T=Technical, S=Sentiment)",
        yaxis_title="Win Rate %",
        height=500
    )

    fig.add_hline(y=50, line_dash="dash", line_color=CHART_COLORS["neutral"], annotation_text="50% Break-even")

    st.plotly_chart(fig, use_container_width=True)

    # Individual Edge Performance
    st.subheader("Individual Edge Performance")

    fund_pass = [t for t in edge_trades if any(e.get("label") == "Fundamental" and e.get("passed") for e in json.loads(t["edge_details"] or "[]"))]
    fund_fail = [t for t in edge_trades if not any(e.get("label") == "Fundamental" and e.get("passed") for e in json.loads(t["edge_details"] or "[]"))]

    tech_pass = [t for t in edge_trades if any(e.get("label") == "Technical" and e.get("passed") for e in json.loads(t["edge_details"] or "[]"))]
    tech_fail = [t for t in edge_trades if not any(e.get("label") == "Technical" and e.get("passed") for e in json.loads(t["edge_details"] or "[]"))]

    sent_pass = [t for t in edge_trades if any(e.get("label") == "Sentiment" and e.get("passed") for e in json.loads(t["edge_details"] or "[]"))]
    sent_fail = [t for t in edge_trades if not any(e.get("label") == "Sentiment" and e.get("passed") for e in json.loads(t["edge_details"] or "[]"))]

    def calc_win_rate(trades):
        if not trades:
            return 0, 0, 0
        wins = sum(1 for t in trades if t["pnl"] > 0)
        win_rate = (wins / len(trades)) * 100 if trades else 0
        avg_pnl = sum(t["pnl"] or 0 for t in trades) / len(trades) if trades else 0
        return win_rate, avg_pnl, len(trades)

    fund_pass_wr, fund_pass_pnl, fund_pass_cnt = calc_win_rate(fund_pass)
    fund_fail_wr, fund_fail_pnl, fund_fail_cnt = calc_win_rate(fund_fail)

    tech_pass_wr, tech_pass_pnl, tech_pass_cnt = calc_win_rate(tech_pass)
    tech_fail_wr, tech_fail_pnl, tech_fail_cnt = calc_win_rate(tech_fail)

    sent_pass_wr, sent_pass_pnl, sent_pass_cnt = calc_win_rate(sent_pass)
    sent_fail_wr, sent_fail_pnl, sent_fail_cnt = calc_win_rate(sent_fail)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.markdown("**Fundamental Edge**")
        st.metric("PASS Win Rate", f"{fund_pass_wr:.1f}%", delta=f"${fund_pass_pnl:+.0f} avg")
        st.caption(f"{fund_pass_cnt} trades")
        st.metric("FAIL Win Rate", f"{fund_fail_wr:.1f}%", delta=f"${fund_fail_pnl:+.0f} avg")
        st.caption(f"{fund_fail_cnt} trades")

    with col2:
        st.markdown("**Technical Edge**")
        st.metric("PASS Win Rate", f"{tech_pass_wr:.1f}%", delta=f"${tech_pass_pnl:+.0f} avg")
        st.caption(f"{tech_pass_cnt} trades")
        st.metric("FAIL Win Rate", f"{tech_fail_wr:.1f}%", delta=f"${tech_fail_pnl:+.0f} avg")
        st.caption(f"{tech_fail_cnt} trades")

    with col3:
        st.markdown("**Sentiment Edge**")
        st.metric("PASS Win Rate", f"{sent_pass_wr:.1f}%", delta=f"${sent_pass_pnl:+.0f} avg")
        st.caption(f"{sent_pass_cnt} trades")
        st.metric("FAIL Win Rate", f"{sent_fail_wr:.1f}%", delta=f"${sent_fail_pnl:+.0f} avg")
        st.caption(f"{sent_fail_cnt} trades")

    st.markdown("---")

    # Edge Pass Rate Over Time (Rolling Window)
    st.subheader("Edge Pass Rate Over Time")

    # Get trades in chronological order
    with db._get_conn() as conn:
        time_trades = conn.execute("""
            SELECT timestamp, edge_details
            FROM trades
            WHERE status = 'CLOSED' AND edge_details IS NOT NULL AND edge_details != '[]'
            ORDER BY timestamp ASC
        """).fetchall()

    if len(time_trades) >= 20:
        window = 20
        fund_rates = []
        tech_rates = []
        sent_rates = []
        timestamps_windowed = []

        for i in range(window, len(time_trades) + 1):
            window_trades = time_trades[i-window:i]

            fund_pass_count = sum(1 for t in window_trades if any(
                e.get("label") == "Fundamental" and e.get("passed")
                for e in json.loads(t["edge_details"] or "[]")
            ))
            tech_pass_count = sum(1 for t in window_trades if any(
                e.get("label") == "Technical" and e.get("passed")
                for e in json.loads(t["edge_details"] or "[]")
            ))
            sent_pass_count = sum(1 for t in window_trades if any(
                e.get("label") == "Sentiment" and e.get("passed")
                for e in json.loads(t["edge_details"] or "[]")
            ))

            fund_rates.append((fund_pass_count / window) * 100)
            tech_rates.append((tech_pass_count / window) * 100)
            sent_rates.append((sent_pass_count / window) * 100)
            timestamps_windowed.append(datetime.fromisoformat(window_trades[-1]["timestamp"]))

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=timestamps_windowed,
            y=fund_rates,
            mode="lines",
            name="Fundamental",
            line=dict(color=CHART_COLORS["primary"], width=2)
        ))

        fig.add_trace(go.Scatter(
            x=timestamps_windowed,
            y=tech_rates,
            mode="lines",
            name="Technical",
            line=dict(color=CHART_COLORS["secondary"], width=2)
        ))

        fig.add_trace(go.Scatter(
            x=timestamps_windowed,
            y=sent_rates,
            mode="lines",
            name="Sentiment",
            line=dict(color=CHART_COLORS["accent"], width=2)
        ))

        fig.update_layout(
            **CHART_LAYOUT,
            title=f"Edge Pass Rate (Rolling {window}-Trade Window)",
            xaxis_title="Time",
            yaxis_title="Pass Rate %",
            height=400,
            showlegend=True
        )

        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info(f"Need at least 20 closed trades to show rolling edge pass rates (currently {len(time_trades)})")

    # Conviction vs Outcome
    st.subheader("Conviction vs Outcome")

    convictions = [t["conviction"] for t in edge_trades if t["conviction"]]
    pnls = [t["pnl"] for t in edge_trades if t["conviction"]]
    tickers = [t["ticker"] for t in edge_trades if t["conviction"]]

    if convictions:
        colors = [CHART_COLORS["positive"] if p > 0 else CHART_COLORS["negative"] for p in pnls]

        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=convictions,
            y=pnls,
            mode="markers",
            marker=dict(color=colors, size=8, line=dict(width=1, color=CHART_COLORS["text"])),
            customdata=tickers,
            hovertemplate="<b>%{customdata}</b><br>Conviction: %{x:.1f}<br>P&L: $%{y:+.2f}<extra></extra>"
        ))

        fig.update_layout(
            **CHART_LAYOUT,
            title="Does Higher Conviction = Better Outcomes?",
            xaxis_title="Conviction Score",
            yaxis_title="P&L ($)",
            height=400
        )

        fig.add_hline(y=0, line_dash="dash", line_color=CHART_COLORS["neutral"])

        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No conviction data available")

# Auto-refresh every 2 minutes
@st.fragment(run_every=120)
def _auto_refresh():
    pass
_auto_refresh()
