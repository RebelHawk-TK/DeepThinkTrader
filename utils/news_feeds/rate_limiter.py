"""Generic rate limiter supporting daily, monthly, and per-minute limits."""

import logging
import threading
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class RateLimiter:
    """Thread-safe rate limiter with support for multiple time windows.

    Supports daily limits (resets every 24h), monthly limits (resets every 30 days),
    and per-minute limits. Can enforce dual limits (e.g. Alpha Vantage: 25/day AND 5/min).
    """

    def __init__(
        self,
        max_calls: int,
        period_seconds: int,
        per_minute_limit: int | None = None,
        name: str = "unknown",
    ):
        self.max_calls = max_calls
        self.period_seconds = period_seconds
        self.per_minute_limit = per_minute_limit
        self.name = name
        self._call_history: list[datetime] = []
        self._lock = threading.Lock()

    @classmethod
    def daily(cls, max_calls: int, per_minute_limit: int | None = None, name: str = "unknown"):
        return cls(max_calls, period_seconds=86400, per_minute_limit=per_minute_limit, name=name)

    @classmethod
    def monthly(cls, max_calls: int, name: str = "unknown"):
        return cls(max_calls, period_seconds=86400 * 30, name=name)

    def _cleanup(self):
        now = datetime.utcnow()
        cutoff = now - timedelta(seconds=self.period_seconds)
        self._call_history = [t for t in self._call_history if t > cutoff]

    def _minute_count(self) -> int:
        now = datetime.utcnow()
        one_min_ago = now - timedelta(seconds=60)
        return sum(1 for t in self._call_history if t > one_min_ago)

    def can_make_call(self) -> bool:
        with self._lock:
            self._cleanup()
            if len(self._call_history) >= self.max_calls:
                return False
            if self.per_minute_limit and self._minute_count() >= self.per_minute_limit:
                return False
            return True

    def record_call(self):
        with self._lock:
            self._call_history.append(datetime.utcnow())

    def calls_remaining(self) -> int:
        with self._lock:
            self._cleanup()
            return max(0, self.max_calls - len(self._call_history))

    def budget_status(self) -> dict:
        with self._lock:
            self._cleanup()
            used = len(self._call_history)
            remaining = max(0, self.max_calls - used)
            if self.period_seconds >= 86400 * 25:
                period = "month"
            elif self.period_seconds >= 86400:
                period = "day"
            else:
                period = f"{self.period_seconds}s"
            return {
                "name": self.name,
                "used": used,
                "remaining": remaining,
                "max": self.max_calls,
                "period": period,
            }
