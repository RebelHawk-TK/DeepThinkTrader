"""Phase 2.2: rule-based parameter recommender.

Reads recent strategy snapshots, applies deterministic rules, and returns
proposed parameter changes. No ML — just hand-tuned thresholds. Phase 3
will let some recommendations auto-apply once they have a track record.

Design principles:
  - Returns recommendations, never applies them. Caller decides.
  - Each rule has a stable name so decision_log can match outcomes back.
  - Requires MIN_DATA_DAYS of snapshots before producing any output —
    below that, results are pure noise.
  - Severity-orders multiple rules touching the same param so we don't
    surface conflicting recommendations.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

logger = logging.getLogger(__name__)

_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "logs" / "strategy_snapshot.jsonl"

MIN_DATA_DAYS = 30  # below this, the recommender returns []

_SEVERITY_ORDER = {"critical": 3, "high": 2, "medium": 1, "info": 0}


@dataclass(frozen=True)
class Recommendation:
    rule: str
    param: str
    current: float
    proposed: float
    rationale: str
    severity: str
    supporting_metrics: dict

    def to_dict(self) -> dict:
        return asdict(self)


def _load_recent_snapshots(days: int = 60) -> list[dict]:
    """Read the last `days` worth of snapshot records."""
    if not _SNAPSHOT_PATH.exists():
        return []
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    out: list[dict] = []
    try:
        with open(_SNAPSHOT_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("date", "") >= cutoff:
                    out.append(rec)
    except Exception as e:
        logger.debug(f"snapshot read failed: {e}")
    return out


def _latest_per_portfolio(snapshots: list[dict]) -> dict[tuple[int, str], dict]:
    """Pick the most recent snapshot per (user_id, portfolio)."""
    latest: dict[tuple[int, str], dict] = {}
    for rec in snapshots:
        key = (rec.get("user_id"), rec.get("portfolio"))
        prev = latest.get(key)
        if prev is None or rec.get("date", "") > prev.get("date", ""):
            latest[key] = rec
    return latest


# ── Rules ─────────────────────────────────────────────────────────────
# Each rule takes the latest snapshot and returns 0 or 1 recommendations.
# Rule names are stable identifiers — used by decision_log to match outcomes.


def _rule_kelly_size_up(snap: dict) -> Recommendation | None:
    """Edge looks real and drawdown is tame — increase Kelly fraction."""
    m = snap.get("metrics", {})
    sharpe = m.get("sharpe", 0)
    win_rate = m.get("win_rate", 0)
    dd_pct = m.get("max_drawdown_pct", 0)
    trades = m.get("trade_count", 0)
    if trades < 20:
        return None
    if sharpe > 1.5 and win_rate > 0.60 and dd_pct < 5.0:
        params = snap.get("params", {})
        current = params.get("kelly_safety_multiplier", 0.5)
        proposed = round(min(1.0, current + 0.05), 2)
        if proposed <= current:
            return None
        return Recommendation(
            rule="kelly_size_up",
            param="kelly_safety_multiplier",
            current=current,
            proposed=proposed,
            rationale=(
                f"30d Sharpe {sharpe:.2f}, win rate {win_rate*100:.0f}%, "
                f"drawdown {dd_pct:.1f}% — edge supports larger sizing"
            ),
            severity="info",
            supporting_metrics={"sharpe": sharpe, "win_rate": win_rate, "max_drawdown_pct": dd_pct, "trade_count": trades},
        )
    return None


def _rule_kelly_size_down(snap: dict) -> Recommendation | None:
    """Drawdown is large — pull Kelly fraction back."""
    m = snap.get("metrics", {})
    dd_pct = m.get("max_drawdown_pct", 0)
    trades = m.get("trade_count", 0)
    if trades < 10:
        return None
    if dd_pct > 8.0:
        params = snap.get("params", {})
        current = params.get("kelly_safety_multiplier", 0.5)
        proposed = round(max(0.1, current - 0.10), 2)
        if proposed >= current:
            return None
        return Recommendation(
            rule="kelly_size_down",
            param="kelly_safety_multiplier",
            current=current,
            proposed=proposed,
            rationale=f"30d drawdown {dd_pct:.1f}% exceeds 8% — sizing too aggressive for current vol",
            severity="high",
            supporting_metrics={"max_drawdown_pct": dd_pct, "trade_count": trades},
        )
    return None


def _rule_raise_conviction_on_winrate_drop(snap: dict) -> Recommendation | None:
    """Win rate dropped >10pp from baseline — raise conviction bar."""
    m = snap.get("metrics", {})
    delta = m.get("win_rate_delta", 0)
    trades = m.get("trade_count", 0)
    if trades < 20:
        return None
    if delta < -0.10:
        params = snap.get("params", {})
        current = params.get("min_conviction", 6.0)
        proposed = round(min(9.5, current + 0.5), 1)
        if proposed <= current:
            return None
        return Recommendation(
            rule="raise_conviction_on_winrate_drop",
            param="min_conviction",
            current=current,
            proposed=proposed,
            rationale=f"Win rate fell {delta*100:.0f}pp vs baseline — tighten selection",
            severity="medium",
            supporting_metrics={"win_rate_delta": delta, "trade_count": trades},
        )
    return None


_RULES = (
    _rule_kelly_size_up,
    _rule_kelly_size_down,
    _rule_raise_conviction_on_winrate_drop,
)


def recommend(min_data_days: int = MIN_DATA_DAYS) -> list[Recommendation]:
    """Return the top-severity recommendation per (param, user, portfolio).

    Returns empty list until at least `min_data_days` of distinct dates are
    in the snapshot file — early recommendations on thin data are noise.
    """
    snapshots = _load_recent_snapshots(days=90)
    distinct_dates = {rec.get("date") for rec in snapshots if rec.get("date")}
    if len(distinct_dates) < min_data_days:
        logger.info(
            f"recommender: {len(distinct_dates)} day(s) of data — "
            f"need {min_data_days} before producing output"
        )
        return []

    latest = _latest_per_portfolio(snapshots)
    proposals: dict[tuple, Recommendation] = {}
    for (uid, portfolio), snap in latest.items():
        for rule_fn in _RULES:
            try:
                rec = rule_fn(snap)
            except Exception as e:
                logger.warning(f"rule {rule_fn.__name__} failed: {e}")
                continue
            if rec is None:
                continue
            key = (uid, portfolio, rec.param)
            existing = proposals.get(key)
            if existing is None or _SEVERITY_ORDER[rec.severity] > _SEVERITY_ORDER[existing.severity]:
                proposals[key] = rec

    return list(proposals.values())
