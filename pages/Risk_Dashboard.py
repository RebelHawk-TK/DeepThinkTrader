"""Risk monitoring dashboard for DeepThinkTrader."""

from __future__ import annotations

import os
import sys
from datetime import datetime as dt
from datetime import timedelta

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests as http_requests
import streamlit as st
import yfinance as yf

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config
from utils.database import Database

from utils.brand import ICON_PATH as _ICON
st.set_page_config(page_title="Risk Dashboard", page_icon=_ICON, layout="wide")

from utils.theme import CHART_COLORS, CHART_LAYOUT, apply_theme
from utils.streamlit_auth import require_auth
apply_theme()
require_auth()

db = Database()
config = Config()

ALPACA_HEADERS = {
    "APCA-API-KEY-ID": config.ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": config.ALPACA_SECRET_KEY,
}

# ── Data Fetchers ────────────────────────────────────────────

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
def get_spy_snapshot():
    try:
        resp = http_requests.get(
            "https://data.alpaca.markets/v2/stocks/SPY/snapshot",
            headers=ALPACA_HEADERS,
            timeout=5
        )
        return resp.json() if resp.ok else None
    except Exception:
        return None

@st.cache_data(ttl=60)
def get_vix():
    try:
        vix = yf.Ticker("^VIX")
        hist = vix.history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
        return None
    except Exception:
        return None

@st.cache_data(ttl=300)
def get_sector_etfs():
    """Fetch sector ETF performance for market breadth."""
    etfs = ["XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLRE"]
    results = []
    for ticker in etfs:
        try:
            t = yf.Ticker(ticker)
            hist = t.history(period="1d")
            if len(hist) >= 1:
                close = hist["Close"].iloc[-1]
                open_price = hist["Open"].iloc[-1]
                change_pct = ((close - open_price) / open_price) * 100
                results.append({
                    "ticker": ticker,
                    "change": change_pct,
                    "status": "advancing" if change_pct > 0 else "declining"
                })
        except Exception:
            pass
    return results

def get_ticker_sector(ticker: str) -> str:
    """Get sector for a ticker via yfinance."""
    try:
        info = yf.Ticker(ticker).info
        return info.get("sector", "Unknown")
    except Exception:
        return "Unknown"

# ── Calculate Metrics ────────────────────────────────────────

def calculate_drawdown() -> tuple[float, float]:
    """Calculate current drawdown vs peak and threshold."""
    account = get_alpaca_account()
    if not account:
        return 0.0, config.MAX_DRAWDOWN_HALT_PCT

    equity = float(account.get("equity", 0))

    # Get peak equity from DB
    peak_equity = db.get_peak_equity(days=30)

    # If no peak recorded yet, use current equity as baseline
    if peak_equity <= 0:
        peak_equity = equity

    # Update peak if current equity is higher
    if equity > peak_equity:
        peak_equity = equity

    # Calculate drawdown
    if peak_equity > 0:
        drawdown = (peak_equity - equity) / peak_equity
    else:
        drawdown = 0.0

    return drawdown, config.MAX_DRAWDOWN_HALT_PCT

def calculate_daily_loss() -> tuple[float, float]:
    """Calculate today's realized P&L as % of account vs limit."""
    account = get_alpaca_account()
    if not account:
        return 0.0, config.MAX_DAILY_LOSS

    today_data = db.get_today_pnl()
    realized_pnl = today_data.get("realized_pnl", 0)
    equity = float(account.get("equity", 50000))

    daily_loss_pct = realized_pnl / equity if equity > 0 else 0.0

    return daily_loss_pct, config.MAX_DAILY_LOSS

def get_spy_change() -> tuple[float, float]:
    """Get today's SPY change % and threshold."""
    spy_data = get_spy_snapshot()
    if not spy_data or "dailyBar" not in spy_data:
        return 0.0, config.CIRCUIT_BREAKER_SPY_DROP_PCT

    daily_bar = spy_data["dailyBar"]
    open_price = float(daily_bar.get("o", 0))
    close_price = float(daily_bar.get("c", 0))

    if open_price > 0:
        change_pct = ((close_price - open_price) / open_price) * 100
    else:
        change_pct = 0.0

    return change_pct, config.CIRCUIT_BREAKER_SPY_DROP_PCT

def calculate_sector_exposure():
    """Calculate market value per sector from open positions."""
    positions = get_alpaca_positions()
    account = get_alpaca_account()

    if not account:
        return {}

    total_equity = float(account.get("equity", 50000))

    sector_exposure = {}
    for pos in positions:
        ticker = pos.get("symbol", "")
        market_value = float(pos.get("market_value", 0))
        sector = get_ticker_sector(ticker)

        if sector not in sector_exposure:
            sector_exposure[sector] = 0.0
        sector_exposure[sector] += market_value

    # Convert to percentages
    sector_pct = {
        sector: (value / total_equity) if total_equity > 0 else 0.0
        for sector, value in sector_exposure.items()
    }

    return sector_pct

def count_consecutive_losses() -> tuple[int, list]:
    """Count consecutive losses from most recent trade backwards."""
    recent_trades = db.get_recent_trades(limit=500)

    # Filter only closed trades with P&L
    closed_trades = [
        t for t in recent_trades
        if t.get("status") == "CLOSED" and t.get("pnl") is not None
    ]

    if not closed_trades:
        return 0, []

    # Sort by timestamp descending (most recent first)
    closed_trades.sort(key=lambda t: t.get("timestamp", ""), reverse=True)

    consecutive_losses = 0
    last_10 = []

    for trade in closed_trades[:10]:
        pnl = trade.get("pnl", 0)
        won = pnl > 0
        last_10.append("win" if won else "loss")

        if consecutive_losses < len(closed_trades):
            if not won:
                consecutive_losses += 1
            else:
                break

    return consecutive_losses, last_10

# ── Header ───────────────────────────────────────────────────

st.title("Risk Dashboard")
st.markdown("Real-time risk monitoring and circuit breaker status")

# ── Section 1: Risk Gauges ───────────────────────────────────

st.markdown("### Risk Gauges")

col1, col2, col3, col4 = st.columns(4)

# Drawdown Gauge
with col1:
    drawdown, dd_limit = calculate_drawdown()
    dd_pct = drawdown * 100
    dd_limit_pct = dd_limit * 100
    dd_ratio = dd_pct / dd_limit_pct if dd_limit_pct > 0 else 0

    if dd_ratio < 0.5:
        dd_color = CHART_COLORS["positive"]
    elif dd_ratio < 0.8:
        dd_color = CHART_COLORS["accent"]
    else:
        dd_color = CHART_COLORS["negative"]

    fig_dd = go.Figure(go.Indicator(
        mode="gauge+number",
        value=dd_pct,
        title={"text": "Drawdown", "font": {"size": 14}},
        number={"suffix": "%", "font": {"size": 24}},
        gauge={
            "axis": {"range": [0, dd_limit_pct]},
            "bar": {"color": dd_color},
            "bgcolor": CHART_COLORS["bg"],
            "borderwidth": 2,
            "bordercolor": CHART_COLORS["grid"],
            "steps": [
                {"range": [0, dd_limit_pct * 0.5], "color": "#0a2e1a"},
                {"range": [dd_limit_pct * 0.5, dd_limit_pct * 0.8], "color": "#2e2a1a"},
                {"range": [dd_limit_pct * 0.8, dd_limit_pct], "color": "#2e1a1a"}
            ],
            "threshold": {
                "line": {"color": CHART_COLORS["negative"], "width": 4},
                "thickness": 0.75,
                "value": dd_limit_pct
            }
        }
    ))
    fig_dd.update_layout(**CHART_LAYOUT, height=250)
    st.plotly_chart(fig_dd, use_container_width=True)
    st.caption(f"Limit: {dd_limit_pct:.1f}%")

# Daily Loss Gauge
with col2:
    daily_loss, daily_limit = calculate_daily_loss()
    daily_loss_pct = daily_loss * 100
    daily_limit_pct = daily_limit * 100
    daily_ratio = abs(daily_loss_pct) / daily_limit_pct if daily_limit_pct > 0 else 0

    if daily_ratio < 0.5:
        daily_color = CHART_COLORS["positive"]
    elif daily_ratio < 0.8:
        daily_color = CHART_COLORS["accent"]
    else:
        daily_color = CHART_COLORS["negative"]

    fig_daily = go.Figure(go.Indicator(
        mode="gauge+number",
        value=abs(daily_loss_pct),
        title={"text": "Daily Loss", "font": {"size": 14}},
        number={"suffix": "%", "font": {"size": 24}},
        gauge={
            "axis": {"range": [0, daily_limit_pct]},
            "bar": {"color": daily_color},
            "bgcolor": CHART_COLORS["bg"],
            "borderwidth": 2,
            "bordercolor": CHART_COLORS["grid"],
            "steps": [
                {"range": [0, daily_limit_pct * 0.5], "color": "#0a2e1a"},
                {"range": [daily_limit_pct * 0.5, daily_limit_pct * 0.8], "color": "#2e2a1a"},
                {"range": [daily_limit_pct * 0.8, daily_limit_pct], "color": "#2e1a1a"}
            ],
            "threshold": {
                "line": {"color": CHART_COLORS["negative"], "width": 4},
                "thickness": 0.75,
                "value": daily_limit_pct
            }
        }
    ))
    fig_daily.update_layout(**CHART_LAYOUT, height=250)
    st.plotly_chart(fig_daily, use_container_width=True)
    st.caption(f"Limit: {daily_limit_pct:.1f}%")

# VIX Level Gauge
with col3:
    vix = get_vix()
    vix_threshold = config.CIRCUIT_BREAKER_VIX_THRESHOLD

    if vix is not None:
        if vix < 20:
            vix_color = CHART_COLORS["positive"]
        elif vix < 30:
            vix_color = CHART_COLORS["accent"]
        else:
            vix_color = CHART_COLORS["negative"]

        fig_vix = go.Figure(go.Indicator(
            mode="gauge+number",
            value=vix,
            title={"text": "VIX Level", "font": {"size": 14}},
            number={"font": {"size": 24}},
            gauge={
                "axis": {"range": [0, 50]},
                "bar": {"color": vix_color},
                "bgcolor": CHART_COLORS["bg"],
                "borderwidth": 2,
                "bordercolor": CHART_COLORS["grid"],
                "steps": [
                    {"range": [0, 20], "color": "#0a2e1a"},
                    {"range": [20, 30], "color": "#2e2a1a"},
                    {"range": [30, 50], "color": "#2e1a1a"}
                ],
                "threshold": {
                    "line": {"color": CHART_COLORS["negative"], "width": 4},
                    "thickness": 0.75,
                    "value": vix_threshold
                }
            }
        ))
        fig_vix.update_layout(**CHART_LAYOUT, height=250)
        st.plotly_chart(fig_vix, use_container_width=True)
        st.caption(f"Threshold: {vix_threshold:.1f}")
    else:
        st.warning("VIX data unavailable")

# SPY Change Gauge
with col4:
    spy_change, spy_threshold = get_spy_change()

    if spy_change > 0:
        spy_color = CHART_COLORS["positive"]
    elif spy_change > -1:
        spy_color = CHART_COLORS["accent"]
    else:
        spy_color = CHART_COLORS["negative"]

    # Gauge range: -5% to +5%
    fig_spy = go.Figure(go.Indicator(
        mode="gauge+number+delta",
        value=spy_change,
        title={"text": "SPY Change", "font": {"size": 14}},
        number={"suffix": "%", "font": {"size": 24}},
        delta={"reference": 0},
        gauge={
            "axis": {"range": [-5, 5]},
            "bar": {"color": spy_color},
            "bgcolor": CHART_COLORS["bg"],
            "borderwidth": 2,
            "bordercolor": CHART_COLORS["grid"],
            "steps": [
                {"range": [-5, -2], "color": "#2e1a1a"},
                {"range": [-2, 0], "color": "#2e2a1a"},
                {"range": [0, 5], "color": "#0a2e1a"}
            ],
            "threshold": {
                "line": {"color": CHART_COLORS["negative"], "width": 4},
                "thickness": 0.75,
                "value": spy_threshold
            }
        }
    ))
    fig_spy.update_layout(**CHART_LAYOUT, height=250)
    st.plotly_chart(fig_spy, use_container_width=True)
    st.caption(f"Threshold: {spy_threshold:.1f}%")

# ── Section 2: Sector Exposure ───────────────────────────────

st.markdown("---")
st.markdown("### Sector Exposure")

sector_pct = calculate_sector_exposure()
if sector_pct:
    sectors = list(sector_pct.keys())
    exposures = [v * 100 for v in sector_pct.values()]

    # Color bars red if they exceed the cap
    cap = config.MAX_SECTOR_EXPOSURE_PCT * 100
    colors = [CHART_COLORS["negative"] if e > cap else CHART_COLORS["primary"] for e in exposures]

    fig_sector = go.Figure(go.Bar(
        y=sectors,
        x=exposures,
        orientation='h',
        marker_color=colors,
        text=[f"{e:.1f}%" for e in exposures],
        textposition='outside'
    ))

    # Add vertical line at cap
    fig_sector.add_vline(
        x=cap,
        line_dash="dash",
        line_color=CHART_COLORS["negative"],
        line_width=2,
        annotation_text=f"{cap:.0f}% cap",
        annotation_position="top"
    )

    fig_sector.update_layout(
        **CHART_LAYOUT,
        height=max(300, len(sectors) * 40),
        xaxis_title="Portfolio %",
        yaxis_title="",
        showlegend=False
    )

    st.plotly_chart(fig_sector, use_container_width=True)
else:
    st.info("No open positions")

# ── Section 3: Consecutive Loss Tracker ─────────────────────

st.markdown("---")
st.markdown("### Consecutive Loss Tracker")

col1, col2 = st.columns([1, 2])

consecutive_losses, last_10 = count_consecutive_losses()
revenge_threshold = 3

with col1:
    if consecutive_losses == 0:
        streak_color = CHART_COLORS["positive"]
        status = "Clear"
    elif consecutive_losses < revenge_threshold:
        streak_color = CHART_COLORS["accent"]
        status = "Caution"
    else:
        streak_color = CHART_COLORS["negative"]
        status = "REVENGE RISK"

    st.metric("Current Streak", f"{consecutive_losses} losses", delta=None)
    st.markdown(f"**Status:** <span style='color:{streak_color};font-weight:bold'>{status}</span>", unsafe_allow_html=True)
    st.caption(f"Revenge trading threshold: {revenge_threshold}")

with col2:
    if last_10:
        st.markdown("**Last 10 Trades:**")
        dots = []
        for outcome in last_10:
            if outcome == "win":
                dots.append("🟢")
            else:
                dots.append("🔴")
        st.markdown(" ".join(dots))
    else:
        st.info("No closed trades yet")

# ── Section 4: Position Risk Table ──────────────────────────

st.markdown("---")
st.markdown("### Position Risk Table")

positions = get_alpaca_positions()
open_trades = db.get_open_trades()

if positions and open_trades:
    # Match positions with trade records
    position_risks = []

    for pos in positions:
        ticker = pos.get("symbol", "")
        current_price = float(pos.get("current_price", 0))
        qty = int(pos.get("qty", 0))
        market_value = float(pos.get("market_value", 0))
        unrealized_pl = float(pos.get("unrealized_pl", 0))
        unrealized_plpc = float(pos.get("unrealized_plpc", 0)) * 100

        # Find matching trade
        trade = next((t for t in open_trades if t.get("ticker") == ticker), None)

        if trade:
            entry_price = trade.get("entry_price", 0)
            stop_loss = trade.get("stop_loss_price", 0)
            trailing_stop = trade.get("trailing_stop_price", 0)
            trailing_active = trade.get("trailing_stop_active", 0)
            risk_amount = trade.get("risk_amount", 0)

            # Calculate distance to stop
            if trailing_active and trailing_stop:
                effective_stop = trailing_stop
                stop_label = "Trailing"
            elif stop_loss:
                effective_stop = stop_loss
                stop_label = "Fixed"
            else:
                effective_stop = None
                stop_label = "None"

            if effective_stop and current_price > 0:
                distance_pct = ((current_price - effective_stop) / current_price) * 100
            else:
                distance_pct = None

            # Calculate R-multiple
            if entry_price and effective_stop and entry_price > effective_stop:
                risk_per_share = entry_price - effective_stop
                gain_per_share = current_price - entry_price
                r_multiple = gain_per_share / risk_per_share if risk_per_share > 0 else 0
            else:
                r_multiple = None

            # Days held
            timestamp = trade.get("timestamp", "")
            try:
                entry_dt = dt.fromisoformat(timestamp)
                days_held = (dt.now() - entry_dt).days
            except Exception:
                days_held = None

            position_risks.append({
                "Ticker": ticker,
                "Entry": f"${entry_price:.2f}" if entry_price else "—",
                "Current": f"${current_price:.2f}",
                "P&L": f"${unrealized_pl:.2f}",
                "P&L %": f"{unrealized_plpc:.1f}%",
                "Stop": f"${effective_stop:.2f}" if effective_stop else "—",
                "Stop Type": stop_label,
                "Distance": f"{distance_pct:.1f}%" if distance_pct else "—",
                "Risk $": f"${risk_amount:.2f}" if risk_amount else "—",
                "R": f"{r_multiple:.2f}R" if r_multiple is not None else "—",
                "Days": days_held if days_held is not None else "—"
            })

    if position_risks:
        df = pd.DataFrame(position_risks)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No position risk data available")
else:
    st.info("No open positions")

# ── Section 5: Circuit Breaker Status ───────────────────────

st.markdown("---")
st.markdown("### Circuit Breaker Status")

col1, col2 = st.columns(2)

with col1:
    spy_change, spy_threshold = get_spy_change()

    st.markdown("**SPY Intraday Change**")

    fig_spy_line = go.Figure()
    fig_spy_line.add_trace(go.Scatter(
        x=["SPY"],
        y=[spy_change],
        mode="markers+text",
        marker=dict(
            size=20,
            color=CHART_COLORS["positive"] if spy_change > 0 else CHART_COLORS["negative"]
        ),
        text=[f"{spy_change:.2f}%"],
        textposition="top center",
        showlegend=False
    ))

    # Threshold line
    fig_spy_line.add_hline(
        y=spy_threshold,
        line_dash="dash",
        line_color=CHART_COLORS["negative"],
        annotation_text=f"Threshold: {spy_threshold:.1f}%",
        annotation_position="right"
    )

    fig_spy_line.update_layout(
        **CHART_LAYOUT,
        height=200,
        yaxis_title="Change %",
        xaxis_visible=False
    )

    st.plotly_chart(fig_spy_line, use_container_width=True)

with col2:
    vix = get_vix()
    vix_threshold = config.CIRCUIT_BREAKER_VIX_THRESHOLD

    st.markdown("**VIX Level**")

    if vix is not None:
        fig_vix_line = go.Figure()
        fig_vix_line.add_trace(go.Scatter(
            x=["VIX"],
            y=[vix],
            mode="markers+text",
            marker=dict(
                size=20,
                color=CHART_COLORS["positive"] if vix < 20 else (
                    CHART_COLORS["accent"] if vix < 30 else CHART_COLORS["negative"]
                )
            ),
            text=[f"{vix:.2f}"],
            textposition="top center",
            showlegend=False
        ))

        # Threshold line
        fig_vix_line.add_hline(
            y=vix_threshold,
            line_dash="dash",
            line_color=CHART_COLORS["negative"],
            annotation_text=f"Threshold: {vix_threshold:.1f}",
            annotation_position="right"
        )

        fig_vix_line.update_layout(
            **CHART_LAYOUT,
            height=200,
            yaxis_title="VIX",
            xaxis_visible=False
        )

        st.plotly_chart(fig_vix_line, use_container_width=True)
    else:
        st.warning("VIX data unavailable")

# Circuit breaker status summary
st.markdown("**Status**")

breaker_active = (spy_change < spy_threshold) or (vix is not None and vix > vix_threshold)

if breaker_active:
    st.error("CIRCUIT BREAKER ACTIVE — No new long entries allowed")
    reasons = []
    if spy_change < spy_threshold:
        reasons.append(f"SPY down {spy_change:.2f}% (threshold: {spy_threshold:.1f}%)")
    if vix is not None and vix > vix_threshold:
        reasons.append(f"VIX at {vix:.1f} (threshold: {vix_threshold:.1f})")
    for reason in reasons:
        st.markdown(f"- {reason}")
else:
    st.success("CLEAR — Normal trading allowed")

# Market breadth
st.markdown("---")
st.markdown("**Market Breadth (Sector ETFs)**")

sector_etfs = get_sector_etfs()
if sector_etfs:
    advancing = [s for s in sector_etfs if s["status"] == "advancing"]
    declining = [s for s in sector_etfs if s["status"] == "declining"]

    col1, col2, col3 = st.columns(3)
    col1.metric("Advancing", len(advancing))
    col2.metric("Declining", len(declining))
    col3.metric("Breadth Ratio", f"{len(advancing)}/{len(sector_etfs)}")

    breadth_df = pd.DataFrame(sector_etfs)
    st.dataframe(
        breadth_df[["ticker", "change", "status"]].style.applymap(
            lambda v: "color: green" if v == "advancing" else "color: red",
            subset=["status"]
        ),
        use_container_width=True,
        hide_index=True
    )
else:
    st.info("Sector ETF data unavailable")
