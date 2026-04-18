"""Shared theme tokens for DeepThinkTrader dashboard + charts.

Single source of truth — pages import CHART_COLORS, CHART_LAYOUT, and THEME_CSS
here instead of defining their own. Palette matches the brand (mark/banner).
"""

from __future__ import annotations

# ── Brand palette ─────────────────────────────────────────────────
BRAND = {
    "bg": "#0B0E14",         # canvas — near-black
    "bg_raised": "#161C28",  # cards / raised surfaces
    "bg_hilite": "#1E2736",  # hover / selection
    "stroke": "#2A3446",     # borders / dividers
    "dim": "#7D8590",        # muted labels
    "text": "#E6EDF3",       # primary copy
    "green": "#00D084",      # up moves, positive
    "green_deep": "#003E22", # green card background
    "green_edge": "#1A5A3A", # green card border
    "red": "#FF4C4C",        # down moves, negative
    "red_deep": "#3B1818",   # red card background
    "red_edge": "#5A2828",   # red card border
    "amber": "#FFCC3D",      # attention / warnings
    "amber_deep": "#3A2E10",
    "amber_edge": "#5E4812",
    "blue": "#5E9EFF",       # secondary accent (non-P&L charts)
}


# ── Plotly palette + layout ───────────────────────────────────────
CHART_COLORS = {
    "primary": BRAND["green"],
    "secondary": BRAND["blue"],
    "positive": BRAND["green"],
    "negative": BRAND["red"],
    "neutral": BRAND["dim"],
    "accent": BRAND["amber"],
    "bg": BRAND["bg"],
    "grid": BRAND["stroke"],
    "text": BRAND["text"],
}

CHART_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor=BRAND["bg"],
    font=dict(family="'SF Mono', 'JetBrains Mono', 'Fira Code', monospace",
              color=BRAND["text"], size=12),
    xaxis=dict(gridcolor=BRAND["stroke"], zerolinecolor=BRAND["stroke"]),
    yaxis=dict(gridcolor=BRAND["stroke"], zerolinecolor=BRAND["stroke"]),
    margin=dict(l=0, r=0, t=30, b=0),
    colorway=[BRAND["green"], BRAND["blue"], BRAND["amber"],
              BRAND["red"], "#9B8AFF", "#00C4B4"],
)


# ── Global CSS ────────────────────────────────────────────────────
# Uses brand tokens; keep class names used elsewhere (kpi-card*, section-header,
# status-banner, status-active/paused) so no page code has to change.

THEME_CSS = f"""<style>
:root {{
    --bg: {BRAND["bg"]};
    --bg-raised: {BRAND["bg_raised"]};
    --stroke: {BRAND["stroke"]};
    --dim: {BRAND["dim"]};
    --text: {BRAND["text"]};
    --green: {BRAND["green"]};
    --red: {BRAND["red"]};
    --amber: {BRAND["amber"]};
}}

.kpi-card {{
    background: linear-gradient(135deg, {BRAND["bg_raised"]} 0%, {BRAND["bg"]} 100%);
    border: 1px solid {BRAND["stroke"]};
    border-radius: 12px;
    padding: 20px 16px 16px;
    margin-bottom: 12px;
}}
.kpi-card-green {{
    background: linear-gradient(135deg, {BRAND["green_deep"]} 0%, #00211A 100%);
    border: 1px solid {BRAND["green_edge"]};
    border-radius: 12px;
    padding: 20px 16px 16px;
    margin-bottom: 12px;
}}
.kpi-card-red {{
    background: linear-gradient(135deg, {BRAND["red_deep"]} 0%, #2B0E0E 100%);
    border: 1px solid {BRAND["red_edge"]};
    border-radius: 12px;
    padding: 20px 16px 16px;
    margin-bottom: 12px;
}}
.kpi-card-amber {{
    background: linear-gradient(135deg, {BRAND["amber_deep"]} 0%, #1F1806 100%);
    border: 1px solid {BRAND["amber_edge"]};
    border-radius: 12px;
    padding: 20px 16px 16px;
    margin-bottom: 12px;
}}

.section-header {{
    font-size: 1.1rem;
    font-weight: 700;
    color: {BRAND["dim"]};
    text-transform: uppercase;
    letter-spacing: 1.5px;
    margin: 24px 0 12px;
    padding-bottom: 8px;
    border-bottom: 2px solid {BRAND["stroke"]};
}}

.status-banner {{
    padding: 10px 20px;
    border-radius: 8px;
    font-weight: 600;
    font-size: 14px;
    text-align: center;
    margin-bottom: 16px;
}}
.status-active {{
    background: {BRAND["green_deep"]};
    border: 1px solid {BRAND["green_edge"]};
    color: {BRAND["green"]};
}}
.status-paused {{
    background: {BRAND["red_deep"]};
    border: 1px solid {BRAND["red_edge"]};
    color: {BRAND["red"]};
}}

[data-testid="stMetric"] {{ overflow: hidden; }}
[data-testid="stMetricValue"] {{
    font-size: clamp(1rem, 2.2vw, 1.8rem);
    white-space: nowrap;
    font-weight: 700;
}}
[data-testid="stMetricLabel"] {{
    font-size: clamp(0.65rem, 1.2vw, 0.85rem);
    color: {BRAND["dim"]} !important;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}
[data-testid="stMetricDelta"] {{ font-size: clamp(0.6rem, 1vw, 0.8rem); }}

h1 {{ font-size: clamp(1.4rem, 3vw, 2.2rem) !important; color: {BRAND["text"]}; }}
h2, h3 {{ color: {BRAND["text"]} !important; }}
hr {{ border-color: {BRAND["stroke"]} !important; margin: 20px 0 !important; }}

[data-testid="stExpander"] {{
    border: 1px solid {BRAND["stroke"]};
    border-radius: 8px;
    margin-bottom: 8px;
}}

/* Streamlit default button — subtle brand accent on hover */
button[kind="primary"] {{
    background: {BRAND["green"]} !important;
    color: {BRAND["bg"]} !important;
    border: 0 !important;
}}
button[kind="secondary"]:hover {{
    border-color: {BRAND["green"]} !important;
    color: {BRAND["green"]} !important;
}}
</style>"""


def apply_theme() -> None:
    """Inject THEME_CSS into the current Streamlit page."""
    import streamlit as st
    st.markdown(THEME_CSS, unsafe_allow_html=True)
