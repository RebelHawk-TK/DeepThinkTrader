"""Daily strategy snapshot writer.

Appends one JSON record per (user, portfolio, day) to logs/strategy_snapshot.jsonl
so we can see how params + performance metrics drift over time. Foundation for
adaptive retraining (idea #2 in the roadmap) — get the measurement right before
we touch any tuning logic.

Idempotent: only writes today's snapshot if today doesn't already appear in the
file. Safe to call from every cycle.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_LOG_PATH = Path(__file__).resolve().parent.parent / "logs" / "strategy_snapshot.jsonl"


def _today_keys_present() -> set[tuple[str, str]]:
    """Return set of (user_id, portfolio) keys already snapshotted today.

    Reads the tail of the file rather than the whole thing — snapshots are
    written once per day so today's records will be the most recent.
    """
    if not _LOG_PATH.exists():
        return set()
    today = date.today().isoformat()
    keys: set[tuple[str, str]] = set()
    try:
        with open(_LOG_PATH, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            # Read last 8KB — enough for several daily snapshots
            read_size = min(size, 8192)
            f.seek(max(0, size - read_size))
            tail = f.read().decode("utf-8", errors="replace")
        for line in tail.splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("date") == today:
                keys.add((str(rec.get("user_id")), str(rec.get("portfolio"))))
    except Exception as e:
        logger.debug(f"snapshot tail read failed: {e}")
    return keys


def _params_in_use() -> dict:
    """Snapshot the current values of tunable parameters."""
    try:
        from utils.tunable_params import get_tunable_params
        return get_tunable_params().get_all()
    except Exception:
        # tunable_params not available yet — fall back to reading Config directly
        from config import Config
        return {
            "kelly_safety_multiplier": Config.KELLY_SAFETY_MULTIPLIER,
            "max_risk_per_trade": Config.MAX_RISK_PER_TRADE,
            "max_daily_loss": Config.MAX_DAILY_LOSS,
            "min_conviction": Config.MIN_CONVICTION,
            "min_reward_risk_ratio": Config.MIN_REWARD_RISK_RATIO,
            "max_position_pct": Config.MAX_POSITION_PCT,
            "max_open_positions": Config.MAX_OPEN_POSITIONS,
            "max_sector_exposure_pct": Config.MAX_SECTOR_EXPOSURE_PCT,
            "max_drawdown_halt_pct": Config.MAX_DRAWDOWN_HALT_PCT,
            "trailing_stop_activation_pct": Config.TRAILING_STOP_ACTIVATION_PCT,
            "trailing_stop_distance_pct": Config.TRAILING_STOP_DISTANCE_PCT,
        }


def maybe_write_daily_snapshot(db, user_ids: list[int], portfolios: tuple[str, ...] = ("main", "penny")) -> int:
    """Write today's snapshot for each (user, portfolio) if not already done.

    Returns count of records written.
    """
    today = date.today().isoformat()
    already = _today_keys_present()
    written = 0
    params = _params_in_use()

    import os as _os
    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except Exception as e:
        logger.warning(f"Could not create logs dir: {e}")
        return 0

    for uid in user_ids:
        for portfolio in portfolios:
            if (str(uid), portfolio) in already:
                continue
            try:
                metrics = db.get_strategy_performance(uid, portfolio, days=30)
                # If no trades in the window, still record an empty snapshot —
                # absence of activity is itself information for the time series.
                record = {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "date": today,
                    "user_id": uid,
                    "portfolio": portfolio,
                    "params": params,
                    "metrics": metrics,
                }
                is_new = not _LOG_PATH.exists()
                with open(_LOG_PATH, "a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
                if is_new:
                    _os.chmod(_LOG_PATH, 0o600)
                written += 1
            except Exception as e:
                logger.error(f"Snapshot write failed for user={uid} portfolio={portfolio}: {e}")
    if written:
        logger.info(f"Strategy snapshot: wrote {written} record(s) for {today}")
    return written
