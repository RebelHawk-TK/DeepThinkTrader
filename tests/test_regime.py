"""Regime classifier tests — uses MockBroker so nothing touches Alpaca."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from analytics.regime import (
    HIGH_VOL_THRESHOLD,
    LOW_VOL_THRESHOLD,
    classify_regime,
)
from brokers.base import Bar
from brokers.mock import MockBroker


def _spy_series(daily_return_std: float, n: int = 30) -> list[Bar]:
    """Synthesize SPY bars with a given daily return stddev.

    Uses deterministic alternating returns (+σ, -σ) so tests are stable
    without a seeded RNG dependency.
    """
    start = datetime(2026, 3, 1, tzinfo=timezone.utc)
    bars = []
    price = 500.0
    for i in range(n):
        r = daily_return_std * (1 if i % 2 == 0 else -1)
        price *= math.exp(r)
        bars.append(Bar(
            ticker="SPY", timestamp=start + timedelta(days=i),
            open=price, high=price * 1.001, low=price * 0.999,
            close=price, volume=10_000_000,
        ))
    return bars


def test_low_vol_regime_recommends_aggressive():
    # 0.3% daily σ → annualized ≈ 4.8%, well below LOW threshold.
    broker = MockBroker()
    for b in _spy_series(daily_return_std=0.003, n=30):
        broker.ingest_bar(b)
    assessment = classify_regime(broker)
    assert assessment.label == "low"
    assert assessment.recommended_mode == "aggressive"
    assert assessment.annualized_vol < LOW_VOL_THRESHOLD


def test_normal_vol_regime_recommends_normal():
    # 1.0% daily σ → annualized ≈ 15.9%, in NORMAL band.
    broker = MockBroker()
    for b in _spy_series(daily_return_std=0.010, n=30):
        broker.ingest_bar(b)
    assessment = classify_regime(broker)
    assert assessment.label == "normal"
    assert assessment.recommended_mode == "normal"
    assert LOW_VOL_THRESHOLD <= assessment.annualized_vol <= HIGH_VOL_THRESHOLD


def test_high_vol_regime_recommends_safe():
    # 2.0% daily σ → annualized ≈ 31.7%, above HIGH threshold.
    broker = MockBroker()
    for b in _spy_series(daily_return_std=0.020, n=30):
        broker.ingest_bar(b)
    assessment = classify_regime(broker)
    assert assessment.label == "high"
    assert assessment.recommended_mode == "safe"
    assert assessment.annualized_vol > HIGH_VOL_THRESHOLD


def test_insufficient_data_defaults_to_normal():
    broker = MockBroker()
    for b in _spy_series(daily_return_std=0.01, n=3):
        broker.ingest_bar(b)
    assessment = classify_regime(broker)
    assert assessment.label == "unknown"
    assert assessment.recommended_mode == "normal"


def test_broker_error_defaults_to_normal():
    class ExplodingBroker:
        def get_bars(self, *a, **k):
            raise RuntimeError("Alpaca down")

    assessment = classify_regime(ExplodingBroker())
    assert assessment.label == "unknown"
    assert assessment.recommended_mode == "normal"
    assert assessment.n_bars == 0


def test_describe_is_human_readable():
    broker = MockBroker()
    for b in _spy_series(daily_return_std=0.010, n=30):
        broker.ingest_bar(b)
    out = classify_regime(broker).describe()
    assert "regime=" in out
    assert "vol=" in out
    assert "recommend" in out
