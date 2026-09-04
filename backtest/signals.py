"""Centralized entry signal definitions (single source of truth).

Used by:
- Live path: agents/deepthink_agent.py (report dicts from ResearchAgent)
- Harness / backtest: backtest/signal_search.py and overlay_search.py (via Cand or report replay)

All predicate logic lives here. Changes must be validated through the harness
(bootstrap + per-third consistency) before any forward-test impact.

The two currently deployed MAIN sleeves (momentum_breakout, relative_strength)
were the only liquid-universe candidates that cleared the 2026-06-25 bootstrap gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict

# --- Dataclass used by the backtest harness (kept here for self-containment) ---
@dataclass
class Cand:
    ticker: str
    ts: Any
    price: float
    atr: float
    daily_chg: float
    vol_ratio: float
    rsi: float
    above10: bool
    above20: bool
    high30: float
    low30: float
    trend1h: str
    rsi1h: float
    news: float
    reddit: float
    catalyst: float
    sa_sent: float
    sa_bull: int
    sa_bear: int
    opt_bull: bool
    opt_strength: float
    pcr: float
    rev_growth: float
    d2e: float
    margin: float
    vix: float
    breadth: float


def _f(x: Any, d: float = 0.0) -> float:
    """Safe float coercion (matches both live _f helpers and load_candidates)."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


# =============================================================================
# REPORT-BASED (live DeepThinkAgent path)
# Exact replicas of the methods previously defined in deepthink_agent.py
# so that live decisions == harness replay on the same research_reports JSON.
# =============================================================================

def momentum_breakout(report: dict) -> bool:
    """MAIN entry rule — momentum_breakout.

    EXACT replica of the backtest (backtest.signal_search 'momentum_breakout').
    95% CI [1.67, 2.74, 4.22], 280 trades, PF>1 in all three time-thirds (2026-06-25).
    Above SMA-10 AND SMA-20, volume > 2x, up > 3% on the day, RSI < 75.

    NOTE: rsi default coerces missing to 0.0 which <75 (passes). Do not add lower bound.
    """
    t = report.get("technicals") or {}
    return (
        bool(t.get("above_sma_10"))
        and bool(t.get("above_sma_20"))
        and _f(t.get("volume_ratio")) > 2
        and _f(t.get("daily_change_pct")) > 3
        and _f(t.get("rsi_14")) < 75
    )


def relative_strength(report: dict) -> bool:
    """MAIN entry rule — relative_strength.

    EXACT replica. 95% CI [1.57, 2.35, 3.46], 443 trades, PF>1 in all thirds
    (deployed 2026-07-02). Price within 10% of 30d high + vol>1.5x + up day.
    """
    t = report.get("technicals") or {}
    high30 = _f(t.get("high_30d"))
    price = _f(t.get("current_price"))
    return (
        high30 > 0
        and price >= 0.9 * high30
        and _f(t.get("volume_ratio")) > 1.5
        and _f(t.get("daily_change_pct")) > 0
    )


def quality_momentum(report: dict) -> bool:
    """Legacy MAIN rule (no validated edge after correction).

    Kept for harness compatibility and explicit selection via MAIN_SIGNAL.
    Above SMA-20 + rev_growth>0 + profit_margin>0 + up day.
    """
    t = report.get("technicals") or {}
    fin = (report.get("fundamentals") or {}).get("financials") or {}
    rev_growth = fin.get("revenue_growth")
    margin = fin.get("profit_margin")
    if rev_growth is None or margin is None:
        return False
    return (
        bool(t.get("above_sma_20"))
        and (t.get("daily_change_pct") or 0) > 0
        and rev_growth > 0
        and margin > 0
    )


# =============================================================================
# CAND-BASED (pure harness / signal_search path)
# Exact match to the original lambdas so existing backtests are unchanged.
# =============================================================================

def momentum_breakout_cand(c: Cand) -> bool:
    return c.above10 and c.above20 and c.vol_ratio > 2 and c.daily_chg > 3 and c.rsi < 75


def relative_strength_cand(c: Cand) -> bool:
    return (
        c.high30 > 0
        and c.price >= 0.9 * c.high30
        and c.vol_ratio > 1.5
        and c.daily_chg > 0
    )


def quality_momentum_cand(c: Cand) -> bool:
    return (
        c.above20
        and c.daily_chg > 0
        and c.rev_growth > 0
        and c.margin > 0
    )


# =============================================================================
# Registries + helpers (used by live agent + dashboard + future sleeve mgmt)
# =============================================================================

# Live (report) registry
REPORT_FUNCS: Dict[str, Callable[[dict], bool]] = {
    "momentum_breakout": momentum_breakout,
    "relative_strength": relative_strength,
    "quality_momentum": quality_momentum,
}

# Harness (Cand) registry — thin alias for migration
CAND_FUNCS: Dict[str, Callable[[Cand], bool]] = {
    "momentum_breakout": momentum_breakout_cand,
    "relative_strength": relative_strength_cand,
    "quality_momentum": quality_momentum_cand,
}

# Human descriptions (central source; used in reasoning + UI)
SIGNAL_DESCRIPTIONS: Dict[str, str] = {
    "momentum_breakout": "momentum_breakout: >SMA10&20 + vol>2x + day>3% + rsi<75",
    "relative_strength": "relative_strength: within 10% of 30d-high + vol>1.5x + up-day",
    "quality_momentum": "quality_momentum: SMA20 + rev_growth>0 + margin>0 + up-day",
}


def get_signal_description(name: str) -> str:
    """Return the canonical description for a signal name (for reasoning/UI)."""
    return SIGNAL_DESCRIPTIONS.get(
        name,
        f"{name}: (custom/unknown signal)"
    )


def get_active_signals(main_signal: str) -> list[str]:
    """Parse MAIN_SIGNAL (comma list) and return only known factor names.

    Unknown names are ignored (caller should log).
    """
    known = set(REPORT_FUNCS.keys())
    names = [s.strip().lower() for s in main_signal.split(",") if s.strip()]
    return [n for n in names if n in known]


def get_signal_func(name: str, prefer_cand: bool = False) -> Callable | None:
    """Return the predicate function for a name.

    prefer_cand=True for harness paths.
    """
    if prefer_cand:
        return CAND_FUNCS.get(name)
    return REPORT_FUNCS.get(name)


# Backwards-compatible alias for signal_search.py (the original SIGNALS dict)
# This lets existing harness code continue to work with minimal change:
#   from backtest.signals import SIGNALS
SIGNALS: Dict[str, Callable[[Cand], bool]] = CAND_FUNCS


__all__ = [
    "Cand",
    "momentum_breakout",
    "relative_strength",
    "quality_momentum",
    "momentum_breakout_cand",
    "relative_strength_cand",
    "quality_momentum_cand",
    "REPORT_FUNCS",
    "CAND_FUNCS",
    "SIGNAL_DESCRIPTIONS",
    "get_signal_description",
    "get_active_signals",
    "get_signal_func",
    "SIGNALS",
]
