"""Phase 3.1: auto-apply gate for recommendations.

Reads AUTO_APPLY_RULES env var (comma-separated rule names) and applies any
matching recommendations via TunableParams.set(source="auto"). Defaults to
empty — nothing auto-applies until Tom explicitly opts in per rule.

Not scheduled by default. To enable, either:
  1. Call apply_auto_recommendations() from a scheduled job, or
  2. Wait for Phase 3.3 circuit-breaker integration

Defense in depth:
  - TUNABLE_PARAMS_FROZEN=1 halts all auto-apply (TunableParams.set enforces this)
  - Each apply respects the param's bounds (TunableParams.set enforces this)
  - Each apply is logged via change_log + decision_log
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


def _enabled_rules() -> set[str]:
    raw = os.getenv("AUTO_APPLY_RULES", "").strip()
    if not raw:
        return set()
    return {r.strip() for r in raw.split(",") if r.strip()}


def apply_auto_recommendations() -> dict:
    """Apply any recommendations whose rule is in AUTO_APPLY_RULES.

    Returns a summary dict with counts and per-rule details.
    """
    enabled = _enabled_rules()
    if not enabled:
        logger.info("auto_apply: AUTO_APPLY_RULES is empty — nothing to apply")
        return {"applied": 0, "skipped": 0, "failed": 0, "details": []}

    if os.getenv("TUNABLE_PARAMS_FROZEN") == "1":
        logger.warning("auto_apply: TUNABLE_PARAMS_FROZEN=1 — skipping all auto-apply")
        return {"applied": 0, "skipped": 0, "failed": 0, "frozen": True, "details": []}

    from utils.param_recommender import recommend
    from utils.tunable_params import get_tunable_params
    from utils.decision_log import log_recommendation, mark_decision

    applied = 0
    skipped = 0
    failed = 0
    details: list[dict] = []
    tp = get_tunable_params()

    for rec in recommend():
        if rec.rule not in enabled:
            skipped += 1
            details.append({"rule": rec.rule, "param": rec.param, "outcome": "skipped_not_enabled"})
            continue

        # Always emit the recommendation to decision_log first so we have an
        # id even if the apply fails.
        rec_id = log_recommendation(
            param=rec.param,
            current=rec.current,
            proposed=rec.proposed,
            rule=rec.rule,
            rationale=rec.rationale,
            severity=rec.severity,
            supporting_metrics=rec.supporting_metrics,
        )

        try:
            tp.set(rec.param, rec.proposed, source="auto")
            mark_decision(rec_id=rec_id, decision="applied", note=f"auto-applied by rule {rec.rule}")
            applied += 1
            details.append({"rule": rec.rule, "param": rec.param, "outcome": "applied", "rec_id": rec_id})
        except PermissionError as e:
            mark_decision(rec_id=rec_id, decision="rejected", note=f"frozen: {e}")
            skipped += 1
            details.append({"rule": rec.rule, "param": rec.param, "outcome": "frozen", "rec_id": rec_id})
        except Exception as e:
            mark_decision(rec_id=rec_id, decision="rejected", note=f"error: {e}")
            failed += 1
            details.append({"rule": rec.rule, "param": rec.param, "outcome": f"error: {e}", "rec_id": rec_id})

    logger.info(f"auto_apply: applied={applied} skipped={skipped} failed={failed}")
    return {
        "applied": applied,
        "skipped": skipped,
        "failed": failed,
        "ts": datetime.utcnow().isoformat(),
        "enabled_rules": sorted(enabled),
        "details": details,
    }
