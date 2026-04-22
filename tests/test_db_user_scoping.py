"""User-scoping invariants for the database layer.

After migration 0004 every tenant-owned write carries a user_id, and every
read filters by it. These tests assert the happy-path: user A's writes are
invisible to user B's queries.
"""
from __future__ import annotations

import pytest


@pytest.fixture
def two_users(db):
    """Create two user rows; return their ids."""
    with db._get_conn() as conn:
        cur_a = conn.execute(
            "INSERT INTO users (email, role, enabled) VALUES (?, 'admin', 1)",
            ("alice@example.com",),
        )
        cur_b = conn.execute(
            "INSERT INTO users (email, role, enabled) VALUES (?, 'user', 1)",
            ("bob@example.com",),
        )
        return cur_a.lastrowid, cur_b.lastrowid


def test_trades_scoped_per_user(db, two_users):
    alice, bob = two_users

    db.save_trade(alice, {"ticker": "AAPL", "action": "BUY", "quantity": 10}, portfolio="main")
    db.save_trade(bob, {"ticker": "MSFT", "action": "BUY", "quantity": 5}, portfolio="main")

    alice_trades = db.get_recent_trades(alice)
    bob_trades = db.get_recent_trades(bob)

    assert {t["ticker"] for t in alice_trades} == {"AAPL"}
    assert {t["ticker"] for t in bob_trades} == {"MSFT"}


def test_open_trades_scoped_per_user(db, two_users):
    alice, bob = two_users

    db.save_trade(alice, {"ticker": "AAPL", "action": "BUY", "quantity": 10})
    db.save_trade(bob, {"ticker": "MSFT", "action": "BUY", "quantity": 5})

    assert len(db.get_open_trades(alice)) == 1
    assert len(db.get_open_trades(bob)) == 1
    assert db.get_open_trades(alice)[0]["ticker"] == "AAPL"
    assert db.get_open_trades(bob)[0]["ticker"] == "MSFT"


def test_analyses_scoped_per_user(db, two_users):
    alice, bob = two_users

    db.save_analysis(alice, {"ticker": "AAPL", "action": "BUY", "conviction": 8.0})
    db.save_analysis(bob, {"ticker": "MSFT", "action": "SELL", "conviction": 6.5})

    alice_rows = db.get_recent_analyses(alice)
    bob_rows = db.get_recent_analyses(bob)

    assert {r["ticker"] for r in alice_rows} == {"AAPL"}
    assert {r["ticker"] for r in bob_rows} == {"MSFT"}


def test_was_recently_analyzed_isolated(db, two_users):
    alice, bob = two_users

    db.save_analysis(alice, {"ticker": "TSLA", "action": "BUY", "conviction": 7.0})

    assert db.was_recently_analyzed(alice, "TSLA") is True
    assert db.was_recently_analyzed(bob, "TSLA") is False


def test_daily_pnl_per_user(db, two_users):
    alice, bob = two_users

    db.update_daily_pnl(alice, 100.0, won=True)
    db.update_daily_pnl(bob, -50.0, won=False)

    assert db.get_today_pnl(alice)["realized_pnl"] == 100.0
    assert db.get_today_pnl(bob)["realized_pnl"] == -50.0


def test_strategy_stats_scoped_per_user(db, two_users):
    alice, bob = two_users

    alice_trade = db.save_trade(alice, {"ticker": "AAPL", "action": "BUY", "quantity": 10})
    db.close_trade(alice_trade, exit_price=110, pnl=100, exit_reason="tp")

    bob_trade = db.save_trade(bob, {"ticker": "MSFT", "action": "BUY", "quantity": 5})
    db.close_trade(bob_trade, exit_price=90, pnl=-50, exit_reason="sl")

    alice_stats = db.get_strategy_stats(alice, portfolio="main")
    bob_stats = db.get_strategy_stats(bob, portfolio="main")

    assert alice_stats["trade_count"] == 1
    assert bob_stats["trade_count"] == 1
    assert alice_stats["win_rate"] == 1.0
    assert bob_stats["win_rate"] == 0.0


def test_get_active_user_ids_requires_both_enabled_and_keys(db, two_users, monkeypatch):
    """Active users must be enabled AND have a user_secrets row."""
    from cryptography.fernet import Fernet

    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())

    alice, bob = two_users

    # Alice has keys, Bob does not.
    from utils import secrets_vault
    secrets_vault.set_alpaca_keys(alice, "PKALICE1234ABCD", "secret-a")

    active = db.get_active_user_ids()
    assert alice in active
    assert bob not in active


def test_close_trade_preserves_user_id_on_edge_performance(db, two_users):
    """close_trade writes an edge_performance row; it must inherit user_id
    from the trade (not from some ambient default)."""
    alice, _ = two_users

    trade_id = db.save_trade(
        alice,
        {"ticker": "NVDA", "action": "BUY", "quantity": 10,
         "entry_price": 100, "conviction": 7.5},
    )
    # Populate edge_details JSON so close_trade writes an edge_performance row.
    with db._get_conn() as conn:
        conn.execute(
            "UPDATE trades SET edges_fired = 2, edge_details = ? WHERE id = ?",
            (
                '[{"label":"Fundamental","passed":true},{"label":"Technical","passed":true}]',
                trade_id,
            ),
        )

    db.close_trade(trade_id, exit_price=120, pnl=200, exit_reason="tp")

    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM edge_performance WHERE trade_id = ?",
            (trade_id,),
        ).fetchone()

    assert row is not None
    assert row["user_id"] == alice
