"""Shared theme tokens for DeepThinkTrader dashboard + charts.

Single source of truth — pages import CHART_COLORS, CHART_LAYOUT, and THEME_CSS
here instead of defining their own. Palette matches the brand (mark/banner).
"""

from __future__ import annotations

# ── Brand palette ─────────────────────────────────────────────────
# Apple iOS 26 "Liquid Glass" direction: vivid indigo → teal → emerald gradient
# behind translucent frosted surfaces. Brighter accent greens/reds so P&L pops
# through the glass, deeper base canvas so the gradient reads.
BRAND = {
    "bg": "#060912",         # canvas — deep near-black with cool tint
    "bg_raised": "rgba(24, 30, 48, 0.55)",   # translucent frosted card
    "bg_hilite": "rgba(32, 44, 72, 0.7)",    # hover / selection (still glassy)
    "stroke": "rgba(142, 175, 255, 0.14)",   # borders — soft glass edge
    "dim": "#8A94A8",        # muted labels, slightly cooler
    "text": "#ECF2FA",       # primary copy, high contrast on glass
    "green": "#00F5A0",      # up moves — neon emerald
    "green_deep": "rgba(0, 80, 48, 0.35)",   # green card, translucent
    "green_edge": "rgba(0, 245, 160, 0.4)",  # green edge glow
    "red": "#FF4D6D",        # down moves — vivid rose
    "red_deep": "rgba(60, 16, 32, 0.4)",
    "red_edge": "rgba(255, 77, 109, 0.4)",
    "amber": "#FFD447",
    "amber_deep": "rgba(58, 44, 16, 0.4)",
    "amber_edge": "rgba(255, 212, 71, 0.35)",
    "blue": "#4E8CFF",       # secondary accent
    # New glass-era accents for chart colorway + backgrounds
    "indigo": "#6366F1",     # gradient start
    "teal": "#2DD4BF",       # gradient middle
    "emerald": "#10E08A",    # gradient end
    "violet": "#A78BFA",     # 4th colorway
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
    # Fully transparent bg so the dashboard's frosted-glass cards show through
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Inter', system-ui, sans-serif",
              color=BRAND["text"], size=12),
    # Gridlines: very soft, matches glass edge tone
    xaxis=dict(gridcolor="rgba(142, 175, 255, 0.08)",
               zerolinecolor="rgba(142, 175, 255, 0.16)"),
    yaxis=dict(gridcolor="rgba(142, 175, 255, 0.08)",
               zerolinecolor="rgba(142, 175, 255, 0.16)"),
    margin=dict(l=0, r=0, t=30, b=0),
    # Colorway matches the new indigo→teal→emerald gradient palette
    colorway=[BRAND["emerald"], BRAND["teal"], BRAND["indigo"],
              BRAND["violet"], BRAND["amber"], BRAND["red"]],
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
    --indigo: {BRAND["indigo"]};
    --teal: {BRAND["teal"]};
    --emerald: {BRAND["emerald"]};
}}

/* Vivid gradient canvas behind the entire app — the frosted cards
   refract this, giving the Liquid Glass feel. Two diffuse radial blobs
   plus a subtle linear wash. Fixed attachment so scrolling doesn't move it. */
html, body, .stApp, [data-testid="stAppViewContainer"] {{
    background:
        radial-gradient(1200px 800px at 15% 10%, rgba(99, 102, 241, 0.32), transparent 55%),
        radial-gradient(1000px 700px at 85% 90%, rgba(16, 224, 138, 0.22), transparent 60%),
        radial-gradient(900px 600px at 50% 50%, rgba(45, 212, 191, 0.18), transparent 65%),
        linear-gradient(180deg, #060912 0%, #0B0E1A 100%) !important;
    background-attachment: fixed !important;
}}

/* Liquid-glass card: translucent fill + heavy backdrop blur + soft edge + inner highlight */
.kpi-card {{
    background: {BRAND["bg_raised"]};
    border: 1px solid {BRAND["stroke"]};
    border-radius: 16px;
    padding: 20px 16px 16px;
    margin-bottom: 12px;
    backdrop-filter: blur(24px) saturate(160%);
    -webkit-backdrop-filter: blur(24px) saturate(160%);
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.06),
        0 8px 24px rgba(0, 0, 0, 0.35);
}}
.kpi-card-green {{
    background: {BRAND["green_deep"]};
    border: 1px solid {BRAND["green_edge"]};
    border-radius: 16px;
    padding: 20px 16px 16px;
    margin-bottom: 12px;
    backdrop-filter: blur(24px) saturate(160%);
    -webkit-backdrop-filter: blur(24px) saturate(160%);
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.08),
        0 8px 24px rgba(0, 0, 0, 0.35),
        0 0 32px rgba(0, 245, 160, 0.08);
}}
.kpi-card-red {{
    background: {BRAND["red_deep"]};
    border: 1px solid {BRAND["red_edge"]};
    border-radius: 16px;
    padding: 20px 16px 16px;
    margin-bottom: 12px;
    backdrop-filter: blur(24px) saturate(160%);
    -webkit-backdrop-filter: blur(24px) saturate(160%);
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.08),
        0 8px 24px rgba(0, 0, 0, 0.35),
        0 0 32px rgba(255, 77, 109, 0.08);
}}
.kpi-card-amber {{
    background: {BRAND["amber_deep"]};
    border: 1px solid {BRAND["amber_edge"]};
    border-radius: 16px;
    padding: 20px 16px 16px;
    margin-bottom: 12px;
    backdrop-filter: blur(24px) saturate(160%);
    -webkit-backdrop-filter: blur(24px) saturate(160%);
    box-shadow:
        inset 0 1px 0 rgba(255, 255, 255, 0.08),
        0 8px 24px rgba(0, 0, 0, 0.35),
        0 0 32px rgba(255, 212, 71, 0.06);
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

/* Glass-era buttons: translucent with gradient glow on primary */
button[kind="primary"] {{
    background: linear-gradient(135deg, {BRAND["indigo"]} 0%, {BRAND["teal"]} 50%, {BRAND["emerald"]} 100%) !important;
    color: #0A1020 !important;
    border: 0 !important;
    font-weight: 700 !important;
    box-shadow: 0 4px 16px rgba(16, 224, 138, 0.25) !important;
}}
button[kind="primary"]:hover {{
    filter: brightness(1.08) !important;
    box-shadow: 0 6px 24px rgba(16, 224, 138, 0.4) !important;
}}
button[kind="secondary"] {{
    background: rgba(142, 175, 255, 0.06) !important;
    border: 1px solid rgba(142, 175, 255, 0.18) !important;
    backdrop-filter: blur(12px) !important;
    -webkit-backdrop-filter: blur(12px) !important;
}}
button[kind="secondary"]:hover {{
    border-color: {BRAND["emerald"]} !important;
    color: {BRAND["emerald"]} !important;
}}

/* Sidebar + expanders inherit the glass feel */
[data-testid="stSidebar"] > div:first-child {{
    background: rgba(10, 14, 26, 0.55) !important;
    backdrop-filter: blur(32px) saturate(160%) !important;
    -webkit-backdrop-filter: blur(32px) saturate(160%) !important;
    border-right: 1px solid {BRAND["stroke"]} !important;
}}

/* Sidebar nav labels: capitalize so 'dashboard' renders as 'Dashboard' without
   renaming the entrypoint file (Dockerfile / compose / launchd still run dashboard.py). */
[data-testid="stSidebarNav"] a span,
[data-testid="stSidebarNavLink"] span {{
    text-transform: capitalize !important;
}}

/* Dataframes + tables: translucent panel with blurred backdrop */
[data-testid="stDataFrame"], [data-testid="stTable"] {{
    background: rgba(24, 30, 48, 0.45) !important;
    border: 1px solid {BRAND["stroke"]} !important;
    border-radius: 14px !important;
    backdrop-filter: blur(20px) saturate(160%) !important;
    -webkit-backdrop-filter: blur(20px) saturate(160%) !important;
    overflow: hidden;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 6px 20px rgba(0,0,0,0.3);
}}
[data-testid="stDataFrame"] div[role="grid"],
[data-testid="stDataFrame"] div[role="row"],
[data-testid="stDataFrame"] div[role="columnheader"],
[data-testid="stDataFrame"] div[role="cell"] {{
    background: transparent !important;
    color: {BRAND["text"]} !important;
}}
[data-testid="stDataFrame"] div[role="columnheader"] {{
    border-bottom: 1px solid {BRAND["stroke"]} !important;
    color: {BRAND["dim"]} !important;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    font-size: 11px;
}}
[data-testid="stTable"] table {{ background: transparent !important; color: {BRAND["text"]} !important; }}
[data-testid="stTable"] th {{ color: {BRAND["dim"]} !important; border-bottom: 1px solid {BRAND["stroke"]} !important; }}
[data-testid="stTable"] td {{ border-bottom: 1px solid rgba(142,175,255,0.06) !important; }}

/* Inputs: frosted glass to match cards */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea,
[data-testid="stSelectbox"] div[data-baseweb="select"] > div,
[data-testid="stMultiSelect"] div[data-baseweb="select"] > div {{
    background: rgba(142, 175, 255, 0.06) !important;
    border: 1px solid {BRAND["stroke"]} !important;
    color: {BRAND["text"]} !important;
    backdrop-filter: blur(12px) !important;
    -webkit-backdrop-filter: blur(12px) !important;
}}

/* Any image rendered by Streamlit gets a subtle glass frame — keeps banners
   and hero PNGs from looking like stickers pasted on the gradient */
[data-testid="stImage"] img {{
    border-radius: 16px;
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.35),
                inset 0 1px 0 rgba(255, 255, 255, 0.04);
}}

/* Plotly charts: put them on a frosted panel so gridlines + colorway pop */
[data-testid="stPlotlyChart"] {{
    background: rgba(24, 30, 48, 0.35) !important;
    border: 1px solid {BRAND["stroke"]} !important;
    border-radius: 16px !important;
    padding: 8px 4px !important;
    backdrop-filter: blur(20px) saturate(160%) !important;
    -webkit-backdrop-filter: blur(20px) saturate(160%) !important;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.05), 0 8px 24px rgba(0,0,0,0.3);
}}
</style>"""


def apply_theme() -> None:
    """Inject THEME_CSS into the current Streamlit page."""
    import streamlit as st
    st.markdown(THEME_CSS, unsafe_allow_html=True)
