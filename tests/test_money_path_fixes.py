"""Money-path fixes from the 2026-06-09 full code review.

Four bugs, four fix groups:
1. trades.pnl excluded partial-exit P&L — a scaled-out winner recorded as a loss,
   corrupting Kelly stats, edge_performance, auto-pause, and revenge detection.
2. Penny limit orders were saved as filled trades immediately, with no fill
   polling — unfilled orders became ghost rows that reconcile later closed at
   a yfinance price (fabricated P&L).
3. No client_order_id on order submission — a POST that timed out after Alpaca
   accepted it left an untracked position (no stop/TP ever) and allowed
   double-buys. Reconcile was also one-directional (DB→Alpaca only).
4. Exits recorded the pre-close snapshot quote, not the actual fill; the
   alpaca_reconcile_retry path never wrote daily_pnl at all.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from agents.execution_agent import ExecutionAgent


@pytest.fixture
def agent(db, test_user_id):
    return ExecutionAgent(
        user_id=test_user_id, api_key="test-key", secret_key="test-secret", db=db
    )


def _seed_trade(db, user_id, ticker="ABC", qty=90, entry=10.0, portfolio="main"):
    return db.save_trade(
        user_id,
        {
            "ticker": ticker,
            "action": "BUY",
            "quantity": qty,
            "entry_price": entry,
            "stop_loss_price": entry * 0.95,
            "take_profit_price": entry * 1.1,
            "conviction": 7.0,
            "order_id": "ord-1",
            "reasoning": "test",
            "source": "ALGO",
        },
        portfolio=portfolio,
    )


# ── Fix 1: trades.pnl includes partial-exit P&L ──────────────────────────────

def test_close_trade_includes_partial_exit_pnl(db, test_user_id):
    trade_id = _seed_trade(db, test_user_id)
    db.save_partial_exit(trade_id, 30, 13.5, 100.0, reason="scale_out_1R")
    db.close_trade(trade_id, 9.5, -30.0, exit_reason="stop_loss")

    with db._get_conn() as conn:
        row = conn.execute("SELECT pnl FROM trades WHERE id = ?", (trade_id,)).fetchone()
        ep = conn.execute(
            "SELECT pnl, won FROM edge_performance WHERE trade_id = ?", (trade_id,)
        ).fetchone()
    # 100 (partial) + (-30) (final leg) = +70: the trade was a WINNER.
    assert row["pnl"] == 70.0
    assert ep["pnl"] == 70.0
    assert ep["won"] == 1


def test_close_trade_without_partials_unchanged(db, test_user_id):
    trade_id = _seed_trade(db, test_user_id)
    db.close_trade(trade_id, 11.0, 90.0, exit_reason="take_profit")
    with db._get_conn() as conn:
        row = conn.execute("SELECT pnl FROM trades WHERE id = ?", (trade_id,)).fetchone()
    assert row["pnl"] == 90.0


# ── Fix 2: limit-order entries record only actual fills ─────────────────────

def _order_json(status, filled_qty, filled_price, order_id="o-1"):
    return {
        "id": order_id,
        "status": status,
        "filled_qty": str(filled_qty),
        "filled_avg_price": str(filled_price) if filled_price else None,
    }


def test_poll_order_status_timeout_returns_observed_fills(agent):
    resp = MagicMock(ok=True)
    resp.json.return_value = _order_json("partially_filled", 40, 2.5)
    agent._session.get = MagicMock(return_value=resp)

    result = agent._poll_order_status("o-1", "ABC", 100, timeout_seconds=1)
    # Timeout must report what actually filled, not pretend zero.
    assert result["filled_qty"] == 40
    assert result["filled_price"] == 2.5


def test_settle_limit_entry_unfilled_cancels_and_reports_zero(agent, monkeypatch):
    monkeypatch.setattr(
        agent, "_poll_order_status",
        lambda *a, **k: {"status": "accepted", "filled_qty": 0, "filled_price": 0.0, "order_id": "o-1"},
    )
    cancel = MagicMock(return_value=True)
    monkeypatch.setattr(agent, "_cancel_order", cancel)
    monkeypatch.setattr(
        agent, "_final_order_state",
        lambda order_id: {"status": "canceled", "filled_qty": 0, "filled_price": 0.0},
    )
    fill = agent._settle_limit_entry("o-1", "ABC", 100)
    assert fill["filled_qty"] == 0
    cancel.assert_called_once()


def test_settle_limit_entry_partial_fill_reports_actual(agent, monkeypatch):
    monkeypatch.setattr(
        agent, "_poll_order_status",
        lambda *a, **k: {"status": "partially_filled", "filled_qty": 60, "filled_price": 2.1, "order_id": "o-1"},
    )
    monkeypatch.setattr(agent, "_cancel_order", MagicMock(return_value=True))
    # After cancel, the final state shows one more racing fill.
    monkeypatch.setattr(
        agent, "_final_order_state",
        lambda order_id: {"status": "canceled", "filled_qty": 65, "filled_price": 2.12},
    )
    fill = agent._settle_limit_entry("o-1", "ABC", 100)
    assert fill["filled_qty"] == 65
    assert fill["filled_price"] == 2.12


# ── Fix 3: client_order_id idempotency + reverse reconcile ──────────────────

def test_submit_order_sets_client_order_id(agent):
    resp = MagicMock(ok=True, status_code=200, headers={})
    resp.json.return_value = {"id": "o-9"}
    post = MagicMock(return_value=resp)
    agent._session.post = post

    order, _ = agent._submit_order(
        {"symbol": "ABC", "qty": "5", "side": "buy", "type": "market", "time_in_force": "day"},
        "ABC",
    )
    sent = post.call_args.kwargs["json"]
    assert sent["client_order_id"].startswith("dtt")
    assert order["id"] == "o-9"


def test_submit_order_recovers_accepted_order_on_timeout(agent):
    agent._session.post = MagicMock(side_effect=requests.Timeout("read timeout"))
    lookup = MagicMock(ok=True)
    lookup.json.return_value = {"id": "o-recovered", "status": "accepted"}
    agent._session.get = MagicMock(return_value=lookup)

    order, request_id = agent._submit_order(
        {"symbol": "ABC", "qty": "5", "side": "buy", "type": "market", "time_in_force": "day"},
        "ABC",
    )
    assert order["id"] == "o-recovered"
    # The lookup must query by the same client_order_id that was sent.
    called_params = agent._session.get.call_args.kwargs["params"]
    assert called_params["client_order_id"].startswith("dtt")


def test_submit_order_raises_when_order_truly_lost(agent):
    agent._session.post = MagicMock(side_effect=requests.Timeout("read timeout"))
    agent._session.get = MagicMock(return_value=MagicMock(ok=False, status_code=404))
    with pytest.raises(requests.Timeout):
        agent._submit_order(
            {"symbol": "ABC", "qty": "5", "side": "buy", "type": "market", "time_in_force": "day"},
            "ABC",
        )


def test_reconcile_warns_on_unmanaged_alpaca_position(agent, monkeypatch, caplog):
    monkeypatch.setattr(
        agent, "get_positions",
        lambda: [{"ticker": "ZZZ", "quantity": 10, "current_price": 5.0, "unrealized_pnl": 0.0}],
    )
    import logging
    with caplog.at_level(logging.ERROR):
        agent.reconcile_open_trades()
    assert "UNMANAGED" in caplog.text
    assert "ZZZ" in caplog.text


# ── Fix 4: exits record actual fills, not pre-close quotes ──────────────────

def test_resolve_exit_fill_uses_fill_price(agent, monkeypatch):
    monkeypatch.setattr(
        agent, "_poll_order_status",
        lambda *a, **k: {"status": "filled", "filled_qty": 10, "filled_price": 9.5, "order_id": "x"},
    )
    close_resp = MagicMock()
    close_resp.json.return_value = {"id": "x"}
    price, pnl = agent._resolve_exit_fill(
        close_resp, "ABC", entry=10.0, qty=10, is_long=True,
        fallback_price=9.0, fallback_pnl=-10.0,
    )
    assert price == 9.5
    assert pnl == -5.0


def test_resolve_exit_fill_falls_back_to_snapshot(agent):
    close_resp = MagicMock()
    close_resp.json.side_effect = ValueError("no body")
    price, pnl = agent._resolve_exit_fill(
        close_resp, "ABC", entry=10.0, qty=10, is_long=True,
        fallback_price=9.0, fallback_pnl=-10.0,
    )
    assert price == 9.0
    assert pnl == -10.0


def test_reconcile_retry_path_updates_daily_pnl(agent, db, test_user_id, monkeypatch):
    trade_id = _seed_trade(db, test_user_id, ticker="GHO", qty=10, entry=5.0)
    trade = {"id": trade_id, "ticker": "GHO", "entry_price": 5.0, "quantity": 10, "action": "BUY"}

    # Force the primary path to fail (orders query raises) -> retry path runs.
    agent._session.get = MagicMock(side_effect=requests.ConnectionError("down"))
    import utils.yahoo_fundamentals as yfu
    monkeypatch.setattr(yfu, "_yf_with_timeout", lambda *a, **k: None)
    monkeypatch.setattr("time.sleep", lambda s: None)

    exits: list = []
    agent._reconcile_missing_position(trade, exits)

    assert exits and exits[0]["reason"] == "alpaca_reconcile_retry"
    today = db.get_today_pnl(test_user_id)
    assert today["trades_taken"] == 1  # retry close now reaches the daily ledger
