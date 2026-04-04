"""State Manager — Persists session state across restarts via .state.json.

Saves paused portfolios, last scan date, warmup progress, and API rate counters
so the bot resumes cleanly after a crash or restart.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".state.json")

_DEFAULTS = {
    "paused_portfolios": [],
    "last_scan_date": "",
    "warmup_tickers_seen": 0,
    "newsapi_calls_today": 0,
    "newsapi_call_date": "",
}


class StateManager:
    def __init__(self, path: str = _STATE_FILE):
        self._path = path
        self._state: dict = dict(_DEFAULTS)
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            logger.info("No state file found — starting fresh")
            return
        try:
            with open(self._path) as f:
                data = json.load(f)
            # Merge with defaults so new keys are always present
            for key, default in _DEFAULTS.items():
                self._state[key] = data.get(key, default)
            logger.info(f"State loaded from {self._path}")
            if self._state["paused_portfolios"]:
                logger.warning(f"Restored paused portfolios: {self._state['paused_portfolios']}")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load state file ({e}) — starting fresh")
            self._state = dict(_DEFAULTS)

    def save(self) -> None:
        try:
            with open(self._path, "w") as f:
                json.dump(self._state, f, indent=2)
        except OSError as e:
            logger.error(f"Failed to save state: {e}")

    # ── Paused Portfolios ──────────────────────────────────────────

    @property
    def paused_portfolios(self) -> set[str]:
        return set(self._state["paused_portfolios"])

    def pause_portfolio(self, portfolio: str) -> None:
        portfolios = set(self._state["paused_portfolios"])
        portfolios.add(portfolio)
        self._state["paused_portfolios"] = sorted(portfolios)
        self.save()

    def resume_portfolio(self, portfolio: str) -> None:
        portfolios = set(self._state["paused_portfolios"])
        portfolios.discard(portfolio)
        self._state["paused_portfolios"] = sorted(portfolios)
        self.save()

    # ── Scan Date ──────────────────────────────────────────────────

    @property
    def last_scan_date(self) -> str:
        return self._state["last_scan_date"]

    @last_scan_date.setter
    def last_scan_date(self, value: str) -> None:
        self._state["last_scan_date"] = value
        self.save()

    # ── Warmup ─────────────────────────────────────────────────────

    @property
    def warmup_tickers_seen(self) -> int:
        return self._state["warmup_tickers_seen"]

    @warmup_tickers_seen.setter
    def warmup_tickers_seen(self, value: int) -> None:
        self._state["warmup_tickers_seen"] = value
        self.save()

    # ── NewsAPI Rate Counter ───────────────────────────────────────

    def record_newsapi_call(self) -> None:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._state["newsapi_call_date"] != today:
            self._state["newsapi_call_date"] = today
            self._state["newsapi_calls_today"] = 0
        self._state["newsapi_calls_today"] += 1
        # Save every 10 calls to avoid excessive disk writes
        if self._state["newsapi_calls_today"] % 10 == 0:
            self.save()

    @property
    def newsapi_calls_today(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._state["newsapi_call_date"] != today:
            return 0
        return self._state["newsapi_calls_today"]
