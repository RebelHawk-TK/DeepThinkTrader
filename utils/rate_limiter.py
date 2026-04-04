"""Rate Limiter — Tracks API call budgets against daily quotas.

Prevents exceeding free-tier limits (e.g., NewsAPI 100 calls/day).
Persists counts via StateManager so restarts don't reset the counter.
"""

from __future__ import annotations

import logging

from config import Config
from utils.state import StateManager

logger = logging.getLogger(__name__)


class RateLimiter:
    def __init__(self, state: StateManager | None = None):
        self._state = state or StateManager()
        self._config = Config()

    def can_call_newsapi(self) -> bool:
        """Check if we have remaining NewsAPI budget for today."""
        used = self._state.newsapi_calls_today
        limit = self._config.NEWSAPI_DAILY_LIMIT
        if used >= limit:
            logger.warning(f"NewsAPI daily limit reached ({used}/{limit}) — skipping news fetch")
            return False
        return True

    def record_newsapi_call(self) -> None:
        """Record a NewsAPI call and log quota status."""
        self._state.record_newsapi_call()
        used = self._state.newsapi_calls_today
        limit = self._config.NEWSAPI_DAILY_LIMIT
        if used == int(limit * 0.8):
            logger.warning(f"NewsAPI quota 80% used ({used}/{limit})")
        elif used == int(limit * 0.95):
            logger.warning(f"NewsAPI quota 95% used ({used}/{limit}) — approaching limit")

    def newsapi_status(self) -> dict:
        """Return current NewsAPI usage stats."""
        used = self._state.newsapi_calls_today
        limit = self._config.NEWSAPI_DAILY_LIMIT
        return {
            "used": used,
            "limit": limit,
            "remaining": max(0, limit - used),
            "pct_used": round(used / limit * 100, 1) if limit > 0 else 0,
        }
