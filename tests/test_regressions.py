"""Regression tests for Sprint 1 bug fixes.

One test per confirmed bug in the plan. Each test fails on the *old* buggy
code and passes on the fix, so they act as a trip-wire against reintroduction.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import responses


# ─────────────────────────── B1: logger NameError ──────────────────────────


def test_b1_database_has_logger_and_imports_logging(db):
    """The ATR seeding path previously called `log.info` / `log.warning`, but
    the module never imported `logging` or defined `log`, so the first new
    ticker crashed with NameError. Verify both are wired up now.
    """
    import utils.database as dbmod

    assert hasattr(dbmod, "logger"), "database.py must expose a module-level `logger`"
    # The bug symbol — a bare `log` — must not exist.
    assert not hasattr(dbmod, "log"), "bare `log` should not shadow `logger`"
    # And only `logger.info/.warning` should appear in the file.
    src = open(dbmod.__file__).read()
    assert "log.info(" not in src
    assert "log.warning(" not in src


def test_b1_atr_seed_handles_missing_data_without_crash(db, monkeypatch):
    """_seed_atr_history must not raise even when yfinance returns empty
    history — the except branch used to re-raise NameError before the fix.
    """
    mock_ticker = MagicMock()
    # Force the early-return branch (empty history).
    mock_ticker.history.return_value.empty = True
    with patch("yfinance.Ticker", return_value=mock_ticker):
        db._seed_atr_history("FAKE")  # must not raise


# ─────────────────────────── B2: drawdown rewrite ──────────────────────────


class _FakeResp:
    def __init__(self, payload, ok=True, status=200):
        self._payload = payload
        self.ok = ok
        self.status_code = status

    def json(self):
        return self._payload


def test_b2_drawdown_uses_equity_curve_not_daily_pnl(risk_manager, monkeypatch):
    """Old code subtracted today's single-day realized P&L from a 30-day
    cumulative P&L peak and would almost always trip. New code must use the
    Alpaca equity curve directly — peak vs current, no DB mix-in.
    """
    equity = [
        100_000, 101_000, 102_000, 103_000, 104_000, 105_000,  # peak
        104_000, 103_500, 103_000, 102_800, 102_500,  # ~2.4% drawdown (OK)
    ]
    monkeypatch.setattr(
        risk_manager, "_fetch_alpaca_equity_history", lambda days=30: equity
    )
    assert risk_manager.check_drawdown_halt(account_value=102_500) is True


def test_b2_drawdown_halts_when_threshold_breached(risk_manager, monkeypatch):
    equity = [100_000, 105_000, 110_000, 115_000, 120_000, 100_000]  # -16.7%
    monkeypatch.setattr(
        risk_manager, "_fetch_alpaca_equity_history", lambda days=30: equity
    )
    # Config default MAX_DRAWDOWN_HALT_PCT = 0.08
    assert risk_manager.check_drawdown_halt(account_value=100_000) is False


def test_b2_drawdown_allows_when_history_short(risk_manager, monkeypatch):
    """<5 equity points → too little data, allow trading (don't block on
    transient network errors or fresh accounts)."""
    monkeypatch.setattr(
        risk_manager, "_fetch_alpaca_equity_history", lambda days=30: [100_000]
    )
    assert risk_manager.check_drawdown_halt(account_value=100_000) is True


@responses.activate
def test_b2_fetch_equity_filters_settlement_artifacts(risk_manager):
    """The 40%-of-prev one-bar crash filter (copy of dashboard.py:390) must
    strip fake settlement drops so they don't invent a false peak."""
    # Use recent epoch timestamps so any BASELINE_DATE filter passes them.
    import time as _t
    base = int(_t.time())
    responses.add(
        responses.GET,
        "https://paper-api.alpaca.markets/v2/account/portfolio/history",
        json={
            "equity": [100_000, 101_000, 40_000, 101_500, 102_000],  # 40k is a settlement artifact
            "timestamp": [base + i for i in range(5)],
        },
        status=200,
    )
    eq = risk_manager._fetch_alpaca_equity_history(days=30)
    assert 40_000 not in eq
    assert eq == [100_000, 101_000, 101_500, 102_000]


# ─────────────────── B3: ghost reconcile throttled in exit loop ────────────


def test_b3_ghost_reconcile_fires_from_check_exit_conditions(db, monkeypatch):
    """Trade marked OPEN in DB but absent from Alpaca positions must trigger
    `_reconcile_missing_position` from within check_exit_conditions — not wait
    for bot restart.
    """
    from agents.execution_agent import ExecutionAgent

    ea = ExecutionAgent(db=db)
    trade_id = db.save_trade({
        "ticker": "GHOST", "action": "BUY", "quantity": 10,
        "entry_price": 100.0, "stop_loss_price": 95.0,
        "take_profit_price": 110.0, "conviction": 8.0, "order_id": "fake-ord-1",
    })
    assert trade_id > 0

    # Alpaca sees no positions → GHOST is a ghost.
    monkeypatch.setattr(ea, "get_positions", lambda: [])

    called = {"n": 0, "ticker": None}
    def fake_reconcile(trade, exits):
        called["n"] += 1
        called["ticker"] = trade["ticker"]

    monkeypatch.setattr(ea, "_reconcile_missing_position", fake_reconcile)
    ea.check_exit_conditions()
    assert called["n"] == 1
    assert called["ticker"] == "GHOST"


def test_b3_ghost_reconcile_throttles_per_ticker(db, monkeypatch):
    """Second call within the throttle window must NOT re-invoke reconcile —
    that's what kept the old code from fixing this; we want a cleaner retry,
    not a log flood.
    """
    from agents.execution_agent import ExecutionAgent

    ea = ExecutionAgent(db=db)
    db.save_trade({
        "ticker": "GHOST", "action": "BUY", "quantity": 10,
        "entry_price": 100.0, "stop_loss_price": 95.0,
        "take_profit_price": 110.0, "conviction": 8.0, "order_id": "fake-ord-1",
    })
    monkeypatch.setattr(ea, "get_positions", lambda: [])
    calls = {"n": 0}
    monkeypatch.setattr(
        ea, "_reconcile_missing_position",
        lambda t, e: calls.__setitem__("n", calls["n"] + 1),
    )

    ea.check_exit_conditions()
    ea.check_exit_conditions()  # immediately — should be throttled
    assert calls["n"] == 1


# ─────────────────── B4: Reddit comment scan guard ─────────────────────────


def test_b4_viral_reddit_post_skips_comments(monkeypatch):
    """Post with >200 comments must skip the comment tree entirely — this is
    the viral-WSB-DD freeze scenario that killed the bot on 2026-04-15.
    """
    from agents.research_agent import ResearchAgent

    # Build a fake viral post whose .comments access would blow up if called.
    viral_post = MagicMock()
    viral_post.title = "NVDA YOLO $1M"
    viral_post.num_comments = 5000
    viral_post.score = 12345
    viral_post.permalink = "/r/wsb/abc"
    # Accessing viral_post.comments must NOT happen. Make it raise if anyone
    # touches it — that's our trip-wire.
    def _boom(*a, **k):
        raise AssertionError("comments must not be accessed for viral posts")
    type(viral_post).comments = property(_boom)

    fake_sub = MagicMock()
    fake_sub.hot.return_value = [viral_post]

    ra = ResearchAgent.__new__(ResearchAgent)  # bypass __init__ (network calls)
    ra.config = MagicMock(SUBREDDITS=["wallstreetbets"])
    ra.reddit = MagicMock()
    ra.reddit.subreddit.return_value = fake_sub
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    ra.vader = SentimentIntensityAnalyzer()

    result = ra.fetch_reddit_sentiment("NVDA")
    assert result["post_count"] == 1  # the post itself was counted
    # No exception = test passes; the property guard proves comments stayed untouched.


# ─────────────────── B7: SQLite indexes + FK enforcement ───────────────────


def test_b7_expected_indexes_exist(db):
    import sqlite3
    conn = sqlite3.connect(db.db_path)
    names = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        ).fetchall()
    }
    expected = {
        "idx_trades_status",
        "idx_trades_ticker",
        "idx_trades_portfolio",
        "idx_trades_timestamp",
        "idx_analysis_ticker",
        "idx_research_ticker",
    }
    assert expected.issubset(names), f"missing: {expected - names}"


def test_b7_foreign_keys_enforced(db):
    with db._get_conn() as conn:
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1

    # Verify enforcement actually bites: inserting a partial_exit with a
    # nonexistent trade_id should now fail.
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        with db._get_conn() as conn:
            conn.execute(
                "INSERT INTO partial_exits (trade_id, timestamp, quantity, exit_price, "
                "pnl, reason) VALUES (?, ?, ?, ?, ?, ?)",
                (999_999, "2026-04-17T00:00:00", 1, 100.0, 10.0, "test"),
            )
