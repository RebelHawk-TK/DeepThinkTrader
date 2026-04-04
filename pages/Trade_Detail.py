"""Trade Detail page for DeepThinkTrader dashboard.

Displays the full story of a single trade with reasoning, edge analysis,
price timeline, partial exits, slippage, and risk metrics.
"""

from __future__ import annotations

import json
from datetime import datetime as dt, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from config import Config
from utils.database import Database

st.set_page_config(page_title="Trade Detail", page_icon="📊", layout="wide")

# ── Chart Theme (consistent with dashboard.py) ──────────────
CHART_COLORS = {
    "primary": "#6c63ff",
    "secondary": "#00d4aa",
    "positive": "#4caf50",
    "negative": "#f44336",
    "neutral": "#8892b0",
    "accent": "#ffd700",
    "bg": "#0e1117",
    "grid": "#1a1a2e",
    "text": "#ccd6f6",
}

CHART_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="#0e1117",
    font=dict(family="'SF Mono', 'Fira Code', monospace", color="#ccd6f6", size=12),
    xaxis=dict(gridcolor="#1a1a2e", showgrid=True, gridwidth=1),
    yaxis=dict(gridcolor="#1a1a2e", showgrid=True, gridwidth=1),
    margin=dict(l=0, r=0, t=30, b=0),
    legend=dict(bgcolor="rgba(0,0,0,0)"),
)

def apply_chart_theme(fig):
    """Apply consistent dark theme to any Plotly figure."""
    fig.update_layout(**CHART_LAYOUT)
    return fig

# ── Global CSS ─────────────────────────────────────────────
st.markdown("""<style>
.kpi-card {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    border: 1px solid #2a2a4a;
    border-radius: 12px;
    padding: 20px 16px 16px;
    margin-bottom: 12px;
}
.section-header {
    font-size: 1.1rem;
    font-weight: 700;
    color: #8892b0;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    margin: 24px 0 12px;
    padding-bottom: 8px;
    border-bottom: 2px solid #2a2a4a;
}
.reasoning-box {
    background: #0a1929;
    border-left: 4px solid #6c63ff;
    padding: 16px;
    border-radius: 8px;
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 0.95rem;
    line-height: 1.6;
    color: #ccd6f6;
    margin: 16px 0;
}
.edge-pass {
    color: #4caf50;
    font-weight: 600;
}
.edge-fail {
    color: #f44336;
    font-weight: 600;
}
</style>""", unsafe_allow_html=True)

db = Database()

# ── Trade Selection ────────────────────────────────────────
st.title("Trade Detail")

# Allow deep-linking via query params
query_params = st.query_params
trade_id_param = query_params.get("trade_id")

recent_trades = db.get_recent_trades(limit=500)

if not recent_trades:
    st.warning("No trades found in database.")
    st.stop()

# Format trade options for selectbox
def format_trade_option(trade):
    """Format trade for display in selectbox."""
    ts = dt.fromisoformat(trade["timestamp"]).strftime("%Y-%m-%d %H:%M")
    action = trade["action"]
    ticker = trade["ticker"]
    status = trade["status"]
    pnl = trade.get("pnl") or 0.0
    pnl_str = f"${pnl:+.2f}" if status == "CLOSED" else "OPEN"
    return f"{ticker} — {action} — {ts} — {status} ({pnl_str})"

trade_options = {format_trade_option(t): t for t in recent_trades}
trade_labels = list(trade_options.keys())

# Set initial selection based on query param if provided
initial_index = 0
if trade_id_param:
    try:
        target_id = int(trade_id_param)
        for idx, trade in enumerate(recent_trades):
            if trade["id"] == target_id:
                initial_index = idx
                break
    except (ValueError, TypeError):
        pass

selected_label = st.selectbox(
    "Select Trade",
    trade_labels,
    index=initial_index,
    key="trade_selector",
)

trade = trade_options[selected_label]

# ── Trade Summary Card ─────────────────────────────────────
st.markdown('<div class="section-header">Trade Summary</div>', unsafe_allow_html=True)

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("Ticker", trade["ticker"])
    st.metric("Action", trade["action"])

with col2:
    st.metric("Entry Price", f"${trade.get('entry_price') or 0:.2f}")
    exit_price = trade.get("exit_price")
    st.metric("Exit Price", f"${exit_price:.2f}" if exit_price else "—")

with col3:
    pnl = trade.get("pnl") or 0.0
    st.metric("P&L", f"${pnl:+.2f}", delta=f"{pnl:+.2f}")
    st.metric("Conviction", f"{trade.get('conviction') or 0:.2f}")

with col4:
    edges_fired = trade.get("edges_fired") or "N/A"
    st.metric("Edges Fired", edges_fired)
    st.metric("Status", trade["status"])

col5, col6, col7, col8 = st.columns(4)

with col5:
    st.metric("Portfolio", trade.get("portfolio") or "main")

with col6:
    st.metric("Sector", trade.get("sector") or "Unknown")

with col7:
    qty = trade.get("quantity") or 0
    st.metric("Quantity", f"{qty}")

with col8:
    exit_reason = trade.get("exit_reason") or "—"
    st.metric("Exit Reason", exit_reason)

# ── Reasoning ──────────────────────────────────────────────
st.markdown('<div class="section-header">Trade Reasoning</div>', unsafe_allow_html=True)

reasoning = trade.get("reasoning") or "No reasoning provided."
st.markdown(f'<div class="reasoning-box">{reasoning}</div>', unsafe_allow_html=True)

# ── Edge Details ───────────────────────────────────────────
st.markdown('<div class="section-header">Edge Analysis</div>', unsafe_allow_html=True)

edge_details = trade.get("edge_details")
if edge_details:
    try:
        edges = json.loads(edge_details) if isinstance(edge_details, str) else edge_details
        edge_rows = []
        for edge_name, edge_data in edges.items():
            status = "PASS" if edge_data.get("passed") else "FAIL"
            detail = edge_data.get("detail", "")
            edge_rows.append({
                "Edge": edge_name,
                "Status": status,
                "Detail": detail,
            })

        if edge_rows:
            df_edges = pd.DataFrame(edge_rows)

            # Color-code the Status column
            def color_status(val):
                color = "color: #4caf50;" if val == "PASS" else "color: #f44336;"
                return color

            styled_df = df_edges.style.applymap(color_status, subset=["Status"])
            st.dataframe(styled_df, use_container_width=True, hide_index=True)
        else:
            st.info("No edge details recorded.")
    except (json.JSONDecodeError, TypeError):
        st.warning("Edge details format invalid.")
else:
    st.info("No edge details recorded.")

# ── Price Timeline ─────────────────────────────────────────
st.markdown('<div class="section-header">Price Timeline</div>', unsafe_allow_html=True)

# Fetch 1-month chart from yfinance
ticker = trade["ticker"]
entry_ts = dt.fromisoformat(trade["timestamp"])
exit_ts = dt.fromisoformat(trade["exit_timestamp"]) if trade.get("exit_timestamp") else dt.now()

# Calculate date range: from 1 week before entry to 1 week after exit (or now)
start_date = entry_ts - timedelta(days=7)
end_date = exit_ts + timedelta(days=7) if trade["status"] == "CLOSED" else dt.now()

try:
    import yfinance as yf

    ticker_obj = yf.Ticker(ticker)
    hist = ticker_obj.history(start=start_date, end=end_date, interval="1d")

    if not hist.empty:
        fig = go.Figure()

        # Candlestick chart
        fig.add_trace(go.Candlestick(
            x=hist.index,
            open=hist["Open"],
            high=hist["High"],
            low=hist["Low"],
            close=hist["Close"],
            name=ticker,
            increasing_line_color=CHART_COLORS["positive"],
            decreasing_line_color=CHART_COLORS["negative"],
        ))

        # Entry point annotation
        entry_price = trade.get("entry_price") or 0
        fig.add_annotation(
            x=entry_ts,
            y=entry_price,
            text="ENTRY",
            showarrow=True,
            arrowhead=2,
            arrowcolor=CHART_COLORS["primary"],
            ax=0,
            ay=-40,
            font=dict(color=CHART_COLORS["primary"], size=12),
        )

        # Exit point annotation (if closed)
        if trade["status"] == "CLOSED" and trade.get("exit_price"):
            exit_price = trade["exit_price"]
            fig.add_annotation(
                x=exit_ts,
                y=exit_price,
                text="EXIT",
                showarrow=True,
                arrowhead=2,
                arrowcolor=CHART_COLORS["accent"],
                ax=0,
                ay=-40,
                font=dict(color=CHART_COLORS["accent"], size=12),
            )

        fig.update_layout(
            title=f"{ticker} Price Timeline",
            xaxis_title="Date",
            yaxis_title="Price ($)",
            height=500,
        )
        apply_chart_theme(fig)
        st.plotly_chart(fig, use_container_width=True)

        # Link to Yahoo Finance
        st.markdown(f"[View {ticker} on Yahoo Finance](https://finance.yahoo.com/quote/{ticker})")
    else:
        st.warning(f"No price data available for {ticker} in the selected date range.")

except ImportError:
    st.error("yfinance package not installed. Run `pip install yfinance` to enable price charts.")
except Exception as e:
    st.error(f"Error fetching price data: {e}")

# ── Trailing Stop History ──────────────────────────────────
st.markdown('<div class="section-header">Trailing Stop</div>', unsafe_allow_html=True)

trailing_active = trade.get("trailing_stop_active")
if trailing_active:
    col1, col2 = st.columns(2)
    with col1:
        trailing_price = trade.get("trailing_stop_price") or 0.0
        st.metric("Trailing Stop Price", f"${trailing_price:.2f}")
    with col2:
        highest_price = trade.get("highest_price") or 0.0
        st.metric("Highest Price Reached", f"${highest_price:.2f}")
else:
    st.info("Trailing stop not active for this trade.")

# ── Partial Exits ──────────────────────────────────────────
st.markdown('<div class="section-header">Partial Exits</div>', unsafe_allow_html=True)

# Query partial_exits table
with db._get_conn() as conn:
    partial_exits = conn.execute(
        "SELECT * FROM partial_exits WHERE trade_id = ? ORDER BY timestamp DESC",
        (trade["id"],)
    ).fetchall()

if partial_exits:
    exit_rows = []
    for exit in partial_exits:
        exit_rows.append({
            "Timestamp": dt.fromisoformat(exit["timestamp"]).strftime("%Y-%m-%d %H:%M"),
            "Quantity": exit["quantity"],
            "Exit Price": f"${exit['exit_price']:.2f}",
            "P&L": f"${exit['pnl'] or 0:.2f}",
            "Reason": exit.get("reason") or "—",
            "Order ID": exit.get("order_id") or "—",
        })

    df_exits = pd.DataFrame(exit_rows)
    st.dataframe(df_exits, use_container_width=True, hide_index=True)
else:
    st.info("No partial exits recorded for this trade.")

# ── Slippage ───────────────────────────────────────────────
st.markdown('<div class="section-header">Slippage Analysis</div>', unsafe_allow_html=True)

# Query slippage_records for this ticker around the trade timestamp
# Look within ±1 hour of entry and exit
entry_start = (entry_ts - timedelta(hours=1)).isoformat()
entry_end = (entry_ts + timedelta(hours=1)).isoformat()

with db._get_conn() as conn:
    slippage_entries = conn.execute(
        """SELECT * FROM slippage_records
           WHERE ticker = ? AND timestamp BETWEEN ? AND ?
           ORDER BY timestamp DESC""",
        (ticker, entry_start, entry_end)
    ).fetchall()

    if trade["status"] == "CLOSED" and trade.get("exit_timestamp"):
        exit_start = (exit_ts - timedelta(hours=1)).isoformat()
        exit_end = (exit_ts + timedelta(hours=1)).isoformat()
        slippage_exits = conn.execute(
            """SELECT * FROM slippage_records
               WHERE ticker = ? AND timestamp BETWEEN ? AND ?
               ORDER BY timestamp DESC""",
            (ticker, exit_start, exit_end)
        ).fetchall()
        all_slippage = list(slippage_entries) + list(slippage_exits)
    else:
        all_slippage = list(slippage_entries)

if all_slippage:
    slippage_rows = []
    for slip in all_slippage:
        slippage_rows.append({
            "Timestamp": dt.fromisoformat(slip["timestamp"]).strftime("%Y-%m-%d %H:%M"),
            "Order Type": slip["order_type"],
            "Side": slip["side"],
            "Expected": f"${slip['expected_price']:.2f}",
            "Actual": f"${slip['filled_price']:.2f}",
            "Slippage %": f"{slip['slippage_pct']:.3f}%",
            "Shares": slip.get("shares") or "—",
        })

    df_slippage = pd.DataFrame(slippage_rows)
    st.dataframe(df_slippage, use_container_width=True, hide_index=True)
else:
    st.info("No slippage records found for this ticker around the trade time.")

# ── Risk Metrics ───────────────────────────────────────────
st.markdown('<div class="section-header">Risk Metrics</div>', unsafe_allow_html=True)

col1, col2, col3, col4 = st.columns(4)

with col1:
    risk_amt = trade.get("risk_amount") or 0.0
    st.metric("Risk Amount", f"${risk_amt:.2f}")

with col2:
    # Calculate R-multiple if closed
    if trade["status"] == "CLOSED" and risk_amt > 0:
        pnl = trade.get("pnl") or 0.0
        r_multiple = pnl / risk_amt
        st.metric("R-Multiple", f"{r_multiple:.2f}R")
    else:
        st.metric("R-Multiple", "—")

with col3:
    # Position size as % of account (need account value — use a placeholder)
    # In production, fetch from portfolio or config
    account_value = 100000.0  # Placeholder
    entry_price = trade.get("entry_price") or 0
    quantity = trade.get("quantity") or 0
    position_value = entry_price * quantity
    position_pct = (position_value / account_value * 100) if account_value > 0 else 0
    st.metric("Position Size %", f"{position_pct:.2f}%")

with col4:
    original_qty = trade.get("original_quantity") or quantity
    st.metric("Original Quantity", f"{original_qty}")

st.success("Trade detail loaded successfully.")
