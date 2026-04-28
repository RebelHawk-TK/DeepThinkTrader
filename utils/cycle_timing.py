"""Lightweight per-stage timing for the analysis pipeline.

Records `(ticker, priority, stage, duration_ms)` to logs/cycle_timing.jsonl
so we can see where time goes without trying to tune blind.

Usage:
    from utils.cycle_timing import time_stage

    with time_stage(ticker, priority, "claude_analyst"):
        ... work ...

Never raises — write failures are logged at debug level only.
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "cycle_timing.jsonl"


@contextmanager
def time_stage(ticker: str, priority: str, stage: str):
    """Time a block and append a record to the cycle_timing log."""
    start = time.monotonic()
    try:
        yield
    finally:
        duration_ms = int((time.monotonic() - start) * 1000)
        try:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            record = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "ticker": ticker,
                "priority": priority,
                "stage": stage,
                "ms": duration_ms,
            }
            is_new = not _LOG_PATH.exists()
            with open(_LOG_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            if is_new:
                os.chmod(_LOG_PATH, 0o600)
        except Exception as e:
            logger.debug(f"cycle_timing write failed: {e}")
