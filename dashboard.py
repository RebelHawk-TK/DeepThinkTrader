"""Streamlit dashboard for monitoring DeepThinkTrader."""

from __future__ import annotations

import json
import math
import os
from datetime import datetime as dt

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests as http_requests
import streamlit as st

from config import Config
from utils.database import Database

st.set_page_config(page_title="DeepThinkTrader", page_icon="📈", layout="wide")
st.title("DeepThinkTrader Dashboard")

YAHOO_URL = "https://finance.yahoo.com/quote"

db = Database()
config = Config()

# ──────────────────────────────────────────────
# Data fetchers
# ──────────────────────────────────────────────

ALPACA_HEADERS = {
    "APCA-API-KEY-ID": config.ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
}

@st.cache_data(ttl=30)
def get_alpaca_account():
    try:
        resp = http_requests.get(
            f"{config.ALPACA_BASE_URL}/v2/account", headers=ALPACA_HEADERS, timeout=5
        )
        return resp.json() if resp.ok else None
    except Exception:
        return None

@st.cache_data(ttl=30)
def get_alpaca_positions():
    try:
        resp = http_requests.get(
            f"{config.ALPACA_BASE_URL}/v2/positions", headers=ALPACA_HEADERS, timeout=5
        )
        return resp.json() if resp.ok else []
    except Exception:
        return []

@st.cache_data(ttl=60)
def get_portfolio_history():
    try:
        resp = http_requests.get(
            f"{config.ALPACA_BASE_URL}/v2/account/portfolio/history",
            headers=ALPACA_HEADERS,
            params={"period": "1A", "timeframe": "1D", "intraday_reporting": "market_hours", "pnl_reset": "per_day"},
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            if data.get("equity"):
                ts = data["timestamp"]
                eq = data["equity"]
                pnl = data.get("profit_loss", [0] * len(eq))
                fts, feq, fpnl = [], [], []
                for i, e in enumerate(eq):
                    if e and e > 0:
                        fts.append(ts[i])
                        feq.append(e)
                        fpnl.append(pnl[i] if i < len(pnl) else 0)
                data["timestamp"] = fts
                data["equity"] = feq
                data["profit_loss"] = fpnl
            return data
    except Exception:
        pass
    return None

@st.cache_data(ttl=60)
def get_spy_history():
    """Fetch SPY history for benchmark comparison."""
    try:
        resp = http_requests.get(
            "https://data.alpaca.markets/v2/stocks/SPY/bars",
            headers=ALPACA_HEADERS,
            params={"timeframe": "1Day", "limit": 60, "adjustment": "raw", "feed": "iex"},
            timeout=10,
        )
        if resp.ok:
            return resp.json().get("bars", [])
    except Exception:
        pass
    return []


account = get_alpaca_account()
positions = get_alpaca_positions()
portfolio_hist = get_portfolio_history()

# ──────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────

st.sidebar.header("Controls")

# Auto-refresh with adjustable interval (persisted via query params)
auto_refresh = st.sidebar.toggle("Auto Refresh", value=True)

# Read interval from URL query param so it survives page reloads
_qp = st.query_params
_saved_interval = int(_qp.get("ri", "300"))
_interval_options = [10, 15, 30, 60, 120, 300]
if _saved_interval not in _interval_options:
    _saved_interval = 30

refresh_interval = st.sidebar.select_slider(
    "Refresh interval",
    options=_interval_options,
    value=_saved_interval,
    format_func=lambda x: f"{x}s" if x < 60 else f"{x//60}m",
)

# Persist to query param when changed
if refresh_interval != _saved_interval:
    st.query_params["ri"] = str(refresh_interval)

if st.sidebar.button("Refresh Now"):
    st.cache_data.clear()
    st.rerun()

if auto_refresh:
    st.cache_data.clear()
    import streamlit.components.v1 as components
    components.html(
        f"""<script>
            setTimeout(function(){{
                var url = new URL(window.parent.location);
                url.searchParams.set('ri', '{refresh_interval}');
                window.parent.location.href = url.toString();
            }}, {refresh_interval * 1000});
        </script>""",
        height=0,
    )

st.sidebar.markdown("---")

# === TRADE MODE SWITCHER ===
st.sidebar.subheader("Trade Mode")

_mode_labels = {"safe": "🛡️ Safe", "normal": "⚖️ Normal", "aggressive": "🔥 Aggressive"}
_current_mode = config.TRADE_MODE
_mode_index = list(_mode_labels.keys()).index(_current_mode) if _current_mode in _mode_labels else 1

_selected_mode = st.sidebar.radio(
    "Select mode",
    options=list(_mode_labels.keys()),
    format_func=lambda m: _mode_labels[m],
    index=_mode_index,
    horizontal=True,
    label_visibility="collapsed",
)

if _selected_mode != _current_mode:
    if st.sidebar.button(f"Switch to {_mode_labels[_selected_mode]}", type="primary"):
        import subprocess, re as _re

        _env_path = os.path.join(os.path.dirname(__file__), ".env")
        _env_content = open(_env_path).read()
        _env_content = _re.sub(
            r"^TRADE_MODE=.*$",
            f"TRADE_MODE={_selected_mode}",
            _env_content,
            flags=_re.MULTILINE,
        )
        with open(_env_path, "w") as f:
            f.write(_env_content)

        # Restart bot
        _project_dir = os.path.dirname(__file__)
        subprocess.Popen(
            ["bash", "-c", f"cd {_project_dir} && bash stop.sh && bash run.sh"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        st.sidebar.success(f"Switching to {_mode_labels[_selected_mode]}... restarting bot")
        import time as _t
        _t.sleep(3)
        st.cache_data.clear()
        st.rerun()
else:
    _mode_desc = {
        "safe": "Low risk, high conviction only",
        "normal": "Balanced risk/reward",
        "aggressive": "Higher risk, more trades",
    }
    st.sidebar.caption(_mode_desc.get(_current_mode, ""))

st.sidebar.markdown("---")

# === PORTFOLIO FILTER ===
st.sidebar.subheader("Portfolio")
_portfolio_filter = st.sidebar.radio(
    "View portfolio",
    options=["all", "main", "penny"],
    format_func=lambda p: {"all": "📊 All", "main": "📈 Main", "penny": "🪙 Penny ($1-$5)"}[p],
    index=0,
    horizontal=True,
    label_visibility="collapsed",
)

st.sidebar.markdown("---")

# === BOT HEALTH (Tier 1 #3) ===
st.sidebar.subheader("Bot Health")

log_path = os.path.join(os.path.dirname(__file__), "deepthinktrader.log")
bot_pid_path = os.path.join(os.path.dirname(__file__), ".trader.pid")
dash_pid_path = os.path.join(os.path.dirname(__file__), ".dashboard.pid")

# Bot running check
bot_running = False
if os.path.exists(bot_pid_path):
    try:
        pid = int(open(bot_pid_path).read().strip())
        os.kill(pid, 0)  # Check if process exists
        bot_running = True
    except (ProcessError, ValueError, OSError):
        pass

st.sidebar.markdown(f"**Bot:** {'🟢 Running' if bot_running else '🔴 Stopped'}")

# Last activity from log
last_activity = "Unknown"
error_count_24h = 0
if os.path.exists(log_path):
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            read_size = min(size, 50000)
            f.seek(max(0, size - read_size))
            lines = f.read().decode("utf-8", errors="ignore").splitlines()
            if lines:
                last_activity = lines[-1][:19] if lines[-1] else "Unknown"
                # Count errors in last 24h
                for line in lines:
                    if "[ERROR]" in line:
                        error_count_24h += 1
    except Exception:
        pass

st.sidebar.markdown(f"**Last Activity:** {last_activity}")
st.sidebar.markdown(f"**Errors (recent):** {'🔴 ' + str(error_count_24h) if error_count_24h > 5 else str(error_count_24h)}")

if account:
    st.sidebar.markdown("---")
    st.sidebar.markdown(f"**Account:** {account.get('account_number', 'N/A')}")
    st.sidebar.markdown(f"**Mode:** {'📄 Paper' if account.get('account_number', '').startswith('PA') else '💰 Live'}")

# ──────────────────────────────────────────────
# Compute metrics
# ──────────────────────────────────────────────

equity = float(account["equity"]) if account else 0
cash = float(account["cash"]) if account else 0
starting_balance = 100_000.0
total_pnl = equity - starting_balance

_pf = _portfolio_filter if _portfolio_filter != "all" else None
all_trades = db.get_recent_trades(500, portfolio=_pf)
total_trades = len(all_trades)
open_trades_db = db.get_open_trades(portfolio=_pf)
closed_trades = [t for t in all_trades if t.get("status") == "CLOSED"]
winning_trades = [t for t in closed_trades if (t.get("pnl") or 0) > 0]
losing_trades = [t for t in closed_trades if (t.get("pnl") or 0) < 0]
win_rate = (len(winning_trades) / len(closed_trades) * 100) if closed_trades else 0

# Realized P&L
realized_pnl = sum(t.get("pnl", 0) or 0 for t in closed_trades)
unrealized_pnl = sum(float(p.get("unrealized_pl", 0)) for p in positions)

# Risk metrics
closed_pnls = [t.get("pnl", 0) or 0 for t in closed_trades]
avg_win = np.mean([p for p in closed_pnls if p > 0]) if winning_trades else 0
avg_loss = abs(np.mean([p for p in closed_pnls if p < 0])) if losing_trades else 0
profit_factor = (sum(p for p in closed_pnls if p > 0) / abs(sum(p for p in closed_pnls if p < 0))) if losing_trades else 0

# Drawdown calculation from equity curve
max_drawdown_pct = 0
max_drawdown_dollars = 0
peak_equity = starting_balance
if portfolio_hist and portfolio_hist.get("equity"):
    eq_series = [e for e in portfolio_hist["equity"] if e and e > 0]
    if equity > 0:
        eq_series.append(equity)
    peak = eq_series[0] if eq_series else starting_balance
    for e in eq_series:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100
        dd_dollars = peak - e
        if dd > max_drawdown_pct:
            max_drawdown_pct = dd
            max_drawdown_dollars = dd_dollars

# Sharpe & Sortino (annualized, using daily returns)
sharpe_ratio = 0
sortino_ratio = 0
if portfolio_hist and portfolio_hist.get("equity"):
    eq_arr = np.array([e for e in portfolio_hist["equity"] if e and e > 0])
    if equity > 0:
        eq_arr = np.append(eq_arr, equity)
    if len(eq_arr) > 2:
        daily_returns = np.diff(eq_arr) / eq_arr[:-1]
        mean_ret = np.mean(daily_returns)
        std_ret = np.std(daily_returns)
        if std_ret > 0:
            sharpe_ratio = round((mean_ret / std_ret) * np.sqrt(252), 2)
        downside = daily_returns[daily_returns < 0]
        downside_std = np.std(downside) if len(downside) > 0 else 0
        if downside_std > 0:
            sortino_ratio = round((mean_ret / downside_std) * np.sqrt(252), 2)

# ──────────────────────────────────────────────
# TOP METRICS ROW 1 — Portfolio
# ──────────────────────────────────────────────

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric(
        "Portfolio Value",
        f"${equity:,.2f}",
        delta=f"${total_pnl:+,.2f}",
        delta_color="normal" if total_pnl >= 0 else "inverse",
    )
with col2:
    st.metric("Realized P&L", f"${realized_pnl:+,.2f}",
              delta_color="normal" if realized_pnl >= 0 else "inverse")
with col3:
    st.metric("Unrealized P&L", f"${unrealized_pnl:+,.2f}",
              delta_color="normal" if unrealized_pnl >= 0 else "inverse")
with col4:
    st.metric("Cash", f"${cash:,.2f}")
with col5:
    st.metric("Total Trades", total_trades)

# TOP METRICS ROW 2 — Risk (Tier 1 #2)
rcol1, rcol2, rcol3, rcol4, rcol5 = st.columns(5)

with rcol1:
    st.metric("Win Rate", f"{win_rate:.0f}%" if closed_trades else "N/A")
with rcol2:
    st.metric("Max Drawdown", f"-{max_drawdown_pct:.1f}%",
              delta=f"-${max_drawdown_dollars:,.0f}" if max_drawdown_dollars > 0 else "$0",
              delta_color="normal" if max_drawdown_dollars > 0 else "off")
with rcol3:
    color = "normal" if sharpe_ratio > 0 else "inverse"
    st.metric("Sharpe Ratio", f"{sharpe_ratio:.2f}")
with rcol4:
    st.metric("Sortino Ratio", f"{sortino_ratio:.2f}")
with rcol5:
    st.metric("Profit Factor", f"{profit_factor:.2f}" if profit_factor > 0 else "N/A")

# TOP METRICS ROW 3 — Rolling Performance (Tier 2 #10)
if closed_trades:
    def rolling_stats(trades, days):
        cutoff = dt.now().isoformat()[:10]
        try:
            from datetime import timedelta
            cutoff_dt = dt.now() - timedelta(days=days)
            cutoff_str = cutoff_dt.isoformat()
        except Exception:
            return None, None
        recent = [t for t in trades if (t.get("timestamp") or "") >= cutoff_str]
        if not recent:
            return 0, 0
        wins = sum(1 for t in recent if (t.get("pnl") or 0) > 0)
        wr = (wins / len(recent) * 100) if recent else 0
        pnl = sum(t.get("pnl", 0) or 0 for t in recent)
        return round(wr), round(pnl, 2)

    wr7, pnl7 = rolling_stats(closed_trades, 7)
    wr30, pnl30 = rolling_stats(closed_trades, 30)
    wr90, pnl90 = rolling_stats(closed_trades, 90)

    pcol1, pcol2, pcol3, pcol4, pcol5, pcol6 = st.columns(6)
    with pcol1:
        st.metric("7d Win Rate", f"{wr7}%" if wr7 is not None else "N/A")
    with pcol2:
        st.metric("7d P&L", f"${pnl7:+,.2f}" if pnl7 is not None else "N/A")
    with pcol3:
        st.metric("30d Win Rate", f"{wr30}%" if wr30 is not None else "N/A")
    with pcol4:
        st.metric("30d P&L", f"${pnl30:+,.2f}" if pnl30 is not None else "N/A")
    with pcol5:
        st.metric("90d Win Rate", f"{wr90}%" if wr90 is not None else "N/A")
    with pcol6:
        st.metric("90d P&L", f"${pnl90:+,.2f}" if pnl90 is not None else "N/A")

st.divider()

# ──────────────────────────────────────────────
# PORTFOLIO VALUE + SPY BENCHMARK (Tier 1 #1, #5)
# ──────────────────────────────────────────────

st.subheader("Portfolio Value vs SPY Benchmark")
if portfolio_hist and portfolio_hist.get("equity"):
    timestamps = portfolio_hist["timestamp"]
    equities = portfolio_hist["equity"]

    if timestamps and equities:
        df_port = pd.DataFrame({
            "date": pd.to_datetime(timestamps, unit="s"),
            "equity": equities,
        })

        # Append live equity
        if df_port.iloc[-1]["equity"] != equity:
            df_port = pd.concat([df_port, pd.DataFrame({
                "date": [pd.Timestamp(dt.now())], "equity": [equity],
            })], ignore_index=True)

        # Normalize to % return for comparison
        port_start = df_port["equity"].iloc[0]
        df_port["port_return_pct"] = ((df_port["equity"] - port_start) / port_start) * 100

        fig_port = go.Figure()

        # Portfolio equity (left axis)
        line_color = "#4CAF50" if equity >= starting_balance else "#F44336"
        fig_port.add_trace(go.Scatter(
            x=df_port["date"], y=df_port["equity"],
            mode="lines+markers", name="Portfolio ($)",
            line=dict(color=line_color, width=3),
            fill="tozeroy",
            fillcolor="rgba(76,175,80,0.1)" if equity >= starting_balance else "rgba(244,67,54,0.08)",
        ))

        # SPY benchmark overlay (normalized to portfolio start value)
        spy_bars = get_spy_history()
        if spy_bars:
            spy_df = pd.DataFrame(spy_bars)
            spy_df["date"] = pd.to_datetime(spy_df["t"])
            spy_start = spy_df["c"].iloc[0]
            spy_df["spy_normalized"] = (spy_df["c"] / spy_start) * port_start
            fig_port.add_trace(go.Scatter(
                x=spy_df["date"], y=spy_df["spy_normalized"],
                mode="lines", name="SPY (normalized)",
                line=dict(color="#FF9800", width=2, dash="dot"),
                opacity=0.7,
            ))

        fig_port.add_hline(y=starting_balance, line_dash="dash", line_color="gray",
                           annotation_text=f"Start (${starting_balance:,.0f})")

        # Drawdown shading
        peak = df_port["equity"].iloc[0]
        dd_dates, dd_vals = [], []
        for _, row in df_port.iterrows():
            if row["equity"] > peak:
                peak = row["equity"]
            dd_dates.append(row["date"])
            dd_vals.append(row["equity"] - peak)  # negative values

        min_eq = min(df_port["equity"])
        max_eq = max(df_port["equity"])
        padding = max((max_eq - min_eq) * 0.3, 500)
        fig_port.update_layout(
            yaxis_title="Portfolio Value ($)",
            yaxis_range=[min_eq - padding, max_eq + padding],
            height=420, margin=dict(l=0, r=0, t=30, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_port, use_container_width=True)

        # Drawdown chart (Tier 1 #1)
        if any(d < 0 for d in dd_vals):
            fig_dd = go.Figure()
            dd_pct = [(d / (df_port["equity"].iloc[i] - d) * 100) if (df_port["equity"].iloc[i] - d) > 0 else 0
                      for i, d in enumerate(dd_vals)]
            fig_dd.add_trace(go.Scatter(
                x=dd_dates, y=dd_pct,
                fill="tozeroy", fillcolor="rgba(244,67,54,0.2)",
                line=dict(color="#F44336", width=2),
                name="Drawdown %",
            ))
            fig_dd.update_layout(
                title="Drawdown from Peak",
                yaxis_title="Drawdown (%)", height=200,
                margin=dict(l=0, r=0, t=40, b=0),
            )
            st.plotly_chart(fig_dd, use_container_width=True)
else:
    st.info("Portfolio history will populate after first trading day")

st.divider()

# ──────────────────────────────────────────────
# DAILY P&L BAR CHART (Tier 1 #4)
# ──────────────────────────────────────────────

st.subheader("Daily P&L")
if portfolio_hist and portfolio_hist.get("profit_loss"):
    ts = portfolio_hist["timestamp"]
    pnls = portfolio_hist["profit_loss"]
    eq = portfolio_hist["equity"]

    # Compute daily P&L from equity differences
    dates = pd.to_datetime([t for t, e in zip(ts, eq) if e and e > 0], unit="s")
    eq_clean = [e for e in eq if e and e > 0]

    if len(eq_clean) > 1:
        daily_pnl = [eq_clean[i] - eq_clean[i-1] for i in range(1, len(eq_clean))]
        daily_dates = dates[1:]

        colors = ["#4CAF50" if p >= 0 else "#F44336" for p in daily_pnl]
        fig_daily = go.Figure(go.Bar(
            x=daily_dates, y=daily_pnl,
            marker_color=colors,
        ))
        fig_daily.add_hline(y=0, line_color="gray", line_width=1)
        fig_daily.update_layout(
            yaxis_title="Daily P&L ($)", height=250,
            margin=dict(l=0, r=0, t=10, b=0),
        )
        st.plotly_chart(fig_daily, use_container_width=True)

        # Summary stats
        dcol1, dcol2, dcol3, dcol4 = st.columns(4)
        with dcol1:
            best = max(daily_pnl)
            st.metric("Best Day", f"${best:+,.2f}")
        with dcol2:
            worst = min(daily_pnl)
            st.metric("Worst Day", f"${worst:+,.2f}")
        with dcol3:
            avg_daily = np.mean(daily_pnl)
            st.metric("Avg Day", f"${avg_daily:+,.2f}")
        with dcol4:
            win_days = sum(1 for p in daily_pnl if p > 0)
            st.metric("Win Days", f"{win_days}/{len(daily_pnl)}")
    else:
        st.info("Need 2+ trading days for daily P&L chart")
else:
    st.info("Daily P&L will populate after first trading day")

st.divider()

# ──────────────────────────────────────────────
# LIVE POSITIONS
# ──────────────────────────────────────────────

st.subheader("Current Positions (Live)")
if positions:
    pos_data = []
    total_unrealized_pos = 0
    total_market_value = 0
    sector_exposure = {}

    for p in positions:
        unrealized = float(p.get("unrealized_pl", 0))
        unrealized_pct = float(p.get("unrealized_plpc", 0)) * 100
        market_val = float(p.get("market_value", 0))
        total_unrealized_pos += unrealized
        total_market_value += market_val
        pos_data.append({
            "Ticker": p["symbol"],
            "Details": f"{YAHOO_URL}/{p['symbol']}",
            "Qty": int(p["qty"]),
            "Avg Entry": float(p["avg_entry_price"]),
            "Current": float(p["current_price"]),
            "Market Value": market_val,
            "P&L": unrealized,
            "P&L %": unrealized_pct,
        })

    # Add cash (uninvested) as a line item
    pos_data.append({
        "Ticker": "💵 CASH",
        "Details": "",
        "Qty": 0,
        "Avg Entry": 0,
        "Current": 0,
        "Market Value": cash,
        "P&L": 0,
        "P&L %": 0,
    })

    df_pos = pd.DataFrame(pos_data)

    def _color_pnl(val):
        if isinstance(val, (int, float)):
            color = "#4CAF50" if val >= 0 else "#F44336"
            return f"color: {color}; font-weight: bold"
        return ""

    def _fmt_or_dash(val, fmt):
        """Format value or show dash for zero (used for cash row)."""
        if val == 0:
            return "—"
        return fmt.format(val)

    styled_pos = df_pos.style.map(
        _color_pnl, subset=["P&L", "P&L %"]
    ).format({
        "Qty": lambda v: _fmt_or_dash(v, "{:,}"),
        "Avg Entry": lambda v: _fmt_or_dash(v, "${:,.2f}"),
        "Current": lambda v: _fmt_or_dash(v, "${:,.2f}"),
        "Market Value": "${:,.2f}",
        "P&L": lambda v: _fmt_or_dash(v, "${:+,.2f}"),
        "P&L %": lambda v: _fmt_or_dash(v, "{:+.2f}%"),
    })

    st.dataframe(
        styled_pos,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Details": st.column_config.LinkColumn("Yahoo Finance", display_text="View"),
        },
    )

    # Position summary + allocation pie chart
    pcol1, pcol2 = st.columns([1, 1])
    with pcol1:
        mcol1, mcol2, mcol3 = st.columns(3)
        with mcol1:
            st.metric("Total Invested", f"${total_market_value:,.2f}")
        with mcol2:
            st.metric("Unrealized P&L", f"${total_unrealized_pos:+,.2f}")
        with mcol3:
            invested_pct = (total_market_value / equity * 100) if equity > 0 else 0
            st.metric("% Invested", f"{invested_pct:.1f}%")

        # P&L bar chart (exclude CASH row)
        if len(positions) > 1:
            pnl_df = pd.DataFrame([{
                "ticker": p["symbol"],
                "pnl": float(p.get("unrealized_pl", 0)),
            } for p in positions])
            colors = ["#4CAF50" if x >= 0 else "#F44336" for x in pnl_df["pnl"]]
            fig_pnl = go.Figure(go.Bar(x=pnl_df["ticker"], y=pnl_df["pnl"], marker_color=colors))
            fig_pnl.update_layout(title="P&L by Position", yaxis_title="P&L ($)", height=250,
                                  margin=dict(l=0, r=0, t=40, b=0))
            st.plotly_chart(fig_pnl, use_container_width=True)

    with pcol2:
        # Allocation pie chart + sector breakdown (Tier 2 #9)
        alloc_df = pd.DataFrame([{
            "Ticker": p["symbol"],
            "Value": abs(float(p.get("market_value", 0))),
        } for p in positions])
        if cash > 0:
            alloc_df = pd.concat([alloc_df, pd.DataFrame([{"Ticker": "CASH", "Value": cash}])], ignore_index=True)

        fig_pie = px.pie(alloc_df, values="Value", names="Ticker", title="Portfolio Allocation",
                         hole=0.4, color_discrete_sequence=px.colors.qualitative.Set2)
        fig_pie.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0))
        st.plotly_chart(fig_pie, use_container_width=True)

        # Sector exposure (Tier 2 #9)
        @st.cache_data(ttl=3600)
        def get_sectors(tickers):
            import yfinance as yf
            sectors = {}
            for t in tickers:
                try:
                    info = yf.Ticker(t).info
                    sectors[t] = info.get("sector", "Unknown")
                except Exception:
                    sectors[t] = "Unknown"
            return sectors

        pos_tickers = [p["symbol"] for p in positions]
        if pos_tickers:
            sectors = get_sectors(tuple(pos_tickers))
            sector_values = {}
            for p in positions:
                s = sectors.get(p["symbol"], "Unknown")
                val = abs(float(p.get("market_value", 0)))
                sector_values[s] = sector_values.get(s, 0) + val

            if sector_values:
                sector_df = pd.DataFrame([
                    {"Sector": s, "Value": v} for s, v in sector_values.items()
                ])
                fig_sector = px.pie(sector_df, values="Value", names="Sector",
                                    title="Sector Exposure",
                                    hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
                fig_sector.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0))
                st.plotly_chart(fig_sector, use_container_width=True)
else:
    st.info("No open positions")

st.divider()

# ──────────────────────────────────────────────
# TRADE HISTORY (Tier 2 #8: Filtering + Export)
# ──────────────────────────────────────────────

st.subheader("Trade History")
if all_trades:
    df_trades_raw = pd.DataFrame(all_trades)

    # Filters (Tier 2 #8)
    fcol1, fcol2, fcol3 = st.columns(3)
    with fcol1:
        ticker_filter = st.multiselect(
            "Filter by Ticker",
            options=sorted(df_trades_raw["ticker"].unique()),
            default=[],
            key="trade_ticker_filter",
        )
    with fcol2:
        status_filter = st.multiselect(
            "Filter by Status",
            options=["OPEN", "CLOSED"],
            default=[],
            key="trade_status_filter",
        )
    with fcol3:
        pnl_filter = st.selectbox(
            "Filter by P&L",
            options=["All", "Winners Only", "Losers Only"],
            key="trade_pnl_filter",
        )

    df_trades = df_trades_raw.copy()
    if ticker_filter:
        df_trades = df_trades[df_trades["ticker"].isin(ticker_filter)]
    if status_filter:
        df_trades = df_trades[df_trades["status"].isin(status_filter)]
    if pnl_filter == "Winners Only":
        df_trades = df_trades[(df_trades["pnl"].fillna(0)) > 0]
    elif pnl_filter == "Losers Only":
        df_trades = df_trades[(df_trades["pnl"].fillna(0)) < 0]

    # Calculate hold duration (Tier 2 #7)
    if "timestamp" in df_trades.columns and "exit_timestamp" in df_trades.columns:
        def calc_hold_time(row):
            try:
                entry = pd.to_datetime(row["timestamp"])
                exit_t = row.get("exit_timestamp")
                if exit_t and pd.notna(exit_t):
                    exit_dt = pd.to_datetime(exit_t)
                    delta = exit_dt - entry
                    hours = delta.total_seconds() / 3600
                    if hours < 1:
                        return f"{delta.total_seconds()/60:.0f}m"
                    elif hours < 24:
                        return f"{hours:.1f}h"
                    else:
                        return f"{delta.days}d"
                return "Open"
            except Exception:
                return "—"
        df_trades["hold_time"] = df_trades.apply(calc_hold_time, axis=1)

    # Calculate invested amount before formatting
    if "quantity" in df_trades.columns and "entry_price" in df_trades.columns:
        df_trades["invested"] = df_trades.apply(
            lambda r: f"${r['quantity'] * r['entry_price']:,.2f}"
            if r["quantity"] and r["entry_price"] and r["entry_price"] > 0 else "—",
            axis=1,
        )

    # Format prices
    for col in ["entry_price", "exit_price", "stop_loss_price", "take_profit_price"]:
        if col in df_trades.columns:
            df_trades[col] = df_trades[col].apply(lambda x: f"${x:,.2f}" if x and x > 0 else "—")
    if "pnl" in df_trades.columns:
        df_trades["pnl"] = df_trades["pnl"].apply(lambda x: f"${x:+,.2f}" if x else "—")

    df_trades["details"] = df_trades["ticker"].apply(lambda t: f"{YAHOO_URL}/{t}")

    display_cols = [
        "ticker", "details", "action", "quantity", "entry_price", "invested", "stop_loss_price",
        "take_profit_price", "exit_price", "conviction", "pnl", "hold_time", "status", "timestamp",
    ]
    available_cols = [c for c in display_cols if c in df_trades.columns]
    st.dataframe(
        df_trades[available_cols],
        use_container_width=True,
        column_config={
            "details": st.column_config.LinkColumn("Yahoo Finance", display_text="View"),
        },
    )

    # CSV Export (Tier 2 #8)
    csv_data = df_trades[available_cols].to_csv(index=False)
    st.download_button("Export to CSV", csv_data, "trade_history.csv", "text/csv")

    # Win/Loss stats + Hold time analysis (Tier 2 #7)
    if closed_trades:
        scol1, scol2, scol3, scol4, scol5, scol6 = st.columns(6)
        with scol1:
            st.metric("Avg Win", f"${avg_win:,.2f}" if avg_win > 0 else "N/A")
        with scol2:
            st.metric("Avg Loss", f"-${avg_loss:,.2f}" if avg_loss > 0 else "N/A")
        with scol3:
            ratio = f"{avg_win / avg_loss:.2f}" if avg_loss > 0 else "N/A"
            st.metric("Win/Loss Ratio", ratio)
        with scol4:
            # Win/loss streak (Tier 2 #10)
            streak = 0
            streak_type = ""
            longest_win = 0
            longest_loss = 0
            cur_streak = 0
            cur_type = ""
            for t in closed_trades:
                p = t.get("pnl", 0) or 0
                tp = "W" if p > 0 else "L"
                if tp == cur_type:
                    cur_streak += 1
                else:
                    cur_type = tp
                    cur_streak = 1
                if cur_type == "W" and cur_streak > longest_win:
                    longest_win = cur_streak
                elif cur_type == "L" and cur_streak > longest_loss:
                    longest_loss = cur_streak
            # Current streak
            streak = cur_streak
            streak_display = f"{streak} {'Wins' if cur_type == 'W' else 'Losses'}"
            st.metric("Current Streak", streak_display)
        with scol5:
            st.metric("Best Streak", f"{longest_win} Wins")
        with scol6:
            st.metric("Worst Streak", f"{longest_loss} Losses")

        # Avg hold time for winners vs losers (Tier 2 #7)
        if "exit_timestamp" in df_trades_raw.columns:
            def get_hold_hours(row):
                try:
                    entry = pd.to_datetime(row["timestamp"])
                    exit_t = row.get("exit_timestamp")
                    if exit_t and pd.notna(exit_t):
                        return (pd.to_datetime(exit_t) - entry).total_seconds() / 3600
                except Exception:
                    pass
                return None

            df_closed = pd.DataFrame(closed_trades)
            df_closed["hold_hours"] = df_closed.apply(get_hold_hours, axis=1)
            winners_hold = df_closed[df_closed["pnl"] > 0]["hold_hours"].dropna()
            losers_hold = df_closed[df_closed["pnl"] < 0]["hold_hours"].dropna()

            hcol1, hcol2, hcol3 = st.columns(3)
            with hcol1:
                avg_w = winners_hold.mean() if len(winners_hold) > 0 else 0
                st.metric("Avg Hold (Winners)", f"{avg_w:.1f}h" if avg_w > 0 else "N/A")
            with hcol2:
                avg_l = losers_hold.mean() if len(losers_hold) > 0 else 0
                st.metric("Avg Hold (Losers)", f"{avg_l:.1f}h" if avg_l > 0 else "N/A")
            with hcol3:
                if avg_w > 0 and avg_l > 0:
                    if avg_l < avg_w:
                        st.metric("Diagnosis", "Cutting losses fast")
                    else:
                        st.metric("Diagnosis", "Holding losers too long")
                else:
                    st.metric("Diagnosis", "N/A")

    # Cumulative P&L chart
    closed_df_raw = pd.DataFrame(closed_trades)
    if not closed_df_raw.empty and "pnl" in closed_df_raw.columns:
        closed_df_raw = closed_df_raw.sort_values("timestamp")
        closed_df_raw["cumulative_pnl"] = closed_df_raw["pnl"].cumsum()
        fig_cum = px.line(closed_df_raw, x="timestamp", y="cumulative_pnl",
                          title="Cumulative Realized P&L")
        fig_cum.update_layout(yaxis_title="P&L ($)")
        st.plotly_chart(fig_cum, use_container_width=True)
else:
    st.info("No trades yet")

st.divider()

# ──────────────────────────────────────────────
# RECENT ANALYSES
# ──────────────────────────────────────────────

st.subheader("Recent Analyses")
analyses = db.get_recent_analyses(100, portfolio=_pf)
if analyses:
    df_analysis = pd.DataFrame(analyses)

    # Extract fields from stored JSON
    extra_cols = {"price": [], "technical_score": [], "fundamental_score": [],
                  "catalyst_score": [], "pattern_score": [], "earnings_risk": []}
    for a in analyses:
        try:
            data = json.loads(a.get("analysis_json", "{}"))
            extra_cols["price"].append(data.get("current_price"))
            extra_cols["technical_score"].append(data.get("technical_score"))
            extra_cols["fundamental_score"].append(data.get("fundamental_score"))
            extra_cols["catalyst_score"].append(data.get("catalyst_score"))
            extra_cols["pattern_score"].append(data.get("pattern_score"))
            extra_cols["earnings_risk"].append(data.get("earnings_risk"))
        except Exception:
            for k in extra_cols:
                extra_cols[k].append(None)

    df_analysis["price"] = [f"${x:,.2f}" if x else "N/A" for x in extra_cols["price"]]
    df_analysis["tech"] = extra_cols["technical_score"]
    df_analysis["fund"] = extra_cols["fundamental_score"]
    df_analysis["cata"] = extra_cols["catalyst_score"]
    df_analysis["patt"] = extra_cols["pattern_score"]
    df_analysis["earn_risk"] = extra_cols["earnings_risk"]

    df_analysis["details"] = df_analysis["ticker"].apply(lambda t: f"{YAHOO_URL}/{t}")

    display_cols = ["ticker", "details", "price", "action", "conviction", "tech", "fund", "cata", "patt",
                    "earn_risk", "stop_loss_pct", "take_profit_pct", "timestamp"]
    available_cols = [c for c in display_cols if c in df_analysis.columns]
    st.dataframe(
        df_analysis[available_cols],
        use_container_width=True,
        column_config={
            "details": st.column_config.LinkColumn("Yahoo Finance", display_text="View"),
        },
    )

    # Analysis-to-trade conversion rate
    total_analyses = len(analyses)
    buy_count = sum(1 for a in analyses if a.get("action") == "BUY")
    sell_count = sum(1 for a in analyses if a.get("action") == "SELL")
    hold_count = total_analyses - buy_count - sell_count
    conversion = ((buy_count + sell_count) / total_analyses * 100) if total_analyses > 0 else 0

    acol1, acol2, acol3, acol4 = st.columns(4)
    with acol1:
        st.metric("Analyzed", total_analyses)
    with acol2:
        st.metric("BUY Signals", buy_count)
    with acol3:
        st.metric("SELL Signals", sell_count)
    with acol4:
        st.metric("Selectivity", f"{conversion:.1f}% traded")

    # Conviction distribution
    fig2 = px.histogram(df_analysis, x="conviction", nbins=10,
                        title="Conviction Score Distribution",
                        color_discrete_sequence=["#2196F3"])
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("No analyses yet")

st.divider()

# ──────────────────────────────────────────────
# BOT CONFIG (read-only)
# ──────────────────────────────────────────────

with st.expander("Bot Configuration"):
    mode = config.TRADE_MODE.upper()
    mode_emoji = {"SAFE": "🛡️", "NORMAL": "⚖️", "AGGRESSIVE": "🔥"}.get(mode, "⚙️")
    st.markdown(f"### {mode_emoji} Trade Mode: **{mode}**")
    st.markdown("*Change in `.env` → `TRADE_MODE=safe|normal|aggressive` → restart bot*")
    st.markdown("")

    cfgcol1, cfgcol2, cfgcol3, cfgcol4 = st.columns(4)
    with cfgcol1:
        st.markdown(f"**Max Risk/Trade:** {config.MAX_RISK_PER_TRADE*100}%")
        st.markdown(f"**Max Daily Loss:** {config.MAX_DAILY_LOSS*100}%")
    with cfgcol2:
        st.markdown(f"**Min Conviction:** {config.MIN_CONVICTION}/10")
        st.markdown(f"**Min R:R Ratio:** {config.MIN_REWARD_RISK_RATIO}:1")
    with cfgcol3:
        st.markdown(f"**Max Position Size:** {config.MAX_POSITION_PCT*100:.0f}% of account")
        st.markdown(f"**Max Open Positions:** {config.MAX_OPEN_POSITIONS}")
    with cfgcol4:
        st.markdown(f"**Scanner Depth:** Top {config.SCANNER_TOP_N} candidates")
        st.markdown(f"**Cycle Interval:** {config.RESEARCH_INTERVAL_MINUTES} min")

# API Request IDs
with st.expander("Alpaca API Request IDs (debugging)"):
    request_ids = db.get_recent_request_ids(30)
    if request_ids:
        df_reqs = pd.DataFrame(request_ids)
        display_cols = ["timestamp", "request_id", "endpoint", "method", "ticker", "order_id", "http_status", "success"]
        available_cols = [c for c in display_cols if c in df_reqs.columns]
        st.dataframe(df_reqs[available_cols], use_container_width=True)
    else:
        st.info("No API calls logged yet")

# ──────────────────────────────────────────────
# STRATEGY HEALTH (Phase 5c)
# ──────────────────────────────────────────────

st.subheader("Strategy Health")

def _show_strategy_health(portfolio_name: str):
    stats = db.get_strategy_stats(portfolio_name, days=30)
    baseline = db.get_strategy_stats(portfolio_name, days=90)
    if stats["trade_count"] < 5:
        st.info(f"Not enough closed trades for {portfolio_name} portfolio health (need 5+, have {stats['trade_count']})")
        return

    hcol1, hcol2, hcol3, hcol4, hcol5 = st.columns(5)
    with hcol1:
        wr = stats["win_rate"] * 100
        st.metric(f"{portfolio_name.title()} Win Rate (30d)", f"{wr:.0f}%")
    with hcol2:
        st.metric("Expectancy", f"${stats['expectancy']:+,.2f}")
    with hcol3:
        pf = stats.get("profit_factor", 0)
        st.metric("Profit Factor", f"{pf:.2f}" if pf > 0 else "N/A")
    with hcol4:
        st.metric("Payoff Ratio", f"{stats['payoff_ratio']:.2f}" if stats["payoff_ratio"] > 0 else "N/A")
    with hcol5:
        if baseline["trade_count"] >= 20:
            delta = (stats["win_rate"] - baseline["win_rate"]) * 100
            color = "normal" if delta >= 0 else "inverse"
            st.metric("WR vs 90d Baseline", f"{delta:+.0f}%")
        else:
            st.metric("WR vs 90d Baseline", "N/A")

_show_strategy_health("main")
if config.PENNY_ENABLED:
    _show_strategy_health("penny")

st.divider()

# Footer
st.divider()
st.caption("DeepThinkTrader v2.0 — Paper Trading Mode | Risk-First Framework | Dashboard auto-refreshes on Streamlit file change")
