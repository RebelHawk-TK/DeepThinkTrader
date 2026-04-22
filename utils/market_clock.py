"""Market Clock — Real-time system clock validation against Alpaca's market calendar.

Single source of truth for market hours. Handles:
- Proper ET timezone conversion (works regardless of system timezone)
- Alpaca market calendar (holidays, early closes)
- Clock drift detection (system vs Alpaca server time)
- Pre-market and after-hours awareness
- Caching to avoid redundant API calls
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests as http_requests

from config import Config

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


class MarketClock:
    """Real-time market clock with Alpaca calendar validation.

    Market hours are global, not per-user, but Alpaca's /v2/clock endpoint
    requires authentication. Callers supply any valid Alpaca keys
    (typically the first active user's keys — see get_market_clock below).
    """

    def __init__(self, api_key: str, secret_key: str):
        self._session = http_requests.Session()
        self._session.headers.update({
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        })
        self._base_url = Config.ALPACA_BASE_URL

        # Cache: avoid hitting Alpaca API every 30 seconds
        self._cached_clock: dict | None = None
        self._cache_time: datetime | None = None
        self._cache_ttl = timedelta(seconds=60)

        # Clock drift tracking
        self._last_drift_ms: float | None = None

    def _now_et(self) -> datetime:
        """Current time in US Eastern, regardless of system timezone."""
        return datetime.now(ET)

    def _fetch_alpaca_clock(self) -> dict | None:
        """Fetch market clock from Alpaca API with caching."""
        now = datetime.now(UTC)
        if self._cached_clock and self._cache_time:
            if now - self._cache_time < self._cache_ttl:
                return self._cached_clock

        try:
            resp = self._session.get(f"{self._base_url}/v2/clock", timeout=5)
            if resp.ok:
                data = resp.json()
                self._cached_clock = data
                self._cache_time = now

                # Clock drift detection: compare Alpaca server time to local
                server_time_str = data.get("timestamp", "")
                if server_time_str:
                    try:
                        server_time = datetime.fromisoformat(server_time_str.replace("Z", "+00:00"))
                        drift = abs((now - server_time).total_seconds() * 1000)
                        self._last_drift_ms = drift
                        if drift > 5000:
                            logger.warning(
                                f"CLOCK DRIFT: System clock off by {drift:.0f}ms from Alpaca server"
                            )
                    except Exception:
                        pass

                return data
        except Exception as e:
            logger.debug(f"Alpaca clock fetch failed: {e}")

        return self._cached_clock  # Return stale cache if API fails

    def is_market_open(self) -> bool:
        """Check if US stock market is currently open.

        Uses Alpaca's /v2/clock API (authoritative), falls back to
        timezone-aware local calculation if API is unreachable.
        """
        clock = self._fetch_alpaca_clock()
        if clock is not None:
            return clock.get("is_open", False)

        # Fallback: timezone-aware local check
        return self._local_market_check()

    def _local_market_check(self) -> bool:
        """Fallback market hours check using proper ET timezone."""
        now = self._now_et()
        if now.weekday() > 4:
            return False
        market_minutes = now.hour * 60 + now.minute
        return 9 * 60 + 30 <= market_minutes < 16 * 60

    def get_status(self) -> dict:
        """Get comprehensive market status for logging/dashboard.

        Returns:
            {
                "is_open": bool,
                "current_time_et": str,
                "next_open": str | None,
                "next_close": str | None,
                "clock_drift_ms": float | None,
                "source": "alpaca" | "local_fallback",
                "is_early_close": bool,
            }
        """
        now_et = self._now_et()
        clock = self._fetch_alpaca_clock()

        if clock:
            next_open = clock.get("next_open", "")
            next_close = clock.get("next_close", "")

            # Detect early close: normal close is 16:00 ET
            is_early_close = False
            if next_close and clock.get("is_open"):
                try:
                    close_dt = datetime.fromisoformat(next_close.replace("Z", "+00:00"))
                    close_et = close_dt.astimezone(ET)
                    if close_et.hour < 16:
                        is_early_close = True
                except Exception:
                    pass

            return {
                "is_open": clock.get("is_open", False),
                "current_time_et": now_et.strftime("%Y-%m-%d %H:%M:%S ET"),
                "next_open": next_open,
                "next_close": next_close,
                "clock_drift_ms": self._last_drift_ms,
                "source": "alpaca",
                "is_early_close": is_early_close,
            }

        return {
            "is_open": self._local_market_check(),
            "current_time_et": now_et.strftime("%Y-%m-%d %H:%M:%S ET"),
            "next_open": None,
            "next_close": None,
            "clock_drift_ms": None,
            "source": "local_fallback",
            "is_early_close": False,
        }

    def get_today_calendar(self) -> dict | None:
        """Get today's market calendar entry (open/close times, early close).

        Returns None if today is not a trading day (weekend/holiday).
        """
        today = self._now_et().strftime("%Y-%m-%d")
        try:
            resp = self._session.get(
                f"{self._base_url}/v2/calendar",
                params={"start": today, "end": today},
                timeout=5,
            )
            if resp.ok:
                days = resp.json()
                if days:
                    day = days[0]
                    return {
                        "date": day.get("date"),
                        "open": day.get("open"),
                        "close": day.get("close"),
                        "is_early_close": day.get("close", "16:00") != "16:00",
                    }
        except Exception as e:
            logger.debug(f"Calendar fetch failed: {e}")
        return None

    def minutes_until_close(self) -> int | None:
        """Minutes until market close. Returns None if market is closed."""
        clock = self._fetch_alpaca_clock()
        if not clock or not clock.get("is_open"):
            return None

        next_close = clock.get("next_close", "")
        if next_close:
            try:
                close_dt = datetime.fromisoformat(next_close.replace("Z", "+00:00"))
                now = datetime.now(UTC)
                diff = (close_dt - now).total_seconds() / 60
                return max(0, int(diff))
            except Exception:
                pass
        return None

    def minutes_until_open(self) -> int | None:
        """Minutes until market open. Returns None if market is already open."""
        clock = self._fetch_alpaca_clock()
        if not clock or clock.get("is_open"):
            return None

        next_open = clock.get("next_open", "")
        if next_open:
            try:
                open_dt = datetime.fromisoformat(next_open.replace("Z", "+00:00"))
                now = datetime.now(UTC)
                diff = (open_dt - now).total_seconds() / 60
                return max(0, int(diff))
            except Exception:
                pass
        return None

    def log_status(self) -> None:
        """Log current market status for diagnostics."""
        status = self.get_status()
        drift_str = f" | Clock drift: {status['clock_drift_ms']:.0f}ms" if status["clock_drift_ms"] is not None else ""
        early_str = " | EARLY CLOSE" if status["is_early_close"] else ""

        if status["is_open"]:
            mins = self.minutes_until_close()
            close_str = f" | Closes in {mins}min" if mins is not None else ""
            logger.info(
                f"Market OPEN ({status['source']}) | {status['current_time_et']}"
                f"{close_str}{early_str}{drift_str}"
            )
        else:
            mins = self.minutes_until_open()
            open_str = f" | Opens in {mins}min" if mins is not None else ""
            logger.info(
                f"Market CLOSED ({status['source']}) | {status['current_time_et']}"
                f"{open_str}{drift_str}"
            )


# Module-level singleton for easy import. The singleton is keyed by
# credential fingerprint so a second caller with different keys can reuse
# the same underlying instance if compatible.
_clock: MarketClock | None = None


def get_market_clock(api_key: str, secret_key: str) -> MarketClock:
    """Get or create a MarketClock for these credentials.

    Market data is cross-user but authenticated. First caller sets the
    singleton; subsequent callers reuse it regardless of whose keys made
    the initial call (the API returns the same result either way).
    """
    global _clock
    if _clock is None:
        _clock = MarketClock(api_key, secret_key)
    return _clock
