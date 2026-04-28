"""Audit log for tunable parameter changes (Phase 3.2).

Every call to TunableParams.set() logs one record here with old/new values
and the source (manual via dashboard/JSON edit, or auto from recommender).
This is the audit trail for closed-loop tuning.

Path: logs/param_changes.jsonl. Append-only, JSON line per change.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "param_changes.jsonl"


def log_param_change(
    *,
    param: str,
    old_value: Any,
    new_value: Any,
    source: str,
    rationale: str | None = None,
) -> None:
    """Append one audit record. Never raises."""
    import os as _os
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "param": param,
            "old_value": old_value,
            "new_value": new_value,
            "source": source,
            "rationale": rationale,
        }
        is_new = not _LOG_PATH.exists()
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        if is_new:
            _os.chmod(_LOG_PATH, 0o600)
    except Exception as e:
        logger.debug(f"change_log write failed: {e}")
