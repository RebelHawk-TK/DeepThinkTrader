"""In-cycle TTL cache for ticker-level AI analysis shared across users.

Claude analyst + debate engine outputs are ticker-level (no user-specific
input), so when the bot runs the same cycle for multiple active users, we
can reuse results and avoid redundant Anthropic API calls.

Cache key is the ticker symbol. TTL is set slightly under the cycle interval
so values expire before the next cycle starts.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from threading import Lock
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: int):
        self._store: dict[str, tuple[datetime, Any]] = {}
        self._lock = Lock()
        self._ttl = timedelta(seconds=ttl_seconds)

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, val = entry
            if datetime.utcnow() - ts >= self._ttl:
                del self._store[key]
                return None
            return val

    def set(self, key: str, val: Any) -> None:
        with self._lock:
            self._store[key] = (datetime.utcnow(), val)


# TTL = 25 min (just under the 30-min cycle interval).
_TTL_SECONDS = 25 * 60

_claude_cache = TTLCache(ttl_seconds=_TTL_SECONDS)
_debate_cache = TTLCache(ttl_seconds=_TTL_SECONDS)


def claude_cache() -> TTLCache:
    return _claude_cache


def debate_cache() -> TTLCache:
    return _debate_cache
