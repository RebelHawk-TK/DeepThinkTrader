"""Phase 2.3: daily digest of recommendations + recent metrics.

Writes a human-readable markdown file once per day to logs/digest_<date>.md
summarizing the latest snapshot metrics and any active recommendations from
the recommender. No Slack pinging yet (Phase 2 default is quiet); operator
opens the file manually.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_SNAPSHOT_PATH = _LOG_DIR / "strategy_snapshot.jsonl"


def _today_digest_path() -> Path:
    return _LOG_DIR / f"digest_{date.today().isoformat()}.md"


def _load_today_snapshots() -> list[dict]:
    if not _SNAPSHOT_PATH.exists():
        return []
    today = date.today().isoformat()
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
                if rec.get("date") == today:
                    out.append(rec)
    except Exception as e:
        logger.debug(f"snapshot read failed: {e}")
    return out


def maybe_write_digest() -> bool:
    """Write today's digest if it doesn't already exist. Returns True if written."""
    path = _today_digest_path()
    if path.exists():
        return False

    try:
        from utils.param_recommender import recommend
        recommendations = recommend()
    except Exception as e:
        logger.warning(f"digest: recommender call failed — {e}")
        recommendations = []

    snapshots = _load_today_snapshots()

    lines = [
        f"# DeepThinkTrader digest — {date.today().isoformat()}",
        "",
        f"_Generated {datetime.now().isoformat(timespec='seconds')}_",
        "",
    ]

    # Snapshot summary
    if snapshots:
        lines.extend(["## Today's snapshot", "", "| User | Portfolio | Trades | Win rate | Sharpe | Sortino | Max DD % | Avg R |", "|---|---|---|---|---|---|---|---|"])
        for s in snapshots:
            m = s.get("metrics", {})
            lines.append(
                f"| {s.get('user_id')} | {s.get('portfolio')} | {m.get('trade_count', 0)} | "
                f"{m.get('win_rate', 0)*100:.0f}% | {m.get('sharpe', 0):.2f} | "
                f"{m.get('sortino', 0):.2f} | {m.get('max_drawdown_pct', 0):.1f}% | "
                f"{m.get('avg_r_multiple', 0):.2f} |"
            )
        lines.append("")
    else:
        lines.extend(["## Today's snapshot", "", "_No snapshot recorded today yet._", ""])

    # Recommendations
    lines.extend(["## Recommendations", ""])
    if not recommendations:
        lines.append("_No active recommendations._")
        lines.append("")
        lines.append(
            "Either there isn't enough snapshot data yet (need 30+ days of "
            "distinct dates) or no rules fired against the latest snapshot."
        )
    else:
        lines.append("| Severity | Param | Current → Proposed | Rule | Rationale |")
        lines.append("|---|---|---|---|---|")
        sev_order = {"critical": 0, "high": 1, "medium": 2, "info": 3}
        for r in sorted(recommendations, key=lambda x: sev_order.get(x.severity, 9)):
            lines.append(
                f"| **{r.severity}** | `{r.param}` | {r.current} → {r.proposed} | "
                f"`{r.rule}` | {r.rationale} |"
            )
        lines.append("")
        lines.append("To apply manually:")
        lines.append("```python")
        lines.append("from utils.tunable_params import get_tunable_params")
        for r in recommendations:
            lines.append(f"get_tunable_params().set({r.param!r}, {r.proposed})")
        lines.append("```")

    import os as _os
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text("\n".join(lines), encoding="utf-8")
        _os.chmod(path, 0o600)
        logger.info(f"digest: wrote {path}")
        # Also log recommendations to decision_log for telemetry
        try:
            from utils.decision_log import log_recommendation
            for r in recommendations:
                log_recommendation(
                    param=r.param,
                    current=r.current,
                    proposed=r.proposed,
                    rule=r.rule,
                    rationale=r.rationale,
                    severity=r.severity,
                    supporting_metrics=r.supporting_metrics,
                )
        except Exception as e:
            logger.debug(f"decision_log emit failed: {e}")
        return True
    except Exception as e:
        logger.error(f"digest write failed: {e}")
        return False
