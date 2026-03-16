"""Streamlit dashboard for monitoring DeepThinkTrader."""

from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests as http_requests
import streamlit as st

from config import Config
from utils.database import Database

st.set_page_config(page_title="DeepThinkTrader", page_icon="📈", layout="wide")
st.title("DeepThinkTrader Dashboard")

db = Database()
config = Config()

# --- Fetch live Alpaca account data ---
@st.cache_data(ttl=30)
def get_alpaca_account():
    try:
        resp = http_requests.get(
            f"{config.ALPACA_BASE_URL}/v2/account",
            headers={
                "APCA-API-KEY-ID": config.ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
            },
            timeout=5,
        )
        if resp.ok:
            return resp.json()
    except Exception:
        pass
    return None

@st.cache_data(ttl=30)
def get_alpaca_positions():
    try:
        resp = http_requests.get(
            f"{config.ALPACA_BASE_URL}/v2/positions",
            headers={
                "APCA-API-KEY-ID": config.ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
            },
            timeout=5,
        )
        if resp.ok:
            return resp.json()
    except Exception:
        pass
    return []

@st.cache_data(ttl=60)
def get_portfolio_history():
    try:
        resp = http_requests.get(
            f"{config.ALPACA_BASE_URL}/v2/account/portfolio/history",
            headers={
                "APCA-API-KEY-ID": config.ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
            },
            params={"period": "1M", "timeframe": "1D"},
            timeout=10,
        )
        if resp.ok:
            return resp.json()
    except Exception:
        pass
    return None


account = get_alpaca_account()
positions = get_alpaca_positions()
portfolio_hist = get_portfolio_history()

# Sidebar
st.sidebar.header("Controls")
if st.sidebar.button("Refresh Data"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.markdown("---")
if account:
    st.sidebar.markdown(f"**Account:** {account.get('account_number', 'N/A')}")
    st.sidebar.markdown(f"**Status:** {'Paper' if account.get('account_number', '').startswith('PA') else 'Live'}")

# === TOP METRICS ROW ===
col1, col2, col3, col4, col5 = st.columns(5)

# Live account data
equity = float(account["equity"]) if account else 0
cash = float(account["cash"]) if account else 0
buying_power = float(account["buying_power"]) if account else 0
starting_balance = 100_000.0
total_pnl = equity - starting_balance

# Trade counts from database (all time, not just today)
all_trades = db.get_recent_trades(500)
total_trades = len(all_trades)
open_trades = db.get_open_trades()
closed_trades = [t for t in all_trades if t.get("status") == "CLOSED"]
winning_trades = [t for t in closed_trades if (t.get("pnl") or 0) > 0]
win_rate = (len(winning_trades) / len(closed_trades) * 100) if closed_trades else 0

with col1:
    st.metric(
        "Portfolio Value",
        f"${equity:,.2f}",
        delta=f"${total_pnl:+,.2f}",
        delta_color="normal" if total_pnl >= 0 else "inverse",
    )
with col2:
    st.metric("Cash Available", f"${cash:,.2f}")
with col3:
    st.metric("Total Trades", total_trades)
with col4:
    st.metric("Open Positions", len(open_trades))
with col5:
    st.metric("Win Rate", f"{win_rate:.0f}%" if closed_trades else "N/A")

st.divider()

# === PORTFOLIO VALUE TIMELINE ===
st.subheader("Portfolio Value Over Time")
if portfolio_hist and portfolio_hist.get("equity"):
    timestamps = portfolio_hist.get("timestamp", [])
    equities = portfolio_hist.get("equity", [])
    pnls = portfolio_hist.get("profit_loss", [])

    if timestamps and equities:
        df_port = pd.DataFrame({
            "date": pd.to_datetime(timestamps, unit="s"),
            "equity": equities,
            "profit_loss": pnls if pnls else [0] * len(equities),
        })

        fig_port = go.Figure()
        fig_port.add_trace(go.Scatter(
            x=df_port["date"],
            y=df_port["equity"],
            mode="lines+markers",
            name="Portfolio Value",
            line=dict(color="#2196F3", width=3),
            fill="tozeroy",
            fillcolor="rgba(33, 150, 243, 0.1)",
        ))
        fig_port.add_hline(
            y=starting_balance,
            line_dash="dash",
            line_color="gray",
            annotation_text=f"Starting Balance (${starting_balance:,.0f})",
        )
        fig_port.update_layout(
            yaxis_title="Portfolio Value ($)",
            xaxis_title="Date",
            height=400,
            margin=dict(l=0, r=0, t=30, b=0),
        )
        st.plotly_chart(fig_port, use_container_width=True)
    else:
        st.info("Portfolio history not available yet — will populate after first trading day")
else:
    st.info("Portfolio history not available yet — will populate after first trading day")

st.divider()

# === LIVE POSITIONS (from Alpaca) ===
st.subheader("Current Positions (Live)")
if positions:
    pos_data = []
    total_unrealized = 0
    total_market_value = 0
    for p in positions:
        unrealized = float(p.get("unrealized_pl", 0))
        unrealized_pct = float(p.get("unrealized_plpc", 0)) * 100
        market_val = float(p.get("market_value", 0))
        total_unrealized += unrealized
        total_market_value += market_val
        pos_data.append({
            "Ticker": p["symbol"],
            "Qty": int(p["qty"]),
            "Avg Entry": f"${float(p['avg_entry_price']):,.2f}",
            "Current": f"${float(p['current_price']):,.2f}",
            "Market Value": f"${market_val:,.2f}",
            "P&L": f"${unrealized:+,.2f}",
            "P&L %": f"{unrealized_pct:+.2f}%",
        })

    df_pos = pd.DataFrame(pos_data)
    st.dataframe(df_pos, use_container_width=True, hide_index=True)

    # Position summary
    pcol1, pcol2, pcol3 = st.columns(3)
    with pcol1:
        st.metric("Total Invested", f"${total_market_value:,.2f}")
    with pcol2:
        st.metric("Unrealized P&L", f"${total_unrealized:+,.2f}")
    with pcol3:
        invested_pct = (total_market_value / equity * 100) if equity > 0 else 0
        st.metric("% Invested", f"{invested_pct:.1f}%")

    # Position P&L bar chart
    if len(pos_data) > 1:
        pnl_df = pd.DataFrame([{
            "ticker": p["Ticker"],
            "pnl": float(positions[i].get("unrealized_pl", 0)),
        } for i, p in enumerate(pos_data)])
        colors = ["#4CAF50" if x >= 0 else "#F44336" for x in pnl_df["pnl"]]
        fig_pnl = go.Figure(go.Bar(
            x=pnl_df["ticker"], y=pnl_df["pnl"],
            marker_color=colors,
        ))
        fig_pnl.update_layout(
            title="Unrealized P&L by Position",
            yaxis_title="P&L ($)",
            height=300,
            margin=dict(l=0, r=0, t=40, b=0),
        )
        st.plotly_chart(fig_pnl, use_container_width=True)
else:
    st.info("No open positions")

st.divider()

# === TRADE HISTORY ===
st.subheader("Trade History")
if all_trades:
    df_trades = pd.DataFrame(all_trades)

    # Format prices as dollar amounts
    for col in ["entry_price", "exit_price", "stop_loss_price", "take_profit_price"]:
        if col in df_trades.columns:
            df_trades[col] = df_trades[col].apply(
                lambda x: f"${x:,.2f}" if x and x > 0 else "—"
            )
    if "pnl" in df_trades.columns:
        df_trades["pnl"] = df_trades["pnl"].apply(
            lambda x: f"${x:+,.2f}" if x else "—"
        )

    display_cols = [
        "ticker", "action", "quantity", "entry_price", "stop_loss_price",
        "take_profit_price", "exit_price", "conviction", "pnl", "status", "timestamp",
    ]
    available_cols = [c for c in display_cols if c in df_trades.columns]
    st.dataframe(df_trades[available_cols], use_container_width=True)

    # Cumulative P&L chart
    closed_df = df_trades[df_trades["status"] == "CLOSED"].copy()
    if not closed_df.empty and "pnl" in closed_df.columns:
        closed_df = closed_df.sort_values("timestamp")
        closed_df["cumulative_pnl"] = closed_df["pnl"].cumsum()
        fig_cum = px.line(
            closed_df, x="timestamp", y="cumulative_pnl",
            title="Cumulative Realized P&L",
        )
        fig_cum.update_layout(yaxis_title="P&L ($)", xaxis_title="Date")
        st.plotly_chart(fig_cum, use_container_width=True)
else:
    st.info("No trades yet")

st.divider()

# === RECENT ANALYSES ===
st.subheader("Recent Analyses")
analyses = db.get_recent_analyses(50)
if analyses:
    df_analysis = pd.DataFrame(analyses)

    # Extract current price from the stored analysis JSON
    prices = []
    for a in analyses:
        try:
            data = json.loads(a.get("analysis_json", "{}"))
            prices.append(data.get("current_price", None))
        except Exception:
            prices.append(None)
    df_analysis["price"] = prices
    df_analysis["price"] = df_analysis["price"].apply(
        lambda x: f"${x:,.2f}" if x else "N/A"
    )

    display_cols = ["ticker", "price", "action", "conviction", "position_size_pct", "stop_loss_pct", "take_profit_pct", "timestamp"]
    available_cols = [c for c in display_cols if c in df_analysis.columns]
    st.dataframe(df_analysis[available_cols], use_container_width=True)

    # Conviction distribution
    fig2 = px.histogram(
        df_analysis, x="conviction", nbins=10,
        title="Conviction Score Distribution",
        color_discrete_sequence=["#2196F3"],
    )
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("No analyses yet")

st.divider()

# === API REQUEST IDS (collapsed) ===
with st.expander("Alpaca API Request IDs (for debugging)"):
    request_ids = db.get_recent_request_ids(30)
    if request_ids:
        df_reqs = pd.DataFrame(request_ids)
        display_cols = ["timestamp", "request_id", "endpoint", "method", "ticker", "order_id", "http_status", "success"]
        available_cols = [c for c in display_cols if c in df_reqs.columns]
        st.dataframe(df_reqs[available_cols], use_container_width=True)
        st.caption("Include the X-Request-ID in any Alpaca support tickets for faster resolution.")
    else:
        st.info("No Alpaca API calls logged yet")

# Footer
st.divider()
st.caption("DeepThinkTrader v1.0 — Paper Trading Mode | Auto-refreshes every 30s")
