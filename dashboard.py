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
from utils.streamlit_auth import require_auth

# Read identity from the X-Auth-Email header set by the auth proxy sidecar
# (Mac dev bypass returns a synthetic admin). Admin-only features gate on
# CURRENT_USER["role"] == "admin".
CURRENT_USER = require_auth()

from utils.dashboard_data import (
    compute_30day_pnl,
    compute_alerts,
    compute_bot_status,
    compute_drawdown_from_peak,
    compute_kelly_state,
    compute_market_state,
    compute_portfolio_cvar,
    compute_recent_reflections,
    compute_regime,
    compute_today_pnl,
    compute_top_correlation,
    compute_total_exposure_pct,
)
from utils.dashboard_widgets import (
    render_kpi_row,
    render_risk_memory,
    render_status_banner,
)

from utils.brand import ICON_PATH, BANNER_PATH
from utils.theme import apply_theme, BRAND

st.set_page_config(page_title="DeepThinkTrader", page_icon=ICON_PATH, layout="wide")
# Banner: full-width black band, image centered inside at 50% width so the
# wordmark+tiles stay legible but the black background of the image
# continues edge-to-edge of the viewport.
import base64 as _b64
with open(BANNER_PATH, "rb") as _bf:
    _banner_b64 = _b64.b64encode(_bf.read()).decode()
st.markdown(
    f"""
    <div style="
        width: 100vw;
        position: relative;
        left: 50%;
        right: 50%;
        margin-left: -50vw;
        margin-right: -50vw;
        background: #000;
        display: flex;
        justify-content: center;
        align-items: center;
        padding: 0;
    ">
        <img src="data:image/png;base64,{_banner_b64}"
             style="width: 50%; display: block;" />
    </div>
    """,
    unsafe_allow_html=True,
)
apply_theme()

# ── User bar (right-aligned) ───────────────────────────────
_SIGNOUT_URL = "https://trader.travelforge.ai/?gcp-iap-mode=CLEAR_LOGIN_COOKIE"
st.markdown(
    f"""<div style='display:flex;justify-content:flex-end;align-items:center;
                     gap:14px;padding:6px 4px 2px;margin-bottom:8px;
                     font-size:0.85rem;'>
        <span style='color:{BRAND["dim"]};'>Signed in as
            <span style='color:{BRAND["text"]};font-weight:600;'>{CURRENT_USER["email"]}</span>
        </span>
        <a href='{_SIGNOUT_URL}' target='_self'
           style='background:{BRAND["bg_raised"]};border:1px solid {BRAND["stroke"]};
                  color:{BRAND["green"]};padding:6px 14px;border-radius:6px;
                  text-decoration:none;font-weight:600;'>Sign out</a>
    </div>""",
    unsafe_allow_html=True,
)

# ── Market Ticker Bar ──────────────────────────────────────
@st.cache_data(ttl=60)
def _fetch_ticker_bar_data():
    """Fetch quotes for the scrolling market ticker bar."""
    import yfinance as yf
    symbols = {
        "^DJI": "DOW",
        "^GSPC": "S&P 500",
        "^IXIC": "NASDAQ",
        "SI=F": "SILVER",
        "GC=F": "GOLD",
        "BTC-USD": "BTC",
    }
    items = []
    for sym, label in symbols.items():
        try:
            t = yf.Ticker(sym)
            hist = t.history(period="5d")
            if len(hist) >= 2:
                price = hist["Close"].iloc[-1]
                prev = hist["Close"].iloc[-2]
                change = ((price - prev) / prev) * 100
            elif len(hist) == 1:
                price = hist["Close"].iloc[-1]
                change = 0.0
            else:
                continue
            if price > 10000:
                fmt = f"{price:,.0f}"
            elif price > 100:
                fmt = f"{price:,.2f}"
            else:
                fmt = f"{price:.2f}"
            color = BRAND["green"] if change >= 0 else BRAND["red"]
            arrow = "▲" if change >= 0 else "▼"
            items.append(
                f'<span style="color:{BRAND["text"]};font-weight:600">{label}</span>&nbsp;'
                f'<span style="color:{color}">${fmt} {arrow} {abs(change):.2f}%</span>'
            )
        except Exception:
            pass
    return items

_ticker_items = _fetch_ticker_bar_data()
if _ticker_items:
    _sep = '&nbsp;&nbsp;&nbsp;·&nbsp;&nbsp;&nbsp;'
    # Duplicate items so the scroll loops seamlessly
    _content = _sep.join(_ticker_items)
    _scroll = _content + _sep + _content
    st.markdown(f"""
    <style>
    .ticker-wrap {{
        width: 100%;
        overflow: hidden;
        background: {BRAND["bg_raised"]};
        border: 1px solid {BRAND["stroke"]};
        border-radius: 6px;
        padding: 8px 0;
        margin-bottom: 12px;
    }}
    .ticker-move {{
        display: inline-block;
        white-space: nowrap;
        animation: ticker-scroll 30s linear infinite;
        font-size: 14px;
        font-family: 'SF Mono', 'Fira Code', monospace;
    }}
    @keyframes ticker-scroll {{
        0%   {{ transform: translateX(0); }}
        100% {{ transform: translateX(-50%); }}
    }}
    </style>
    <div class="ticker-wrap">
        <div class="ticker-move">{_scroll}</div>
    </div>
    """, unsafe_allow_html=True)


# Compact branded header — single line, no JS clock bar (status banner below
# already shows market state with countdown). Cuts ~80px of vertical chrome
# from above-the-fold per UX cleanup pass.
st.markdown(
    "<div style='display:flex;align-items:baseline;gap:10px;margin-bottom:6px;'>"
    "<span style='font-size:1.3rem;font-weight:700;color:#ccd6f6;letter-spacing:-0.3px;'>"
    "📈 DeepThinkTrader</span>"
    "<span style='font-size:0.8rem;color:#7D8590;'>· Trade with conviction, not emotion.</span>"
    "</div>",
    unsafe_allow_html=True,
)

YAHOO_URL = "https://finance.yahoo.com/quote"

from utils.theme import CHART_COLORS, CHART_LAYOUT

def apply_chart_theme(fig):
    """Apply consistent dark theme to any Plotly figure."""
    fig.update_layout(**CHART_LAYOUT)
    return fig

db = Database()
config = Config()

# ──────────────────────────────────────────────
# Per-user identity + Alpaca credentials
# ──────────────────────────────────────────────
from utils import secrets_vault
from utils.secrets_vault import user_id_for_email

USER_ID = user_id_for_email(CURRENT_USER["email"])
if USER_ID is None:
    st.error("Your user record is missing. Ask Tom to re-add you.")
    st.stop()


def _user_alpaca_headers(user_id: int) -> dict | None:
    """Return request headers for this user's Alpaca account, or None when
    the user hasn't added keys yet. Callers that depend on Alpaca data should
    show an empty state when this returns None.
    """
    keys = secrets_vault.get_alpaca_keys(user_id)
    if not keys:
        return None
    return {"APCA-API-KEY-ID": keys[0], "APCA-API-SECRET-KEY": keys[1]}


# Module-level shorthand for the signed-in user's Alpaca headers. A handful of
# legacy callers (`get_spy_history`, `_get_portfolio_history_period`) reference
# `ALPACA_HEADERS` directly; without this they raise NameError, get caught by
# `except Exception:` swallowers, and the benchmarks chart falls back to
# "Portfolio history or benchmark data unavailable" forever.
ALPACA_HEADERS = _user_alpaca_headers(USER_ID) or {}


# ──────────────────────────────────────────────
# Data fetchers (user_id in cache key = per-user cache)
# ──────────────────────────────────────────────

@st.cache_data(ttl=30)
def get_alpaca_account(user_id: int):
    headers = _user_alpaca_headers(user_id)
    if headers is None:
        return None
    try:
        resp = http_requests.get(
            f"{config.ALPACA_BASE_URL}/v2/account", headers=headers, timeout=5
        )
        return resp.json() if resp.ok else None
    except Exception:
        return None

@st.cache_data(ttl=30)
def get_alpaca_positions(user_id: int):
    headers = _user_alpaca_headers(user_id)
    if headers is None:
        return []
    try:
        resp = http_requests.get(
            f"{config.ALPACA_BASE_URL}/v2/positions", headers=headers, timeout=5
        )
        return resp.json() if resp.ok else []
    except Exception:
        return []

@st.cache_data(ttl=60)
def get_portfolio_history(user_id: int):
    headers = _user_alpaca_headers(user_id)
    if headers is None:
        return {}
    try:
        resp = http_requests.get(
            f"{config.ALPACA_BASE_URL}/v2/account/portfolio/history",
            headers=headers,
            params={"period": "1A", "timeframe": "1D", "intraday_reporting": "market_hours", "pnl_reset": "per_day"},
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            if data.get("equity"):
                ts = data["timestamp"]
                eq = data["equity"]
                pnl = data.get("profit_loss", [0] * len(eq))
                # Filter to baseline date — ignore all history before reset
                baseline = config.BASELINE_DATE
                if baseline:
                    from datetime import datetime as _dt
                    baseline_ts = int(_dt.strptime(baseline, "%Y-%m-%d").timestamp())
                else:
                    baseline_ts = 0
                fts, feq, fpnl = [], [], []
                prev_eq = None
                for i, e in enumerate(eq):
                    if e and e > 0 and ts[i] >= baseline_ts:
                        # Skip settlement artifacts: equity drops >20% in one bar
                        # then recovers (cash-only snapshots between sell/buy cycles).
                        # Tightened from 0.6 -> 0.8 after seeing a -17% phantom dip
                        # on a day with -$51 realized P&L (rapid DGXX cycling).
                        if prev_eq and e < prev_eq * 0.8:
                            continue
                        fts.append(ts[i])
                        feq.append(e)
                        fpnl.append(pnl[i] if i < len(pnl) else 0)
                        prev_eq = e
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


account = get_alpaca_account(USER_ID)
positions = get_alpaca_positions(USER_ID)
portfolio_hist = get_portfolio_history(USER_ID)

# ──────────────────────────────────────────────
# Sidebar
# ──────────────────────────────────────────────

st.sidebar.header("Controls")

# Theme toggle
_theme = st.sidebar.toggle("Light Theme", value=False)
if _theme:
    st.markdown("""<style>
    [data-testid="stAppViewContainer"] { background-color: #f5f5f5; }
    [data-testid="stSidebar"] { background: #e8e8e8 !important; }
    .kpi-card { background: linear-gradient(135deg, #f0f0f5 0%, #e8eaf6 100%); border-color: #c5cae9; }
    .kpi-card-green { background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%); border-color: #a5d6a7; }
    .kpi-card-red { background: linear-gradient(135deg, #fce4ec 0%, #f8bbd0 100%); border-color: #ef9a9a; }
    .kpi-card-amber { background: linear-gradient(135deg, #fff8e1 0%, #ffecb3 100%); border-color: #ffe082; }
    .section-header { color: #37474f !important; border-bottom-color: #cfd8dc !important; }
    h1, h2, h3 { color: #263238 !important; }
    [data-testid="stMetricLabel"] { color: #546e7a !important; }
    .ticker-wrap { background: #e8eaf6 !important; }
    </style>""", unsafe_allow_html=True)

# Compact mode for mobile
_compact = st.sidebar.toggle("Compact Mode", value=True)
if _compact:
    st.markdown("""<style>
    @media (max-width: 768px) {
        [data-testid="stHorizontalBlock"] { flex-direction: column !important; }
        [data-testid="stColumn"] { width: 100% !important; flex: 1 1 100% !important; }
        .kpi-card, .kpi-card-green, .kpi-card-red, .kpi-card-amber { padding: 12px 10px 10px; }
        [data-testid="stMetricValue"] { font-size: 1.2rem !important; }
    }
    .kpi-card, .kpi-card-green, .kpi-card-red, .kpi-card-amber { padding: 12px 10px 10px; margin-bottom: 6px; }
    [data-testid="stMetricValue"] { font-size: 1rem !important; }
    [data-testid="stMetricLabel"] { font-size: 0.6rem !important; }
    .section-header { font-size: 0.9rem; margin: 16px 0 8px; }
    </style>""", unsafe_allow_html=True)

# Auto-refresh with adjustable interval (persisted via session state)
auto_refresh = st.sidebar.toggle("Auto Refresh", value=True)

_interval_options = [10, 15, 30, 60, 120, 300]

# Use session_state to persist interval across reruns
if "refresh_interval" not in st.session_state:
    # First load: try query param, then default to 300 (5m)
    _qp_val = int(st.query_params.get("ri", "300"))
    st.session_state["refresh_interval"] = _qp_val if _qp_val in _interval_options else 300

refresh_interval = st.sidebar.select_slider(
    "Refresh interval",
    options=_interval_options,
    value=st.session_state["refresh_interval"],
    format_func=lambda x: f"{x}s" if x < 60 else f"{x//60}m",
    key="ri_slider",
)

# Persist when changed
if refresh_interval != st.session_state["refresh_interval"]:
    st.session_state["refresh_interval"] = refresh_interval
    st.query_params["ri"] = str(refresh_interval)

if st.sidebar.button("Refresh Now"):
    st.cache_data.clear()
    st.rerun()

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
    # Two-step confirm — a misclick here kills the bot with positions open.
    _pending_key = "pending_mode_switch"
    _pending = st.session_state.get(_pending_key)

    # Check if market is open with open positions — block switch entirely.
    _open_count = 0
    try:
        _open_count = len(db.get_open_trades(USER_ID))
    except Exception:
        pass
    _market_open = False
    try:
        from utils.market_clock import get_market_clock
        _keys = secrets_vault.get_alpaca_keys(USER_ID)
        if _keys:
            _market_open = get_market_clock(_keys[0], _keys[1]).is_market_open()
    except Exception:
        pass
    _blocked = _market_open and _open_count > 0

    if _blocked:
        st.sidebar.error(
            f"🚫 Can't switch modes during market hours with {_open_count} open "
            f"position(s). Close positions or wait for market close."
        )
    elif _pending != _selected_mode:
        if st.sidebar.button(
            f"Switch to {_mode_labels[_selected_mode]}", type="primary", key="mode_switch_1"
        ):
            st.session_state[_pending_key] = _selected_mode
            st.rerun()
    else:
        st.sidebar.warning(
            f"⚠️ Confirm: switching to **{_mode_labels[_selected_mode]}** will "
            f"**restart the bot**. Any running analysis will be interrupted."
        )
        _c1, _c2 = st.sidebar.columns(2)
        if _c1.button("✅ Confirm", type="primary", key="mode_switch_confirm"):
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

            _project_dir = os.path.dirname(__file__)
            subprocess.Popen(
                ["bash", "-c", f"cd {_project_dir} && bash stop.sh && bash run.sh"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

            st.session_state.pop(_pending_key, None)
            st.sidebar.success(f"Switching to {_mode_labels[_selected_mode]}... restarting bot")
            import time as _t
            _t.sleep(3)
            st.cache_data.clear()
            st.rerun()
        if _c2.button("Cancel", key="mode_switch_cancel"):
            st.session_state.pop(_pending_key, None)
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

# Bot running check — consult run.sh's PID file first, then launchctl.
# Matches status.sh's two-source strategy so the sidebar doesn't lie after
# launchd takes over.
bot_running = False
pid = None
if os.path.exists(bot_pid_path):
    try:
        pid = int(open(bot_pid_path).read().strip())
        os.kill(pid, 0)
        bot_running = True
    except (ProcessLookupError, ValueError, OSError):
        pid = None
if not bot_running:
    try:
        import subprocess as _sp
        out = _sp.check_output(["launchctl", "list"], text=True, timeout=2)
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2] == "com.deepthinktrader.bot" and parts[0] != "-":
                pid = int(parts[0])
                bot_running = True
                break
    except Exception:
        pass

# Cloud Run fallback: no PID file or launchd in a container. Query Cloud
# Logging for a recent heartbeat from trader-bot; a log entry in the last
# 5 minutes means the Cloud Run revision is alive.
_cloud_last_activity = None
if not bot_running:
    try:
        from google.cloud import logging as _gcl
        _client = _gcl.Client()
        _filter = (
            'resource.type="cloud_run_revision" '
            'AND resource.labels.service_name="trader-bot"'
        )
        _entries = list(_client.list_entries(
            filter_=_filter, order_by=_gcl.DESCENDING, page_size=1, max_results=1,
        ))
        if _entries:
            _ts = _entries[0].timestamp
            _age = (dt.now(_ts.tzinfo) - _ts).total_seconds()
            if _age < 300:
                bot_running = True
                _cloud_last_activity = _ts.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

if bot_running:
    # Compute uptime from process start time
    try:
        import subprocess as _sp
        _ps_out = _sp.check_output(["ps", "-o", "lstart=", "-p", str(pid)], text=True).strip()
        _start_dt = dt.strptime(_ps_out, "%c")
        _uptime_delta = dt.now() - _start_dt
        _days = _uptime_delta.days
        _hours = _uptime_delta.seconds // 3600
        _mins = (_uptime_delta.seconds % 3600) // 60
        if _days > 0:
            _uptime_str = f"{_days}d {_hours}h {_mins}m"
        elif _hours > 0:
            _uptime_str = f"{_hours}h {_mins}m"
        else:
            _uptime_str = f"{_mins}m"
        st.sidebar.markdown(f"**Bot:** 🟢 Running ({_uptime_str})")
    except Exception:
        st.sidebar.markdown("**Bot:** 🟢 Running")
else:
    st.sidebar.markdown("**Bot:** 🔴 Stopped")

# Last activity from log (local dev). Falls back to Cloud Logging timestamp.
last_activity = _cloud_last_activity or "Unknown"
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

# === MARKET CLOCK (v2.0) ===
st.sidebar.markdown("---")
st.sidebar.subheader("Market Clock")
try:
    from utils.market_clock import get_market_clock
    _mkeys = secrets_vault.get_alpaca_keys(USER_ID)
    if not _mkeys:
        raise RuntimeError("no user keys for market clock")
    _mclock = get_market_clock(_mkeys[0], _mkeys[1])
    _mstatus = _mclock.get_status()
    _open_icon = "🟢" if _mstatus["is_open"] else "🔴"
    _open_label = "OPEN" if _mstatus["is_open"] else "CLOSED"
    st.sidebar.markdown(f"**Status:** {_open_icon} {_open_label}")
    st.sidebar.markdown(f"**ET Time:** {_mstatus['current_time_et']}")
    if _mstatus["is_early_close"]:
        st.sidebar.markdown("**Early Close Today**")
    if _mstatus["is_open"]:
        _mins_close = _mclock.minutes_until_close()
        if _mins_close is not None:
            _hrs = _mins_close // 60
            _mins = _mins_close % 60
            st.sidebar.markdown(f"**Closes in:** {_hrs}h {_mins}m")
    else:
        _mins_open = _mclock.minutes_until_open()
        if _mins_open is not None:
            if _mins_open < 60:
                st.sidebar.markdown(f"**Opens in:** {_mins_open}m")
            else:
                _hrs = _mins_open // 60
                _mins = _mins_open % 60
                st.sidebar.markdown(f"**Opens in:** {_hrs}h {_mins}m")
    if _mstatus["clock_drift_ms"] is not None:
        _drift = _mstatus["clock_drift_ms"]
        _drift_color = "🔴" if _drift > 5000 else ("🟡" if _drift > 2000 else "🟢")
        st.sidebar.markdown(f"**Clock Drift:** {_drift_color} {_drift:.0f}ms")
    st.sidebar.caption(f"Source: {_mstatus['source']}")
except Exception as _e:
    st.sidebar.markdown("**Market Clock:** unavailable")

# === SYSTEM HEALTH ===
st.sidebar.markdown("---")
st.sidebar.subheader("System Health")

try:
    _db_health = db.health_check()
    _db_ok = _db_health.get("status") == "ok"
    # Postgres returns `dialect`; SQLite returns `journal_mode`.
    if _db_health.get("dialect") == "postgresql":
        _db_label = "POSTGRES"
    elif _db_health.get("journal_mode"):
        _db_label = f"SQLITE {_db_health['journal_mode'].upper()}"
    else:
        _db_label = "unknown"
    st.sidebar.markdown(f"**Database:** {'🟢' if _db_ok else '🔴'} {_db_label}")
except Exception:
    st.sidebar.markdown("**Database:** 🔴 unavailable")

try:
    from utils.rate_limiter import RateLimiter as _RL
    _rl_status = _RL().newsapi_status()
    _rl_pct = _rl_status["pct_used"]
    _rl_color = "🟢" if _rl_pct < 80 else ("🟡" if _rl_pct < 95 else "🔴")
    st.sidebar.markdown(f"**NewsAPI:** {_rl_color} {_rl_status['used']}/{_rl_status['limit']} today")
except Exception:
    pass

try:
    from utils.state import StateManager as _SM
    _sm = _SM()
    _paused = _sm.paused_portfolios
    if _paused:
        st.sidebar.markdown(f"**Paused:** 🔴 {', '.join(_paused)}")
    else:
        st.sidebar.markdown("**Paused:** 🟢 None")

    # Warmup progress — DB-backed per-user counter (distinct tickers analyzed).
    # State-file warmup_tickers_seen is legacy single-user and stays at 0 on
    # Cloud Run where the dashboard has no filesystem access to the bot's state.
    try:
        with db._get_conn() as _wconn:
            _row = _wconn.execute(
                "SELECT COUNT(DISTINCT ticker) AS n FROM analysis_results WHERE user_id = ?",
                (USER_ID,),
            ).fetchone()
        _warmup_seen = _row["n"] if _row else 0
    except Exception:
        _warmup_seen = 0
    _warmup_target = config.WARMUP_MIN_TICKERS
    if _warmup_seen < _warmup_target:
        _warmup_pct = min(1.0, _warmup_seen / _warmup_target) if _warmup_target else 1.0
        st.sidebar.markdown(f"**Warmup:** {_warmup_seen}/{_warmup_target} tickers")
        st.sidebar.progress(_warmup_pct)
    else:
        st.sidebar.markdown(f"**Warmup:** 🟢 {_warmup_seen}/{_warmup_target} tickers — ready")
except Exception:
    pass

_state_path = os.path.join(os.path.dirname(__file__), ".state.json")
if os.path.exists(_state_path):
    _state_mtime = dt.fromtimestamp(os.path.getmtime(_state_path)).strftime("%H:%M:%S")
    st.sidebar.markdown(f"**State saved:** {_state_mtime}")

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
all_trades = db.get_recent_trades(USER_ID, 500, portfolio=_pf)
total_trades = len(all_trades)
open_trades_db = db.get_open_trades(USER_ID, portfolio=_pf)
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
# STATUS BANNER + PRIMARY KPI ROW (Sprint 6 clean-top redesign)
# ──────────────────────────────────────────────

# --- Status banner: bot health | market | regime | alerts -----------
# Computations stay at page scope so KPI row + later sections can read them.
_log_path = os.path.join(os.path.dirname(__file__), "deepthinktrader.log")
try:
    from utils.market_clock import get_market_clock as _get_clock
    _cs_keys = secrets_vault.get_alpaca_keys(USER_ID)
    _has_clock_keys = bool(_cs_keys)
except Exception:
    _cs_keys = None
    _has_clock_keys = False

_bot_status, _bot_detail = compute_bot_status(_log_path)
if _has_clock_keys:
    try:
        _market_label, _market_open = compute_market_state(_get_clock(_cs_keys[0], _cs_keys[1]))
    except Exception:
        _market_label, _market_open = "CLOSED", False
else:
    _market_label, _market_open = "?", False
_regime = compute_regime(config)
# True today-only P&L from Alpaca (resets at midnight ET). Falls back to 0
# if the account response is missing last_equity for any reason.
_today_pnl, _today_pnl_pct = compute_today_pnl(account)
_drawdown_pct = compute_drawdown_from_peak(portfolio_hist) if portfolio_hist else max_drawdown_pct
_halt_pct = float(getattr(config, "MAX_DRAWDOWN_HALT_PCT", 0.08)) * 100
# Revenge-streak calc — count trailing consecutive losses.
_streak = 0
for _t in reversed(closed_trades):
    if (_t.get("pnl") or 0) < 0:
        _streak += 1
    else:
        break
_banner_alerts = compute_alerts(
    paused_portfolios=set(getattr(state, "paused_portfolios", []) if "state" in globals() else []),
    drawdown_pct=_drawdown_pct,
    drawdown_halt_pct=_halt_pct,
    consecutive_losses=_streak,
    circuit_breaker_active=False,  # Risk_Dashboard page owns the live check
)

# Render the banner inside a 30s fragment so the time-sensitive parts
# (market countdown, "last log Xs ago") refresh independent of the heavy
# main-page rerun (default 5 min). Recomputes bot_status + market_state
# every fragment run; reuses regime/alerts from outer scope (slow-moving).
@st.fragment(run_every=30)
def _render_status_banner_fragment():
    bs, bd = compute_bot_status(_log_path)
    if _has_clock_keys:
        try:
            ml, mo = compute_market_state(_get_clock(_cs_keys[0], _cs_keys[1]))
        except Exception:
            ml, mo = "CLOSED", False
    else:
        ml, mo = "?", False
    render_status_banner(
        bot_status=bs, bot_detail=bd,
        market_state=ml, market_is_open=mo,
        regime_label=_regime["label"], regime_vol_pct=_regime["vol_pct"],
        recommended_mode=_regime["recommended_mode"],
        current_mode=config.TRADE_MODE,
        alerts=_banner_alerts,
    )

_render_status_banner_fragment()

# --- Primary KPI row: 5 numbers ------------------------------------
# Pass live equity so the 30-day value updates intraday instead of freezing
# at yesterday's daily-bar close.
_thirty_day_pnl, _thirty_day_pct = compute_30day_pnl(portfolio_hist, current_equity=equity)
_exposure_pct = compute_total_exposure_pct(positions, equity)
render_kpi_row(
    equity=equity,
    today_pnl=_today_pnl, today_pnl_pct=_today_pnl_pct,
    thirty_day_pnl=_thirty_day_pnl, thirty_day_pnl_pct=_thirty_day_pct,
    open_positions_count=len(open_trades_db),
    total_exposure_pct=_exposure_pct,
    drawdown_from_peak_pct=_drawdown_pct,
    drawdown_halt_pct=_halt_pct,
)

# --- Full metrics (collapsed by default) ---------------------------
with st.expander("Full metrics (Sharpe, Sortino, rolling windows, edge quality)", expanded=False):
    st.markdown('<div class="section-header">Account Overview</div>', unsafe_allow_html=True)

    _pnl_card = "kpi-card-green" if total_pnl >= 0 else "kpi-card-red"
    _dd_card = "kpi-card-amber" if max_drawdown_pct > 5 else "kpi-card"

    _card_left, _card_mid, _card_right = st.columns(3)

    with _card_left:
        st.markdown(f'<div class="{_pnl_card}">', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.metric(
                "Portfolio Value",
                f"${equity:,.2f}",
                delta=f"${total_pnl:+,.2f}",
                delta_color="normal" if total_pnl >= 0 else "inverse",
            )
        with c2:
            st.metric("Cash", f"${cash:,.2f}")
        c3, c4 = st.columns(2)
        with c3:
            st.metric("Realized P&L", f"${realized_pnl:+,.2f}",
                      delta_color="normal" if realized_pnl >= 0 else "inverse")
        with c4:
            st.metric("Unrealized P&L", f"${unrealized_pnl:+,.2f}",
                      delta_color="normal" if unrealized_pnl >= 0 else "inverse")
        st.markdown('</div>', unsafe_allow_html=True)

    with _card_mid:
        _wr_card = "kpi-card-green" if win_rate >= 55 else ("kpi-card-red" if win_rate < 45 and closed_trades else "kpi-card")
        st.markdown(f'<div class="{_wr_card}">', unsafe_allow_html=True)
        p1, p2 = st.columns(2)
        with p1:
            st.metric("Win Rate", f"{win_rate:.0f}%" if closed_trades else "N/A")
        with p2:
            st.metric("Total Trades", total_trades)
        p3, p4 = st.columns(2)
        with p3:
            st.metric("Profit Factor", f"{profit_factor:.2f}" if profit_factor > 0 else "N/A")
        with p4:
            _expectancy = (avg_win * (win_rate/100) - avg_loss * (1-win_rate/100)) if closed_trades else 0
            st.metric("Expectancy", f"${_expectancy:+,.2f}" if closed_trades else "N/A")
        st.markdown('</div>', unsafe_allow_html=True)

    with _card_right:
        st.markdown(f'<div class="{_dd_card}">', unsafe_allow_html=True)
        r1, r2 = st.columns(2)
        with r1:
            st.metric("Max Drawdown", f"-{max_drawdown_pct:.1f}%",
                      delta=f"-${max_drawdown_dollars:,.0f}" if max_drawdown_dollars > 0 else "$0",
                      delta_color="normal" if max_drawdown_dollars > 0 else "off")
        with r2:
            st.metric("Sharpe Ratio", f"{sharpe_ratio:.2f}")
        r3, r4 = st.columns(2)
        with r3:
            st.metric("Sortino Ratio", f"{sortino_ratio:.2f}")
        with r4:
            st.metric("Open Positions", len(open_trades_db))
        st.markdown('</div>', unsafe_allow_html=True)

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

    # ── Edge Quality Metrics (v2.0) ───────────────
    # Compute from trades that have edges_fired column
    _trades_with_edges = [t for t in all_trades if t.get("edges_fired") is not None]
    if _trades_with_edges:
        _avg_edges = np.mean([t["edges_fired"] for t in _trades_with_edges])
        _edge_trades_passed = sum(1 for t in _trades_with_edges if t["edges_fired"] >= config.MIN_EDGES_REQUIRED)
        _edge_hit_rate = (_edge_trades_passed / len(_trades_with_edges) * 100) if _trades_with_edges else 0

        ecol1, ecol2, ecol3 = st.columns(3)
        with ecol1:
            st.metric("Avg Edges/Trade", f"{_avg_edges:.1f}/3")
        with ecol2:
            st.metric("Edge Pass Rate", f"{_edge_hit_rate:.0f}%")
        with ecol3:
            # Breakdown by edge type from closed trades with edge_details
            _edge_labels = {"Fundamental": 0, "Technical": 0, "Sentiment": 0}
            _edge_totals = {"Fundamental": 0, "Technical": 0, "Sentiment": 0}
            for t in _trades_with_edges:
                details = t.get("edge_details")
                if details:
                    try:
                        edges = json.loads(details) if isinstance(details, str) else details
                        for e in edges:
                            lbl = e.get("label", "")
                            if lbl in _edge_labels:
                                _edge_totals[lbl] += 1
                                if e.get("passed"):
                                    _edge_labels[lbl] += 1
                    except Exception:
                        pass
            edge_rates = []
            for lbl in ["Fundamental", "Technical", "Sentiment"]:
                total = _edge_totals[lbl]
                passed = _edge_labels[lbl]
                rate = f"{passed}/{total}" if total > 0 else "—"
                edge_rates.append(f"{lbl[:4]}: {rate}")
            st.metric("Edge Breakdown", " | ".join(edge_rates))

    st.markdown("")

# ──────────────────────────────────────────────
# PERFORMANCE vs BENCHMARKS
# ──────────────────────────────────────────────

st.markdown('<div class="section-header">Performance vs Market Benchmarks</div>', unsafe_allow_html=True)

_PERIOD_OPTIONS = {
    "1 D": ("1d", "1D"),
    "5 D": ("5d", "5D"),
    "30 D": ("1mo", "30D"),
    "90 D": ("3mo", "90D"),
    "180 D": ("6mo", "180D"),
    "1 Y": ("1y", "1Y"),
    "3 Y": ("3y", "3Y"),
}
_ALPACA_PERIOD_MAP = {
    "1 D": "1D", "5 D": "1W", "30 D": "1M", "90 D": "3M",
    "180 D": "6M", "1 Y": "1A", "3 Y": "3A",
}
# Intraday timeframes for short periods
_ALPACA_TF_MAP = {
    "1 D": "15Min", "5 D": "1H",
    "30 D": "1D", "90 D": "1D", "180 D": "1D", "1 Y": "1D", "3 Y": "1D",
}

_bench_period = st.segmented_control(
    "Period",
    options=list(_PERIOD_OPTIONS.keys()),
    default="5 D",
    key="bench_period",
    label_visibility="collapsed",
)
if not _bench_period:
    _bench_period = "5 D"

_yf_period, _display_period = _PERIOD_OPTIONS[_bench_period]

@st.cache_data(ttl=120)
def _get_benchmark_data(yf_period: str, intraday: bool = False):
    """Fetch index performance for comparison chart."""
    import yfinance as yf

    benchmarks = {"^DJI": "Dow Jones", "^GSPC": "S&P 500", "^IXIC": "Nasdaq"}
    series = {}

    for sym, label in benchmarks.items():
        try:
            if intraday:
                hist = yf.Ticker(sym).history(period=yf_period, interval="15m")
            else:
                hist = yf.Ticker(sym).history(period=yf_period)
            if not hist.empty:
                closes = hist["Close"]
                base = closes.iloc[0]
                pct = ((closes - base) / base) * 100
                series[label] = pct
        except Exception:
            pass

    return series

@st.cache_data(ttl=60)
def _get_portfolio_history_period(alpaca_period: str):
    """Fetch bot portfolio history for the selected period."""
    try:
        tf = _ALPACA_TF_MAP.get(_bench_period, "1D")
        resp = http_requests.get(
            f"{config.ALPACA_BASE_URL}/v2/account/portfolio/history",
            headers=ALPACA_HEADERS,
            params={
                "period": alpaca_period,
                "timeframe": tf,
                "intraday_reporting": "market_hours",
                "pnl_reset": "per_day",
            },
            timeout=10,
        )
        if resp.ok:
            data = resp.json()
            if data.get("equity"):
                ts = data["timestamp"]
                eq = data["equity"]
                pnl = data.get("profit_loss", [0] * len(eq))
                # Filter to baseline date
                baseline = config.BASELINE_DATE
                if baseline:
                    from datetime import datetime as _dt
                    baseline_ts = int(_dt.strptime(baseline, "%Y-%m-%d").timestamp())
                else:
                    baseline_ts = 0
                fts, feq, fpnl = [], [], []
                prev_eq = None
                for i, e in enumerate(eq):
                    if e and e > 0 and ts[i] >= baseline_ts:
                        # Skip settlement artifacts: equity drops >50% in one bar
                        # (cash-only snapshots between sell/buy cycles). 2026-05-21:
                        # loosened from 0.8 -> 0.5 so real drawdowns (e.g. flash-crash
                        # hours) aren't masked. A -17% phantom will now show as a
                        # single bar but won't be filtered.
                        if prev_eq and e < prev_eq * 0.5:
                            continue
                        fts.append(ts[i])
                        feq.append(e)
                        fpnl.append(pnl[i] if i < len(pnl) else 0)
                        prev_eq = e
                data["timestamp"] = fts
                data["equity"] = feq
                data["profit_loss"] = fpnl
            return data
    except Exception:
        pass
    return None

_is_intraday = _bench_period in ("1 D", "5 D")
benchmark_data = _get_benchmark_data(_yf_period, intraday=_is_intraday)
_port_hist = _get_portfolio_history_period(_ALPACA_PERIOD_MAP[_bench_period])

if _port_hist and _port_hist.get("equity") and benchmark_data:
    eq = _port_hist["equity"]
    ts = _port_hist["timestamp"]

    # Show "last trading day" label when market is closed and viewing 1D
    if _bench_period == "1 D" and not _mstatus["is_open"] and ts:
        from datetime import datetime as _dtx
        _last_day = _dtx.fromtimestamp(ts[-1]).strftime("%A, %b %-d")
        st.caption(f"Market closed — showing last trading day: {_last_day}")

    if eq and ts and eq[0] and eq[0] > 0:
        bot_dates_raw = pd.to_datetime(ts, unit="s").tz_localize("UTC").tz_convert("US/Eastern")

        # For intraday views: filter to market hours only (9:30-16:00 ET)
        # and keep actual timestamps (don't normalize to midnight)
        if _is_intraday:
            bot_dates = bot_dates_raw
            # Filter out pre-market / after-hours data points
            mask = bot_dates.map(lambda t: 9 * 60 + 30 <= t.hour * 60 + t.minute <= 16 * 60)
            bot_dates = bot_dates[mask]
            eq = [e for e, m in zip(eq, mask) if m]
        else:
            bot_dates = bot_dates_raw.normalize()

        if len(eq) == 0 or len(bot_dates) == 0:
            st.info("No market-hours data yet for this period.")
        else:
            # Skip leading settlement artifacts: initial cash-only snapshots
            # before positions are reflected (e.g. $35K cash vs $90K with positions).
            # 2026-05-21: tightened from 0.6 -> 0.4 so real drawdowns at the start
            # of the window aren't trimmed; only severe cash-only snapshots are.
            if len(eq) > 2:
                median_eq = sorted(eq)[len(eq) // 2]
                while len(eq) > 2 and eq[0] < median_eq * 0.4:
                    eq = eq[1:]
                    bot_dates = bot_dates[1:]

            bot_base = eq[0]
            bot_pct = [((e - bot_base) / bot_base) * 100 for e in eq]

            fig_bench = go.Figure()

            colors = {"Dow Jones": "#1f77b4", "S&P 500": "#ff7f0e", "Nasdaq": "#2ca02c"}
            # Re-anchor benchmark to bot's first timestamp so both series share
            # the same zero point. yfinance's pct_series is already anchored to
            # its own first bar; that's only the same point as bot's first bar
            # when no leading bot bars were filtered.
            bot_start_ts = bot_dates.min()
            for label, pct_series in benchmark_data.items():
                if len(pct_series) == 0:
                    continue
                pct_idx = pct_series.index
                # Normalize tz for comparison with bot_start_ts (US/Eastern)
                if _is_intraday:
                    if pct_idx.tz is None:
                        pct_idx_cmp = pct_idx.tz_localize("US/Eastern")
                    else:
                        pct_idx_cmp = pct_idx.tz_convert("US/Eastern")
                else:
                    pct_idx_cmp = pct_idx
                pct_mask = pct_idx_cmp >= bot_start_ts
                if not pct_mask.any():
                    continue
                aligned = pct_series[pct_mask]
                if len(aligned) > 0:
                    aligned = aligned - aligned.iloc[0]
                fig_bench.add_trace(go.Scatter(
                    x=aligned.index,
                    y=aligned.values,
                    name=label,
                    line=dict(color=colors.get(label, "#999"), width=2, dash="dot"),
                    opacity=0.8,
                ))

            fig_bench.add_trace(go.Scatter(
                x=bot_dates,
                y=bot_pct,
                name="DeepThinkTrader",
                line=dict(color="#e040fb", width=3),
            ))

            fig_bench.add_hline(y=0, line_dash="dash", line_color="gray", opacity=0.4)

            fig_bench.update_layout(
                title="",
                yaxis_title="Return %",
                xaxis_title="",
                height=400,
                template="plotly_dark",
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
                margin=dict(l=40, r=20, t=10, b=40),
                hovermode="x unified",
            )
            apply_chart_theme(fig_bench)
            st.plotly_chart(fig_bench, use_container_width=True)

            # Summary metrics
            bcols = st.columns(4)
            bot_return = bot_pct[-1] if bot_pct else 0
            bcols[0].metric("DeepThinkTrader", f"{bot_return:+.2f}%")
            bot_start_ts = bot_dates.min()
            for i, (label, pct_series) in enumerate(benchmark_data.items()):
                if i < 3:
                    if len(pct_series) == 0:
                        bench_return = 0
                    else:
                        pct_idx = pct_series.index
                        if _is_intraday:
                            if pct_idx.tz is None:
                                pct_idx_cmp = pct_idx.tz_localize("US/Eastern")
                            else:
                                pct_idx_cmp = pct_idx.tz_convert("US/Eastern")
                        else:
                            pct_idx_cmp = pct_idx
                        pct_mask = pct_idx_cmp >= bot_start_ts
                        if pct_mask.any():
                            aligned = pct_series[pct_mask]
                            bench_return = (aligned.iloc[-1] - aligned.iloc[0]) if len(aligned) > 0 else 0
                        else:
                            bench_return = 0
                    delta = bot_return - bench_return
                    bcols[i + 1].metric(label, f"{bench_return:+.2f}%", delta=f"{delta:+.2f}% vs bot")
    else:
        st.info("Waiting for portfolio equity history to build (need at least 2 data points).")
else:
    st.info("Portfolio history or benchmark data unavailable.")

st.divider()

# ──────────────────────────────────────────────
# STRATEGY HEALTH (Phase 5c) — Moved up for visibility
# ──────────────────────────────────────────────

st.markdown('<div class="section-header">Strategy Health</div>', unsafe_allow_html=True)

def _show_strategy_health_top(portfolio_name: str):
    stats = db.get_strategy_stats(USER_ID, portfolio_name, days=30)
    baseline = db.get_strategy_stats(USER_ID, portfolio_name, days=90)
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
            st.metric("WR vs 90d Baseline", f"{delta:+.0f}%")
        else:
            st.metric("WR vs 90d Baseline", "N/A")

    # Expectancy trend chart — rolling 10-trade windows
    if stats["trade_count"] >= 10:
        with db._get_conn() as conn:
            from datetime import timedelta
            cutoff = (dt.now() - timedelta(days=90)).isoformat()
            rows = conn.execute(
                """SELECT pnl, timestamp FROM trades
                   WHERE status = 'CLOSED' AND portfolio = ? AND timestamp >= ? AND pnl IS NOT NULL
                   ORDER BY timestamp""",
                (portfolio_name, cutoff),
            ).fetchall()
        if len(rows) >= 10:
            pnl_list = [r["pnl"] for r in rows]
            ts_list = [r["timestamp"] for r in rows]
            window = 10
            exp_points = []
            for i in range(window, len(pnl_list) + 1):
                w = pnl_list[i - window:i]
                wins = [p for p in w if p > 0]
                losses = [p for p in w if p <= 0]
                wr = len(wins) / len(w)
                avg_w = np.mean(wins) if wins else 0
                avg_l = abs(np.mean(losses)) if losses else 0
                exp = (wr * avg_w) - ((1 - wr) * avg_l)
                exp_points.append({"timestamp": ts_list[i - 1], "expectancy": exp})

            if exp_points:
                df_exp = pd.DataFrame(exp_points)
                df_exp["timestamp"] = pd.to_datetime(df_exp["timestamp"])
                fig_exp = go.Figure()
                colors = ["#4CAF50" if e >= 0 else "#F44336" for e in df_exp["expectancy"]]
                fig_exp.add_trace(go.Bar(
                    x=df_exp["timestamp"], y=df_exp["expectancy"],
                    marker_color=colors, name="Expectancy",
                ))
                fig_exp.add_hline(y=0, line_color="gray", line_width=1)
                fig_exp.update_layout(
                    title=f"{portfolio_name.title()} — Rolling 10-Trade Expectancy",
                    yaxis_title="Expectancy ($)", height=220,
                    margin=dict(l=0, r=0, t=40, b=0),
                )
                apply_chart_theme(fig_exp)
                st.plotly_chart(fig_exp, use_container_width=True)

_show_strategy_health_top("main")
if config.PENNY_ENABLED:
    _show_strategy_health_top("penny")

st.divider()

# ──────────────────────────────────────────────
# PORTFOLIO VALUE + SPY BENCHMARK (Tier 1 #1, #5)
# ──────────────────────────────────────────────

st.markdown('<div class="section-header">Portfolio Value vs SPY Benchmark</div>', unsafe_allow_html=True)
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
        apply_chart_theme(fig_port)
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
            apply_chart_theme(fig_dd)
            st.plotly_chart(fig_dd, use_container_width=True)
else:
    st.info("Portfolio history will populate after first trading day")

st.divider()

# ──────────────────────────────────────────────
# RISK & MEMORY — Kelly / CVaR / correlation / reflections
# ──────────────────────────────────────────────

# Pull the risk_manager instance lazily so importing dashboard.py in tests
# doesn't reach out to Alpaca.
_user_keys = secrets_vault.get_alpaca_keys(USER_ID)
try:
    from utils.risk_manager import RiskManager
    if _user_keys:
        _rm = RiskManager(
            user_id=USER_ID, api_key=_user_keys[0], secret_key=_user_keys[1], db=db,
        )
        _kelly = compute_kelly_state(db, _rm, USER_ID, portfolio=_pf if _pf else "main")
    else:
        _kelly = {"fraction": None, "n_trades": 0, "win_rate": None}
except Exception:
    _kelly = {"fraction": None, "n_trades": 0, "win_rate": None}
if _user_keys:
    _cvar = compute_portfolio_cvar(positions, _user_keys[0], _user_keys[1])
    _top_corr = compute_top_correlation(positions, _user_keys[0], _user_keys[1])
else:
    _cvar = None
    _top_corr = None
_reflections = compute_recent_reflections(db, USER_ID, limit=3)

render_risk_memory(
    kelly_fraction=_kelly["fraction"],
    kelly_n_trades=_kelly["n_trades"],
    kelly_win_rate=_kelly["win_rate"],
    portfolio_cvar_pct=_cvar,
    cvar_limit_pct=float(getattr(config, "MAX_PORTFOLIO_CVAR_PCT", 0.05)),
    top_correlation=_top_corr,
    recent_reflections=_reflections,
)

st.divider()

# ──────────────────────────────────────────────
# DAILY P&L BAR CHART (Tier 1 #4)
# ──────────────────────────────────────────────

st.markdown('<div class="section-header">Daily P&L</div>', unsafe_allow_html=True)
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
        apply_chart_theme(fig_daily)
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
# MANUAL TRADE (admin only)
# ──────────────────────────────────────────────

if CURRENT_USER.get("role") == "admin":
    st.markdown('<div class="section-header">Manual Trade</div>', unsafe_allow_html=True)
    with st.expander("Open or close a position manually", expanded=False):
        with st.form("manual_trade_form", clear_on_submit=False):
            mc1, mc2, mc3 = st.columns([1, 1, 1])
            with mc1:
                mt_action = st.radio(
                    "Action", ["BUY", "SELL", "CLOSE"], horizontal=True, key="mt_action",
                )
            with mc2:
                mt_ticker_raw = st.text_input(
                    "Ticker", value="", placeholder="AAPL", key="mt_ticker",
                )
            with mc3:
                mt_portfolio = st.selectbox(
                    "Portfolio", ["main", "penny"], key="mt_portfolio",
                )

            if mt_action in ("BUY", "SELL"):
                sc1, sc2, sc3 = st.columns(3)
                with sc1:
                    mt_shares = st.number_input(
                        "Shares", min_value=1, value=10, step=1, key="mt_shares",
                    )
                with sc2:
                    mt_stop = st.number_input(
                        "Stop loss %", min_value=0.1, value=2.0, step=0.1, key="mt_stop",
                    )
                with sc3:
                    mt_tp = st.number_input(
                        "Take profit %", min_value=0.1, value=4.0, step=0.1, key="mt_tp",
                    )
                mt_override = st.checkbox(
                    "Override signal filters (spread/liquidity/sector/edges/etc.) — "
                    "account-protection checks still apply",
                    value=True,
                    key="mt_override",
                )
            else:
                mt_shares = mt_stop = mt_tp = None
                mt_override = False

            mt_note = st.text_input("Note (saved with the trade)", value="", key="mt_note")
            mt_submit = st.form_submit_button(f"Execute {mt_action}")

        if mt_submit:
            _ticker = (mt_ticker_raw or "").upper().strip()
            if not _ticker:
                st.error("Ticker is required.")
            else:
                from agents.execution_agent import ExecutionAgent
                from utils import secrets_vault
                from utils.database import Database

                _keys = secrets_vault.get_alpaca_keys(USER_ID)
                if not _keys:
                    st.error("No Alpaca keys configured for this user.")
                else:
                    _ea = ExecutionAgent(
                        user_id=USER_ID,
                        api_key=_keys[0],
                        secret_key=_keys[1],
                        db=Database(),
                    )
                    if mt_action == "CLOSE":
                        result = _ea.manual_close(
                            _ticker, portfolio=mt_portfolio, note=mt_note,
                        )
                    else:
                        # Live price from Alpaca snapshot
                        _price = 0.0
                        try:
                            _resp = http_requests.get(
                                f"https://data.alpaca.markets/v2/stocks/{_ticker}/snapshot",
                                headers=_user_alpaca_headers(USER_ID) or {},
                                timeout=5,
                            )
                            _resp.raise_for_status()
                            _snap = _resp.json()
                            _latest = _snap.get("latestTrade") or {}
                            _price = float(_latest.get("p") or 0)
                            if _price <= 0:
                                _q = _snap.get("latestQuote") or {}
                                _price = float(_q.get("ap") or _q.get("bp") or 0)
                        except Exception as _e:
                            st.warning(f"Live price fetch failed: {_e}")

                        if _price <= 0:
                            st.error(f"Could not fetch a live price for {_ticker}. Aborting.")
                            result = None
                        else:
                            _analysis = {
                                "ticker": _ticker,
                                "action": mt_action,
                                "conviction": 10.0,
                                "stop_loss_pct": float(mt_stop),
                                "take_profit_pct": float(mt_tp),
                                "current_price": _price,
                                "edges_firing": 0,
                                "proposed_shares": int(mt_shares),
                                "reasoning": f"MANUAL ({mt_action}): {mt_note or 'no note'}",
                            }
                            result = _ea.execute(
                                _analysis,
                                portfolio=mt_portfolio,
                                is_manual=True,
                                bypass_filters=bool(mt_override),
                            )

                    if result is not None:
                        _status = result.get("status")
                        if _status in ("OPEN", "EXECUTED", "CLOSED") or result.get("trade_id"):
                            st.success(result.get("message") or f"OK — {_status}")
                        elif _status == "BLOCKED":
                            st.warning(f"Blocked: {result.get('message')}")
                            if result.get("failures"):
                                st.caption("Failed checks: " + ", ".join(result["failures"]))
                        else:
                            st.error(result.get("message") or f"Error: {result}")
                        with st.expander("Full result", expanded=False):
                            st.json(result)

    st.divider()

# ──────────────────────────────────────────────
# LIVE POSITIONS
# ──────────────────────────────────────────────

st.markdown('<div class="section-header">Current Positions (Live)</div>', unsafe_allow_html=True)
if positions:
    # Build lookup of DB trade data for open positions (trailing stops, risk, edges)
    _open_db_trades = {t["ticker"]: t for t in open_trades_db}

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

        ticker = p["symbol"]
        db_trade = _open_db_trades.get(ticker, {})
        trailing_active = db_trade.get("trailing_stop_active", 0)
        trailing_stop = db_trade.get("trailing_stop_price")
        highest = db_trade.get("highest_price")
        risk_amt = db_trade.get("risk_amount", 0)
        original_qty = db_trade.get("original_quantity")
        current_qty = int(p["qty"])
        edges = db_trade.get("edges_fired")

        # Calculate R-multiple
        r_multiple = ""
        entry = float(p["avg_entry_price"])
        current = float(p["current_price"])
        if risk_amt and risk_amt > 0 and original_qty and original_qty > 0:
            r_per_share = risk_amt / original_qty
            profit_per_share = current - entry
            if r_per_share > 0:
                r_multiple = f"{profit_per_share / r_per_share:.1f}R"

        # Scale-out indicator
        scaled = ""
        if original_qty and current_qty < original_qty:
            scaled = f"{current_qty}/{original_qty}"

        pos_data.append({
            "Ticker": ticker,
            "Details": f"{YAHOO_URL}/{ticker}",
            "Qty": current_qty,
            "Scaled": scaled,
            "Avg Entry": entry,
            "Current": current,
            "Market Value": market_val,
            "P&L": unrealized,
            "P&L %": unrealized_pct,
            "R-Mult": r_multiple,
            "Trail": f"${trailing_stop:.2f}" if trailing_active and trailing_stop else "—",
            "High": f"${highest:.2f}" if highest else "—",
            "Edges": f"{edges}/3" if edges is not None else "—",
        })

    # Add cash (uninvested) as a line item
    pos_data.append({
        "Ticker": "CASH",
        "Details": "",
        "Qty": 0,
        "Scaled": "",
        "Avg Entry": 0,
        "Current": 0,
        "Market Value": cash,
        "P&L": 0,
        "P&L %": 0,
        "R-Mult": "",
        "Trail": "—",
        "High": "—",
        "Edges": "—",
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
            apply_chart_theme(fig_pnl)
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
        fig_pie.update_layout(
            height=360,
            margin=dict(l=10, r=10, t=40, b=60),
            legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
        )
        apply_chart_theme(fig_pie)
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
                fig_sector.update_layout(
                    height=360,
                    margin=dict(l=10, r=10, t=40, b=60),
                    legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5),
                )
                apply_chart_theme(fig_sector)
                st.plotly_chart(fig_sector, use_container_width=True)
else:
    st.info("No open positions")

st.divider()

# ──────────────────────────────────────────────
# TRADE HISTORY (Tier 2 #8: Filtering + Export)
# ──────────────────────────────────────────────

st.markdown('<div class="section-header">Trade History</div>', unsafe_allow_html=True)
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

    # Edges fired column
    if "edges_fired" in df_trades.columns:
        df_trades["edges"] = df_trades["edges_fired"].apply(lambda x: f"{int(x)}/3" if x is not None and pd.notna(x) else "—")

    # Risk amount column
    if "risk_amount" in df_trades.columns:
        df_trades["risk"] = df_trades["risk_amount"].apply(lambda x: f"${x:,.2f}" if x and pd.notna(x) and x > 0 else "—")

    # Exit reason column (clean up for display)
    if "exit_reason" in df_trades.columns:
        df_trades["exit"] = df_trades["exit_reason"].apply(lambda x: x if x and pd.notna(x) else "—")

    # Format prices
    for col in ["entry_price", "exit_price", "stop_loss_price", "take_profit_price"]:
        if col in df_trades.columns:
            df_trades[col] = df_trades[col].apply(lambda x: f"${x:,.2f}" if x and x > 0 else "—")
    if "pnl" in df_trades.columns:
        df_trades["pnl"] = df_trades["pnl"].apply(lambda x: f"${x:+,.2f}" if x else "—")

    df_trades["details"] = df_trades["ticker"].apply(lambda t: f"{YAHOO_URL}/{t}")

    display_cols = [
        "ticker", "details", "action", "quantity", "entry_price", "invested", "stop_loss_price",
        "take_profit_price", "exit_price", "conviction", "edges", "risk", "pnl", "exit",
        "hold_time", "status", "timestamp",
    ]
    available_cols = [c for c in display_cols if c in df_trades.columns]
    st.dataframe(
        df_trades[available_cols],
        use_container_width=True,
        column_config={
            "details": st.column_config.LinkColumn("Yahoo Finance", display_text="View"),
        },
    )

    # Trade Reasoning Detail View
    if "reasoning" in df_trades_raw.columns:
        trades_with_reasoning = df_trades_raw[
            df_trades_raw["reasoning"].notna() & (df_trades_raw["reasoning"] != "")
        ]
        if not trades_with_reasoning.empty:
            with st.expander("Trade Reasoning Details", expanded=False):
                # PDF-style export: generate a full trade report as downloadable text
                _report_lines = ["DEEPTHINKTRADER — TRADE REASONING REPORT",
                                 f"Generated: {dt.now().strftime('%Y-%m-%d %H:%M')}",
                                 "=" * 60, ""]
                for _, row in trades_with_reasoning.head(20).iterrows():
                    ticker = row.get("ticker", "?")
                    ts = row.get("timestamp", "")[:16] if row.get("timestamp") else ""
                    action = row.get("action", "")
                    conv = row.get("conviction", 0)
                    pnl = row.get("pnl")
                    pnl_str = f" | P&L: ${pnl:+,.2f}" if pnl and pnl != 0 else ""
                    status = row.get("status", "")
                    status_icon = "🟢" if status == "OPEN" else ("🟩" if pnl and pnl > 0 else "🟥")

                    st.markdown(
                        f"**{status_icon} {action} {ticker}** — {ts} | "
                        f"Conviction: {conv}/10{pnl_str}"
                    )
                    st.text(row["reasoning"])
                    st.divider()

                    # Build export text
                    _report_lines.append(f"{action} {ticker} — {ts}")
                    _report_lines.append(f"Status: {status} | Conviction: {conv}/10{pnl_str}")
                    _edges = row.get("edges_fired")
                    if _edges is not None:
                        _report_lines.append(f"Edges: {int(_edges)}/3")
                    _report_lines.append("")
                    _report_lines.append(str(row.get("reasoning", "")))
                    _report_lines.append("-" * 60)
                    _report_lines.append("")

                _report_text = "\n".join(_report_lines)
                st.download_button(
                    "Export Trade Report",
                    _report_text,
                    f"trade_report_{dt.now().strftime('%Y%m%d')}.txt",
                    "text/plain",
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
        apply_chart_theme(fig_cum)
        st.plotly_chart(fig_cum, use_container_width=True)
else:
    from utils.brand import HERO_NO_TRADES
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.image(HERO_NO_TRADES, use_container_width=True)
    st.markdown(
        "<p style='text-align:center;color:#7D8590;'>No trades yet — the bot "
        "is warming up. First trades usually land within the first few market "
        "sessions.</p>",
        unsafe_allow_html=True,
    )

st.divider()

# ──────────────────────────────────────────────
# RECENT ANALYSES
# ──────────────────────────────────────────────

st.markdown('<div class="section-header">Recent Analyses</div>', unsafe_allow_html=True)
analyses = db.get_recent_analyses(USER_ID, 100, portfolio=_pf)
if analyses:
    df_analysis = pd.DataFrame(analyses)

    # Extract fields from stored JSON — now with edge data
    extra_cols = {"price": [], "edges_firing": [], "fund_edge": [], "tech_edge": [], "sent_edge": []}
    for a in analyses:
        try:
            data = json.loads(a.get("analysis_json", "{}"))
            extra_cols["price"].append(data.get("current_price"))
            ef = data.get("edges_firing")
            extra_cols["edges_firing"].append(ef)

            # Parse individual edge results
            edge_details = data.get("edge_details", [])
            fund = tech = sent = None
            for ed in edge_details:
                lbl = ed.get("label", "")
                passed = ed.get("passed", False)
                if lbl == "Fundamental":
                    fund = passed
                elif lbl == "Technical":
                    tech = passed
                elif lbl == "Sentiment":
                    sent = passed
            extra_cols["fund_edge"].append(fund)
            extra_cols["tech_edge"].append(tech)
            extra_cols["sent_edge"].append(sent)
        except Exception:
            for k in extra_cols:
                extra_cols[k].append(None)

    df_analysis["price"] = [f"${x:,.2f}" if x else "N/A" for x in extra_cols["price"]]
    df_analysis["edges"] = [f"{x}/3" if x is not None else "—" for x in extra_cols["edges_firing"]]
    df_analysis["fund"] = [("PASS" if x else "FAIL") if x is not None else "—" for x in extra_cols["fund_edge"]]
    df_analysis["tech"] = [("PASS" if x else "FAIL") if x is not None else "—" for x in extra_cols["tech_edge"]]
    df_analysis["sent"] = [("PASS" if x else "FAIL") if x is not None else "—" for x in extra_cols["sent_edge"]]

    df_analysis["details"] = df_analysis["ticker"].apply(lambda t: f"{YAHOO_URL}/{t}")

    display_cols = ["ticker", "details", "price", "action", "conviction", "edges",
                    "fund", "tech", "sent", "stop_loss_pct", "take_profit_pct", "timestamp"]
    available_cols = [c for c in display_cols if c in df_analysis.columns]
    st.dataframe(
        df_analysis[available_cols],
        use_container_width=True,
        column_config={
            "details": st.column_config.LinkColumn("Yahoo Finance", display_text="View"),
        },
    )

    # Analysis-to-trade conversion rate + edge stats
    total_analyses = len(analyses)
    buy_count = sum(1 for a in analyses if a.get("action") == "BUY")
    sell_count = sum(1 for a in analyses if a.get("action") == "SELL")
    hold_count = total_analyses - buy_count - sell_count
    conversion = ((buy_count + sell_count) / total_analyses * 100) if total_analyses > 0 else 0

    # Edge-blocked vs conviction-blocked
    _edges_list = [e for e in extra_cols["edges_firing"] if e is not None]
    _edge_blocked = sum(1 for e in _edges_list if e < config.MIN_EDGES_REQUIRED)

    acol1, acol2, acol3, acol4, acol5 = st.columns(5)
    with acol1:
        st.metric("Analyzed", total_analyses)
    with acol2:
        st.metric("BUY Signals", buy_count)
    with acol3:
        st.metric("SELL Signals", sell_count)
    with acol4:
        st.metric("Selectivity", f"{conversion:.1f}% traded")
    with acol5:
        st.metric("Edge-Blocked", _edge_blocked)

    # Conviction distribution + edge distribution side by side
    chart_col1, chart_col2 = st.columns(2)
    with chart_col1:
        fig2 = px.histogram(df_analysis, x="conviction", nbins=10,
                            title="Conviction Score Distribution",
                            color_discrete_sequence=["#2196F3"])
        fig2.update_layout(height=280, margin=dict(l=0, r=0, t=40, b=0))
        apply_chart_theme(fig2)
        st.plotly_chart(fig2, use_container_width=True)
    with chart_col2:
        if _edges_list:
            fig_edges = px.histogram(x=_edges_list, nbins=4,
                                     title="Edges Firing Distribution (0-3)",
                                     color_discrete_sequence=["#FF9800"],
                                     labels={"x": "Edges Firing", "count": "Count"})
            fig_edges.update_layout(height=280, margin=dict(l=0, r=0, t=40, b=0),
                                    xaxis=dict(dtick=1))
            apply_chart_theme(fig_edges)
            st.plotly_chart(fig_edges, use_container_width=True)
else:
    st.info("No analyses yet")

st.divider()

# ──────────────────────────────────────────────
# BOT CONFIG (read-only)
# ──────────────────────────────────────────────

# ──────────────────────────────────────────────
# SCALE-OUT LOG (v2.0)
# ──────────────────────────────────────────────

with st.expander("Scale-Out History (Partial Exits)"):
    with db._get_conn() as _conn:
        _partial_rows = _conn.execute(
            """SELECT pe.*, t.ticker, t.entry_price, t.action
               FROM partial_exits pe
               JOIN trades t ON pe.trade_id = t.id
               ORDER BY pe.timestamp DESC LIMIT 50"""
        ).fetchall()

    if _partial_rows:
        _partial_data = []
        for r in _partial_rows:
            rd = dict(r)
            entry = rd.get("entry_price", 0)
            exit_p = rd.get("exit_price", 0)
            _partial_data.append({
                "Ticker": rd.get("ticker", ""),
                "Qty Sold": rd.get("quantity", 0),
                "Entry": f"${entry:,.2f}" if entry else "—",
                "Exit": f"${exit_p:,.2f}" if exit_p else "—",
                "P&L": f"${rd.get('pnl', 0):+,.2f}" if rd.get("pnl") else "—",
                "Reason": rd.get("reason", ""),
                "Timestamp": rd.get("timestamp", ""),
            })
        st.dataframe(pd.DataFrame(_partial_data), use_container_width=True, hide_index=True)
    else:
        st.info("No partial exits recorded yet")

st.divider()

with st.expander("Bot Configuration"):
    mode = config.TRADE_MODE.upper()
    mode_emoji = {"SAFE": "🛡️", "NORMAL": "⚖️", "AGGRESSIVE": "🔥"}.get(mode, "⚙️")
    st.markdown(f"### {mode_emoji} Trade Mode: **{mode}**")
    st.markdown("*Change in `.env` → `TRADE_MODE=safe|normal|aggressive` → restart bot*")
    st.markdown("")

    st.markdown("#### Trade Parameters")
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

    st.markdown("#### Risk-First Gate (v2.0)")
    rcfg1, rcfg2, rcfg3, rcfg4 = st.columns(4)
    with rcfg1:
        st.markdown(f"**Kelly Safety:** {config.KELLY_SAFETY_MULTIPLIER}x (half-Kelly)")
        st.markdown(f"**Drawdown Halt:** {config.MAX_DRAWDOWN_HALT_PCT*100:.0f}%")
    with rcfg2:
        st.markdown(f"**Min Edges:** {config.MIN_EDGES_REQUIRED}/3")
        st.markdown(f"**Volatility ATR:** {config.VOLATILITY_ATR_MULTIPLIER}x")
    with rcfg3:
        st.markdown(f"**Trail Activation:** {config.TRAILING_STOP_ACTIVATION_PCT}%")
        st.markdown(f"**Trail Distance:** {config.TRAILING_STOP_DISTANCE_PCT}% / {config.PENNY_TRAILING_STOP_DISTANCE_PCT}%")
    with rcfg4:
        st.markdown(f"**Circuit Breaker:** SPY {config.CIRCUIT_BREAKER_SPY_DROP_PCT}%")
        st.markdown(f"**Earnings Exit:** {config.EARNINGS_EXIT_DAYS}d ({config.EARNINGS_EXIT_MODE})")

    st.markdown("#### Exit Management")
    ecfg1, ecfg2, ecfg3 = st.columns(3)
    with ecfg1:
        st.markdown(f"**Exit Check:** every {config.EXIT_CHECK_INTERVAL_MINUTES} min")
        st.markdown(f"**Time Stop:** {config.TIME_STOP_DAYS} days")
    with ecfg2:
        st.markdown(f"**Scale-Out:** {'Enabled' if config.SCALE_OUT_ENABLED else 'Disabled'}")
        st.markdown(f"**Scale Levels:** {', '.join(str(l) + 'R' for l in config.SCALE_OUT_LEVELS)}")
    with ecfg3:
        st.markdown(f"**Penny Limit Slip:** {config.PENNY_LIMIT_SLIPPAGE_PCT}%")
        st.markdown(f"**Max Slippage:** {config.MAX_SLIPPAGE_PCT}%")

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
# ALERT HISTORY FEED
# ──────────────────────────────────────────────

with st.expander("Alert History (Recent Notifications)"):
    # Read from notification rate-limit cache (in-memory, shows current session only)
    try:
        from utils.notifications import _last_sent
        if _last_sent:
            _alert_rows = []
            for event_type, ts in sorted(_last_sent.items(), key=lambda x: x[1], reverse=True):
                _alert_rows.append({
                    "Event": event_type,
                    "Time": dt.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"),
                })
            st.dataframe(pd.DataFrame(_alert_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No notifications sent this session")
    except Exception:
        st.info("Notification module not loaded")

    # Also scan recent log for key events
    _alert_keywords = ["ORDER EXECUTED", "EXIT —", "PARTIAL EXIT", "STRATEGY PAUSED",
                        "STRATEGY RESUMED", "Circuit breaker", "Daily loss limit"]
    if os.path.exists(log_path):
        try:
            with open(log_path, "rb") as _f:
                _f.seek(0, 2)
                _sz = _f.tell()
                _read = min(_sz, 100000)
                _f.seek(max(0, _sz - _read))
                _log_lines = _f.read().decode("utf-8", errors="ignore").splitlines()

            _event_lines = []
            for _line in reversed(_log_lines):
                if any(kw in _line for kw in _alert_keywords):
                    _event_lines.append(_line)
                    if len(_event_lines) >= 20:
                        break

            if _event_lines:
                st.markdown("**Recent Log Events:**")
                for _el in _event_lines:
                    _ts_part = _el[:19] if len(_el) > 19 else ""
                    _msg_part = _el[20:] if len(_el) > 20 else _el
                    if "EXECUTED" in _el:
                        st.markdown(f"<span style='color:#e040fb;font-size:12px;font-family:monospace'>{_ts_part} {_msg_part}</span>", unsafe_allow_html=True)
                    elif "EXIT" in _el:
                        st.markdown(f"<span style='color:#ff9800;font-size:12px;font-family:monospace'>{_ts_part} {_msg_part}</span>", unsafe_allow_html=True)
                    elif "PAUSED" in _el or "Circuit" in _el or "loss limit" in _el:
                        st.markdown(f"<span style='color:#f44336;font-size:12px;font-family:monospace'>{_ts_part} {_msg_part}</span>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<span style='color:#8892b0;font-size:12px;font-family:monospace'>{_ts_part} {_msg_part}</span>", unsafe_allow_html=True)
        except Exception:
            pass

# Footer
st.divider()
st.caption("DeepThinkTrader v3.0 — Paper Trading Mode | Risk-First Framework + Claude AI Analysis")

# Auto-refresh using st.fragment for non-blocking periodic rerun
if auto_refresh:
    @st.fragment(run_every=refresh_interval)
    def _auto_refresh():
        st.cache_data.clear()
    _auto_refresh()
