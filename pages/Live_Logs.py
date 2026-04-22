"""Live log viewer for DeepThinkTrader."""

from __future__ import annotations

import os
import re
from datetime import datetime

import streamlit as st

from utils.brand import ICON_PATH as _ICON
from utils.theme import apply_theme
from utils.streamlit_auth import require_auth
st.set_page_config(page_title="DeepThinkTrader — Live Logs", page_icon=_ICON, layout="wide")
apply_theme()
require_auth()

LOG_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_FILES = {
    "Bot": os.path.join(LOG_DIR, "deepthinktrader.log"),
    "Dashboard": os.path.join(LOG_DIR, "dashboard.log"),
}

# ── Styling ────────────────────────────────────────────────
st.markdown("""<style>
.log-line { font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace; font-size: 12px; line-height: 1.5; }
.log-info { color: #8bc34a; }
.log-warn { color: #ff9800; }
.log-error { color: #f44336; font-weight: bold; }
.log-debug { color: #9e9e9e; }
.log-trade { color: #e040fb; font-weight: bold; }
.log-claude { color: #00bcd4; }
.log-warmup { color: #ffeb3b; }
.log-block { color: #ff5722; }
.log-container {
    background: rgba(24, 30, 48, 0.55);
    border: 1px solid rgba(142, 175, 255, 0.14);
    border-radius: 16px;
    padding: 16px;
    max-height: 700px;
    overflow-y: auto;
    backdrop-filter: blur(24px) saturate(160%);
    -webkit-backdrop-filter: blur(24px) saturate(160%);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.06), 0 8px 24px rgba(0,0,0,0.35);
}
</style>""", unsafe_allow_html=True)

st.title("Live Logs")

# ── Controls ───────────────────────────────────────────────
col1, col2, col3, col4 = st.columns([2, 2, 2, 2])

with col1:
    log_source = st.selectbox("Log Source", list(LOG_FILES.keys()), index=0)

with col2:
    num_lines = st.select_slider("Lines", options=[50, 100, 200, 500, 1000], value=200)

with col3:
    filter_level = st.selectbox("Level", ["All", "INFO", "WARNING", "ERROR", "Trades Only", "Claude Only", "Warmup"])

with col4:
    search = st.text_input("Search", placeholder="ticker, keyword...")


def colorize_line(line: str) -> str:
    """Apply color classes to log lines based on content."""
    css_class = "log-info"

    if "[ERROR]" in line:
        css_class = "log-error"
    elif "[WARNING]" in line:
        css_class = "log-warn"
    elif "[DEBUG]" in line:
        css_class = "log-debug"
    elif any(kw in line for kw in ["ORDER EXECUTED", "TRADE SUMMARY", "EXIT —", "PARTIAL EXIT"]):
        css_class = "log-trade"
    elif any(kw in line for kw in ["Claude Analyst", "Claude adjusted", "CLAUDE OVERRIDE"]):
        css_class = "log-claude"
    elif "WARMUP" in line:
        css_class = "log-warmup"
    elif any(kw in line for kw in ["BLOCKED", "CIRCUIT BREAKER", "SPREAD CHECK", "SECTOR CONCENTRATION"]):
        css_class = "log-block"

    # Escape HTML
    safe = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f'<div class="log-line {css_class}">{safe}</div>'


def _fetch_cloud_logs(service_name: str, n: int) -> list[str]:
    """Fetch last N log entries from Cloud Logging for a Cloud Run service.

    Used as a fallback when the on-disk file isn't present (production runs
    on Cloud Run, which writes to stdout and is captured by Cloud Logging,
    not to a local file).
    """
    try:
        from google.cloud import logging as gcl
    except ImportError:
        return [
            "google-cloud-logging not installed. Install: pip install google-cloud-logging",
        ]
    try:
        client = gcl.Client()
        filter_str = (
            'resource.type="cloud_run_revision" '
            f'AND resource.labels.service_name="{service_name}"'
        )
        entries = list(client.list_entries(
            filter_=filter_str,
            order_by=gcl.DESCENDING,
            page_size=n,
            max_results=n,
        ))
        entries.reverse()  # oldest first so the viewer reads naturally
        out: list[str] = []
        for e in entries:
            ts = e.timestamp.strftime("%Y-%m-%d %H:%M:%S") if e.timestamp else ""
            payload = e.payload
            if isinstance(payload, dict):
                msg = payload.get("message", str(payload))
            else:
                msg = str(payload) if payload is not None else ""
            severity = (e.severity or "INFO").ljust(7)
            out.append(f"{ts} [{severity}] {msg}".rstrip())
        return out or ["(no recent Cloud Logging entries)"]
    except Exception as exc:
        return [f"Cloud Logging fetch failed: {exc}"]


def read_log_tail(filepath: str, n: int) -> list[str]:
    """Read last N lines of a log file efficiently.

    Falls back to Cloud Logging for the matching Cloud Run service when the
    on-disk file isn't present (production deploy).
    """
    if not os.path.exists(filepath):
        service = "trader-bot" if filepath.endswith("deepthinktrader.log") else "trader-dashboard"
        return _fetch_cloud_logs(service, n)
    try:
        with open(filepath, "rb") as f:
            # Seek from end to find last N newlines
            f.seek(0, 2)
            size = f.tell()
            if size == 0:
                return ["(empty log)"]

            # Read chunks from the end
            lines = []
            chunk_size = min(8192, size)
            pos = size

            while len(lines) <= n and pos > 0:
                read_size = min(chunk_size, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size).decode("utf-8", errors="replace")
                lines = chunk.splitlines() + lines

            return lines[-n:]
    except Exception as e:
        return [f"Error reading log: {e}"]


def filter_lines(lines: list[str], level: str, search_term: str) -> list[str]:
    """Filter log lines by level and search term."""
    filtered = lines

    if level == "INFO":
        filtered = [l for l in filtered if "[INFO]" in l]
    elif level == "WARNING":
        filtered = [l for l in filtered if "[WARNING]" in l]
    elif level == "ERROR":
        filtered = [l for l in filtered if "[ERROR]" in l]
    elif level == "Trades Only":
        filtered = [l for l in filtered if any(kw in l for kw in [
            "ORDER EXECUTED", "TRADE SUMMARY", "EXIT —", "PARTIAL EXIT",
            "TRADE BLOCKED", "HOLD signal", "Result for",
        ])]
    elif level == "Claude Only":
        filtered = [l for l in filtered if any(kw in l for kw in [
            "Claude Analyst", "Claude adjusted", "CLAUDE OVERRIDE",
            "qualitative_assessment", "conviction_adjustment",
        ])]
    elif level == "Warmup":
        filtered = [l for l in filtered if "WARMUP" in l or "warmup" in l]

    if search_term:
        term = search_term.upper()
        filtered = [l for l in filtered if term in l.upper()]

    return filtered


# ── Deduplicate consecutive identical lines ────────────────
def deduplicate(lines: list[str]) -> list[str]:
    """Remove consecutive duplicate lines (launchd double-logging)."""
    if not lines:
        return lines
    result = [lines[0]]
    for line in lines[1:]:
        if line != result[-1]:
            result.append(line)
    return result


# ── Read and display ───────────────────────────────────────
log_path = LOG_FILES[log_source]
raw_lines = read_log_tail(log_path, num_lines * 2)  # read extra for dedup
deduped = deduplicate(raw_lines)
filtered = filter_lines(deduped, filter_level, search)
display_lines = filtered[-num_lines:]

# Stats bar
scol1, scol2, scol3, scol4 = st.columns(4)
scol1.metric("Lines shown", len(display_lines))
scol2.metric("Total (deduped)", len(deduped))

# Count key events in visible lines
trades = sum(1 for l in display_lines if "ORDER EXECUTED" in l)
blocks = sum(1 for l in display_lines if "BLOCKED" in l)
scol3.metric("Trades", trades)
scol4.metric("Blocked", blocks)

st.markdown("---")

# Render log
html_lines = [colorize_line(line) for line in display_lines]
log_html = "\n".join(html_lines)

st.markdown(f'<div class="log-container">{log_html}</div>', unsafe_allow_html=True)

# Auto-refresh
@st.fragment(run_every=5)
def _auto_refresh():
    pass
_auto_refresh()
