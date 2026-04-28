"""Decision telemetry for Phase 2 recommendations.

Logs every recommendation produced by the recommender, plus what happened
to it (applied / rejected / ignored, and 30-day-later outcome). This is
the dataset Phase 3 needs to know which rules actually work before allowing
auto-apply on them.

Two write paths:
  - log_recommendation: emit a record when the recommender proposes a change
  - mark_decision: update an existing recommendation with its outcome

Path: logs/param_decisions.jsonl. Append-only, one record per emit/update.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "param_decisions.jsonl"


def log_recommendation(
    *,
    param: str,
    current: Any,
    proposed: Any,
    rule: str,
    rationale: str,
    severity: str = "info",
    supporting_metrics: dict | None = None,
) -> str:
    """Emit a fresh recommendation. Returns the recommendation id."""
    rec_id = uuid.uuid4().hex[:12]
    _append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "recommendation",
        "id": rec_id,
        "param": param,
        "current": current,
        "proposed": proposed,
        "rule": rule,
        "rationale": rationale,
        "severity": severity,
        "supporting_metrics": supporting_metrics or {},
    })
    return rec_id


def mark_decision(
    *,
    rec_id: str,
    decision: str,
    note: str | None = None,
) -> None:
    """Record the operator (or auto-applier) decision on a recommendation.

    decision: "applied" | "rejected" | "expired"
    """
    _append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "decision",
        "id": rec_id,
        "decision": decision,
        "note": note,
    })


def mark_outcome(
    *,
    rec_id: str,
    metric_deltas: dict,
) -> None:
    """Record the post-change outcome for a recommendation, ~30 days later.

    metric_deltas: {"sharpe": +0.2, "win_rate": -0.05, ...} relative changes.
    """
    _append({
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "outcome",
        "id": rec_id,
        "metric_deltas": metric_deltas,
    })


def _append(record: dict) -> None:
    import os as _os
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        is_new = not _LOG_PATH.exists()
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        if is_new:
            _os.chmod(_LOG_PATH, 0o600)
    except Exception as e:
        logger.debug(f"decision_log write failed: {e}")
