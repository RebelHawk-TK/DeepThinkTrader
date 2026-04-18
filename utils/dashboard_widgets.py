"""Dashboard widgets — focused helpers for the redesigned top-of-page.

Three functions:
- `render_status_banner`  — one-line health/market/regime/alerts strip
- `render_kpi_row`        — five headline metrics
- `render_risk_memory`    — Kelly state, CVaR, top correlation, recent lessons

Kept in its own module so dashboard.py doesn't grow by another 300 LOC.
All functions are pure renderers (Streamlit side-effects only); they don't
mutate config or DB.
"""
from __future__ import annotations

from typing import Iterable

import streamlit as st


# ─────────────────────────── Status banner ──────────────────────────────


def render_status_banner(
    *,
    bot_status: str,              # "ok" | "warning" | "down"
    bot_detail: str,              # "last heartbeat 42s ago" etc.
    market_state: str,            # "OPEN — closes 4h 23m" | "CLOSED — opens 14h 12m"
    market_is_open: bool,
    regime_label: str,            # "low" | "normal" | "high" | "unknown"
    regime_vol_pct: float,        # e.g. 15.3
    recommended_mode: str,        # "aggressive" | "normal" | "safe"
    current_mode: str,            # user's configured mode
    alerts: list[str],            # e.g. ["SPY circuit breaker", "penny portfolio paused"]
) -> None:
    """Render the single-line top banner."""
    bot_dot = {"ok": "🟢", "warning": "🟡", "down": "🔴"}.get(bot_status, "⚪")
    market_dot = "🟢" if market_is_open else "⚫"
    regime_color = {"low": "🟢", "normal": "🟢", "high": "🔴", "unknown": "⚪"}.get(regime_label, "⚪")
    mode_mismatch = (
        regime_label != "unknown"
        and recommended_mode != current_mode
    )
    mode_suffix = f" ⚠️ recommend {recommended_mode}" if mode_mismatch else ""
    alert_badge = f" • 🟠 {len(alerts)} alert{'s' if len(alerts) != 1 else ''}" if alerts else ""

    banner = (
        f"{bot_dot} Bot {bot_status.upper()} ({bot_detail}) │ "
        f"{market_dot} Market {market_state} │ "
        f"{regime_color} Regime {regime_label.upper()} ({regime_vol_pct:.1f}% vol){mode_suffix}"
        f"{alert_badge}"
    )
    st.markdown(
        f"""<div style='
            background: rgba(255,255,255,0.04);
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 8px;
            padding: 10px 16px;
            margin-bottom: 12px;
            font-size: 13px;
            font-weight: 500;
            letter-spacing: 0.2px;
        '>{banner}</div>""",
        unsafe_allow_html=True,
    )
    if alerts:
        with st.expander(f"Alerts ({len(alerts)})", expanded=False):
            for a in alerts:
                st.markdown(f"- {a}")


# ─────────────────────────── KPI row (5 metrics) ────────────────────────


def render_kpi_row(
    *,
    equity: float,
    today_pnl: float,
    today_pnl_pct: float,
    thirty_day_pnl: float,
    thirty_day_pnl_pct: float,
    open_positions_count: int,
    total_exposure_pct: float,
    drawdown_from_peak_pct: float,
    drawdown_halt_pct: float,
) -> None:
    """Five headline numbers — the 'where do I stand right now?' row."""
    cols = st.columns(5)
    cols[0].metric(
        "Equity",
        f"${equity:,.0f}",
        delta=f"{today_pnl_pct:+.2f}% today",
        delta_color="normal" if today_pnl >= 0 else "inverse",
    )
    cols[1].metric(
        "Today",
        f"${today_pnl:+,.0f}",
        delta=f"{today_pnl_pct:+.2f}%",
        delta_color="normal" if today_pnl >= 0 else "inverse",
    )
    cols[2].metric(
        "30-day",
        f"${thirty_day_pnl:+,.0f}",
        delta=f"{thirty_day_pnl_pct:+.2f}%",
        delta_color="normal" if thirty_day_pnl >= 0 else "inverse",
    )
    cols[3].metric(
        "Open positions",
        open_positions_count,
        delta=f"{total_exposure_pct:.1f}% exposure",
        delta_color="off",
    )
    # Drawdown goes red as it approaches the halt threshold.
    dd_ratio = drawdown_from_peak_pct / max(drawdown_halt_pct, 0.01)
    if dd_ratio >= 0.9:
        dd_label = f"-{drawdown_from_peak_pct:.1f}%"
        dd_delta = f"⚠️ near {drawdown_halt_pct:.1f}% halt"
    elif dd_ratio >= 0.5:
        dd_label = f"-{drawdown_from_peak_pct:.1f}%"
        dd_delta = f"halt @ -{drawdown_halt_pct:.1f}%"
    else:
        dd_label = f"-{drawdown_from_peak_pct:.1f}%"
        dd_delta = "well clear"
    cols[4].metric("Drawdown", dd_label, delta=dd_delta, delta_color="off")


# ─────────────────────────── Risk & Memory row ──────────────────────────


def render_risk_memory(
    *,
    kelly_fraction: float | None,
    kelly_n_trades: int,
    kelly_win_rate: float | None,
    portfolio_cvar_pct: float | None,
    cvar_limit_pct: float,
    top_correlation: tuple[str, str, float] | None,   # (ticker_a, ticker_b, corr) or None
    recent_reflections: Iterable[dict],
) -> None:
    """Single row surfacing Sprint 5 signals that otherwise live only in logs."""
    st.markdown('<div class="section-header">Risk & Memory</div>', unsafe_allow_html=True)

    risk_cols = st.columns(3)
    # Kelly
    if kelly_fraction is not None and kelly_n_trades >= 20:
        wr_note = f"{kelly_win_rate * 100:.0f}% win" if kelly_win_rate is not None else ""
        risk_cols[0].metric(
            "Kelly risk/trade",
            f"{kelly_fraction * 100:.2f}%",
            delta=f"N={kelly_n_trades} trades • {wr_note}",
            delta_color="off",
        )
    else:
        risk_cols[0].metric(
            "Kelly risk/trade",
            "fixed 1%",
            delta=f"N={kelly_n_trades} — need ≥20 for Kelly",
            delta_color="off",
        )

    # CVaR
    if portfolio_cvar_pct is not None:
        breach = portfolio_cvar_pct > cvar_limit_pct
        risk_cols[1].metric(
            "Portfolio 5%-CVaR",
            f"-{portfolio_cvar_pct * 100:.2f}%",
            delta=(
                f"⚠️ above {cvar_limit_pct * 100:.1f}% limit" if breach
                else f"limit -{cvar_limit_pct * 100:.1f}%"
            ),
            delta_color="inverse" if breach else "off",
        )
    else:
        risk_cols[1].metric(
            "Portfolio 5%-CVaR",
            "—",
            delta="insufficient history",
            delta_color="off",
        )

    # Top correlation
    if top_correlation is not None:
        a, b, corr = top_correlation
        flag = "⚠️ " if corr > 0.6 else ""
        risk_cols[2].metric(
            "Top correlation",
            f"{flag}{a} ↔ {b}",
            delta=f"ρ = {corr:+.2f}",
            delta_color="inverse" if corr > 0.6 else "off",
        )
    else:
        risk_cols[2].metric(
            "Top correlation",
            "—",
            delta="<2 positions held",
            delta_color="off",
        )

    # Reflection cards — small text, not metrics, because they're narrative.
    reflections = list(recent_reflections)
    if reflections:
        st.markdown(
            "<div style='color: rgba(255,255,255,0.6); font-size: 12px; "
            "margin-top: 8px; margin-bottom: 4px;'>Recent lessons</div>",
            unsafe_allow_html=True,
        )
        ref_cols = st.columns(min(3, len(reflections)))
        for col, r in zip(ref_cols, reflections[:3]):
            date = (r.get("created_at") or "")[:10]
            ticker = r.get("ticker", "?")
            label = r.get("outcome_label", "")
            lesson = (r.get("lesson") or "").strip()
            if len(lesson) > 180:
                lesson = lesson[:177] + "…"
            color_tag = {"win": "🟢", "loss": "🔴", "flat": "⚪"}.get(label, "⚪")
            col.markdown(
                f"""<div style='
                    background: rgba(255,255,255,0.03);
                    border: 1px solid rgba(255,255,255,0.08);
                    border-radius: 6px;
                    padding: 10px 12px;
                    font-size: 12px;
                    line-height: 1.4;
                    height: 100%;
                '>
                    <div style='color: rgba(255,255,255,0.5); font-size: 11px; margin-bottom: 4px;'>
                        {color_tag} {date} · {ticker}
                    </div>
                    {lesson}
                </div>""",
                unsafe_allow_html=True,
            )
