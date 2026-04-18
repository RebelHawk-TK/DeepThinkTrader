"""MockBroker behavioral tests — the new code consumer of IBroker."""
from __future__ import annotations

from datetime import datetime, timedelta

from brokers import Bar
from brokers.mock import MockBroker


def _bar(ticker: str, t: datetime, px: float, vol: int = 1_000_000) -> Bar:
    return Bar(ticker=ticker, timestamp=t, open=px, high=px * 1.01,
               low=px * 0.99, close=px, volume=vol)


# ─────────────────────────── Fills ─────────────────────────────────────────


def test_market_buy_fills_at_current_bar_close():
    b = MockBroker(starting_cash=100_000)
    t = datetime(2026, 1, 2)
    b.ingest_bar(_bar("NVDA", t, 900.0))
    order = b.submit_order("NVDA", qty=10, side="buy")
    assert order.status == "filled"
    assert order.filled_avg_price == 900.0
    pos = b.get_position("NVDA")
    assert pos.qty == 10
    assert pos.avg_entry_price == 900.0


def test_market_sell_realizes_pnl_and_clears_position():
    b = MockBroker(100_000)
    t = datetime(2026, 1, 2)
    b.ingest_bar(_bar("NVDA", t, 900.0))
    b.submit_order("NVDA", 10, "buy")
    b.ingest_bar(_bar("NVDA", t + timedelta(days=1), 950.0))
    b.submit_order("NVDA", 10, "sell")
    assert b.get_position("NVDA") is None
    # (950-900) × 10 = 500 realized
    assert b.realized_pnl == 500.0


def test_limit_buy_fills_only_when_price_crosses():
    b = MockBroker(100_000)
    t = datetime(2026, 1, 2)
    b.ingest_bar(_bar("NVDA", t, 900.0))
    order = b.submit_order("NVDA", 10, "buy", order_type="limit", limit_price=850.0)
    assert order.status == "pending"  # price above limit, no fill

    # Next bar dips to 840 — should fill at limit (or below).
    dip = Bar(ticker="NVDA", timestamp=t + timedelta(days=1), open=860.0,
              high=865.0, low=840.0, close=855.0, volume=1_000_000)
    b.ingest_bar(dip)
    order = b.get_order(order.id)
    assert order.status == "filled"
    assert order.filled_avg_price <= 850.0


def test_submit_order_validates_inputs():
    b = MockBroker()
    import pytest
    with pytest.raises(ValueError):
        b.submit_order("NVDA", 0, "buy")
    with pytest.raises(ValueError):
        b.submit_order("NVDA", 10, "buy", order_type="limit")  # missing limit_price


# ─────────────────────────── Account / positions ──────────────────────────


def test_account_equity_reflects_position_value():
    b = MockBroker(100_000)
    t = datetime(2026, 1, 2)
    b.ingest_bar(_bar("NVDA", t, 100.0))
    b.submit_order("NVDA", 100, "buy")  # -$10k cash, +$10k position
    acct = b.get_account()
    assert acct.cash == 90_000
    assert acct.equity == 100_000

    # Mark-to-market on next bar
    b.ingest_bar(_bar("NVDA", t + timedelta(days=1), 110.0))
    acct = b.get_account()
    assert acct.equity == 101_000  # +$1000 unrealized


def test_cancel_order_removes_from_open_queue():
    b = MockBroker(100_000)
    t = datetime(2026, 1, 2)
    b.ingest_bar(_bar("NVDA", t, 900.0))
    order = b.submit_order("NVDA", 10, "buy", order_type="limit", limit_price=500.0)
    assert b.cancel_order(order.id) is True
    assert b.get_order(order.id).status == "cancelled"
    # Subsequent bars shouldn't accidentally fill it.
    dip = Bar(ticker="NVDA", timestamp=t + timedelta(days=1), open=400.0,
              high=450.0, low=380.0, close=420.0, volume=1_000_000)
    b.ingest_bar(dip)
    assert b.get_position("NVDA") is None


def test_get_bars_returns_history_window():
    b = MockBroker()
    t0 = datetime(2026, 1, 2)
    for i in range(10):
        b.ingest_bar(_bar("NVDA", t0 + timedelta(days=i), 100.0 + i))
    window = b.get_bars("NVDA", t0 + timedelta(days=2), t0 + timedelta(days=5))
    assert len(window) == 4
    assert window[0].close == 102.0
    assert window[-1].close == 105.0


# ─────────────────────────── Protocol conformance ─────────────────────────


def test_mock_satisfies_ibroker_protocol():
    """Duck-typing check: MockBroker has the surface IBroker declares."""
    from brokers import IBroker
    b = MockBroker()
    # Protocols support isinstance() when runtime_checkable — IBroker isn't
    # decorated that way, so just assert the methods exist and are callable.
    required = ["get_account", "get_positions", "get_position", "get_bars",
                "submit_order", "cancel_order", "get_order"]
    for name in required:
        assert callable(getattr(b, name)), f"MockBroker missing {name}"
    # And the Alpaca implementation too.
    from brokers.alpaca import AlpacaBroker
    for name in required:
        assert callable(getattr(AlpacaBroker, name)), f"AlpacaBroker missing {name}"
    _ = IBroker  # silence unused-import
