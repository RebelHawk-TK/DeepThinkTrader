"""Correlation-aware sizing tests. Uses MockBroker with synthetic return
series so we can dial the true correlation up and down."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from analytics.correlation import (
    HIGH_CORR_MULTIPLIER,
    MODERATE_CORR_MULTIPLIER,
    average_correlation,
    correlation_size_multiplier,
)
from brokers.base import Bar
from brokers.mock import MockBroker


def _series_with_returns(ticker: str, returns: list[float], start_px: float = 100.0) -> list[Bar]:
    """Build a Bar series whose close-to-close log returns match `returns`.

    Timestamps end at "now" so they fall inside the correlation lookback
    window (default 60 days) regardless of when the test runs.
    """
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(days=len(returns) + 1)
    bars = []
    px = start_px
    bars.append(Bar(ticker=ticker, timestamp=t0, open=px, high=px * 1.001,
                    low=px * 0.999, close=px, volume=1_000_000))
    for i, r in enumerate(returns):
        px *= math.exp(r)
        bars.append(Bar(ticker=ticker, timestamp=t0 + timedelta(days=i + 1),
                        open=px, high=px * 1.001, low=px * 0.999,
                        close=px, volume=1_000_000))
    return bars


def test_perfectly_correlated_series_returns_near_1():
    """Two tickers with identical returns → correlation ≈ 1."""
    returns = [0.01 if i % 2 == 0 else -0.01 for i in range(30)]
    broker = MockBroker()
    for b in _series_with_returns("NVDA", returns):
        broker.ingest_bar(b)
    for b in _series_with_returns("AMD", returns):
        broker.ingest_bar(b)

    corr = average_correlation(broker, candidate="NVDA", held_tickers=["AMD"])
    assert corr is not None
    assert corr > 0.99


def test_anticorrelated_series_returns_near_minus_1():
    ups = [0.01 if i % 2 == 0 else -0.01 for i in range(30)]
    downs = [-r for r in ups]
    broker = MockBroker()
    for b in _series_with_returns("SPY", ups):
        broker.ingest_bar(b)
    for b in _series_with_returns("SH", downs):  # inverse SPY
        broker.ingest_bar(b)

    corr = average_correlation(broker, candidate="SPY", held_tickers=["SH"])
    assert corr is not None
    assert corr < -0.99


def test_empty_held_list_returns_none():
    broker = MockBroker()
    for b in _series_with_returns("NVDA", [0.01] * 20):
        broker.ingest_bar(b)
    assert average_correlation(broker, candidate="NVDA", held_tickers=[]) is None


def test_candidate_in_held_list_is_skipped():
    broker = MockBroker()
    returns = [0.01 if i % 2 == 0 else -0.01 for i in range(30)]
    for b in _series_with_returns("NVDA", returns):
        broker.ingest_bar(b)
    # Only self in held — nothing to correlate against.
    assert average_correlation(broker, candidate="NVDA", held_tickers=["NVDA"]) is None


def test_short_history_returns_none_gracefully():
    broker = MockBroker()
    for b in _series_with_returns("NEWIPO", [0.01, -0.01, 0.02]):
        broker.ingest_bar(b)
    for b in _series_with_returns("SPY", [0.01 if i % 2 == 0 else -0.01 for i in range(30)]):
        broker.ingest_bar(b)
    # NEWIPO has only 3 returns, below the 5-obs floor → None.
    assert average_correlation(broker, candidate="NEWIPO", held_tickers=["SPY"]) is None


# ─────────────────────── Multiplier mapping ────────────────────────


def test_multiplier_thresholds():
    assert correlation_size_multiplier(0.9) == HIGH_CORR_MULTIPLIER   # > 0.6
    assert correlation_size_multiplier(0.5) == MODERATE_CORR_MULTIPLIER  # 0.4-0.6
    assert correlation_size_multiplier(0.2) == 1.0  # below threshold
    assert correlation_size_multiplier(-0.5) == 1.0  # negative corr → full size
    assert correlation_size_multiplier(None) == 1.0  # unknown → full size


# ─────────────────────── RiskManager integration ───────────────────


def test_risk_manager_applies_correlation_multiplier_when_broker_given(risk_manager, db, test_user_id):
    """With a mocked broker returning high correlation, position size shrinks."""
    from brokers.mock import MockBroker

    returns = [0.01 if i % 2 == 0 else -0.01 for i in range(30)]
    broker = MockBroker()
    for b in _series_with_returns("NVDA", returns):
        broker.ingest_bar(b)
    for b in _series_with_returns("AMD", returns):
        broker.ingest_bar(b)

    # Seed an existing position so "held_tickers" is non-empty.
    db.save_trade(test_user_id, {
        "ticker": "AMD", "action": "BUY", "quantity": 10,
        "entry_price": 100.0, "stop_loss_price": 95.0,
        "take_profit_price": 110.0, "conviction": 8.0, "order_id": "ord-amd",
    })

    shares_no_corr = risk_manager.calculate_position_size(
        account_value=100_000, entry_price=100.0, stop_loss_pct=4.0, portfolio="main",
    )
    shares_with_corr = risk_manager.calculate_position_size(
        account_value=100_000, entry_price=100.0, stop_loss_pct=4.0, portfolio="main",
        ticker="NVDA", broker=broker,
    )
    assert shares_with_corr < shares_no_corr
    # Specifically, high-corr multiplier is 0.5x on risk → roughly half the shares.
    assert shares_with_corr <= shares_no_corr * 0.55 + 1


def test_risk_manager_no_broker_means_no_correlation_penalty(risk_manager):
    shares_baseline = risk_manager.calculate_position_size(
        account_value=100_000, entry_price=100.0, stop_loss_pct=4.0, portfolio="main",
    )
    shares_no_broker = risk_manager.calculate_position_size(
        account_value=100_000, entry_price=100.0, stop_loss_pct=4.0, portfolio="main",
        ticker="NVDA", broker=None,
    )
    assert shares_baseline == shares_no_broker
