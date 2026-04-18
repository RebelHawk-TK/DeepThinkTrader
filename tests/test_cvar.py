"""CVaR tests — historical simulation on synthetic return series."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from analytics.cvar import (
    _cvar_of_returns,
    candidate_would_breach_cvar,
    portfolio_cvar,
)
from brokers.base import Bar
from brokers.mock import MockBroker


def _series_with_returns(ticker: str, returns: list[float]) -> list[Bar]:
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(days=len(returns) + 1)
    bars = []
    px = 100.0
    bars.append(Bar(ticker=ticker, timestamp=t0, open=px, high=px, low=px,
                    close=px, volume=1_000_000))
    for i, r in enumerate(returns):
        px *= math.exp(r)
        bars.append(Bar(ticker=ticker, timestamp=t0 + timedelta(days=i + 1),
                        open=px, high=px, low=px, close=px, volume=1_000_000))
    return bars


# ─────────────────────────── _cvar_of_returns ────────────────────────────


def test_cvar_of_returns_is_positive_loss():
    # 20 days: -5% once, -2% four times, 0% the rest.
    returns = [-0.05] + [-0.02] * 4 + [0.0] * 15
    cvar = _cvar_of_returns(returns, alpha=0.10)
    # Worst 10% = 2 days. Average of -0.05 and -0.02 = -0.035 → cvar = 0.035.
    assert 0.03 < cvar < 0.04


def test_cvar_of_flat_series_is_zero():
    assert _cvar_of_returns([0.0] * 20) == 0.0


def test_cvar_of_all_positive_series_floors_at_zero():
    # All positive returns → no losses → CVaR should not be negative.
    assert _cvar_of_returns([0.01] * 20) == 0.0


# ─────────────────────────── portfolio_cvar ────────────────────────────


def test_single_position_cvar_matches_ticker_cvar():
    broker = MockBroker()
    returns = [0.01 if i % 5 != 0 else -0.03 for i in range(60)]  # bad every 5th day
    for b in _series_with_returns("NVDA", returns):
        broker.ingest_bar(b)

    cvar = portfolio_cvar(broker, {"NVDA": 10_000})
    # Worst 5% of 60 days = 3 days, all -3% returns → cvar ≈ 3%.
    assert cvar is not None
    assert 0.025 < cvar < 0.035


def test_diversified_portfolio_cvar_is_lower_than_single():
    """Two tickers with non-identical return streams → portfolio should have
    lower CVaR than the worst-component CVaR (basic diversification)."""
    broker = MockBroker()
    bad_every_5 = [0.01 if i % 5 != 0 else -0.03 for i in range(60)]
    bad_every_7 = [0.01 if i % 7 != 0 else -0.03 for i in range(60)]
    for b in _series_with_returns("A", bad_every_5):
        broker.ingest_bar(b)
    for b in _series_with_returns("B", bad_every_7):
        broker.ingest_bar(b)

    single = portfolio_cvar(broker, {"A": 10_000})
    mixed = portfolio_cvar(broker, {"A": 5_000, "B": 5_000})
    assert mixed is not None and single is not None
    assert mixed <= single


def test_portfolio_cvar_empty_holdings_returns_zero():
    assert portfolio_cvar(MockBroker(), {}) == 0.0


def test_portfolio_cvar_missing_bars_returns_none():
    # Broker has no data for this ticker.
    assert portfolio_cvar(MockBroker(), {"NVDA": 10_000}) is None


# ─────────────────────────── candidate check ─────────────────────────────


def test_candidate_within_limit_passes():
    broker = MockBroker()
    calm = [0.002 if i % 2 == 0 else -0.002 for i in range(60)]
    for b in _series_with_returns("SPY", calm):
        broker.ingest_bar(b)

    breached, cvar = candidate_would_breach_cvar(
        broker=broker, current_holdings={},
        candidate_ticker="SPY", candidate_value=10_000, cvar_limit=0.05,
    )
    assert breached is False
    assert cvar is not None and cvar < 0.05


def test_candidate_breaching_limit_blocks():
    broker = MockBroker()
    # Very spiky series: -8% every 10 days.
    scary = [0.01 if i % 10 != 0 else -0.08 for i in range(60)]
    for b in _series_with_returns("WILD", scary):
        broker.ingest_bar(b)

    breached, cvar = candidate_would_breach_cvar(
        broker=broker, current_holdings={},
        candidate_ticker="WILD", candidate_value=10_000, cvar_limit=0.05,
    )
    assert breached is True
    assert cvar is not None and cvar > 0.05


# ─────────────────────── RiskManager integration ─────────────────────────


def test_risk_manager_cvar_check_no_broker_passes(risk_manager):
    assert risk_manager.check_cvar_limit(
        candidate_ticker="NVDA", entry_value=10_000, broker=None,
    ) is True


def test_risk_manager_cvar_check_blocks_on_spiky_candidate(risk_manager, db):
    broker = MockBroker()
    scary = [0.01 if i % 10 != 0 else -0.08 for i in range(60)]
    for b in _series_with_returns("WILD", scary):
        broker.ingest_bar(b)
    allowed = risk_manager.check_cvar_limit(
        candidate_ticker="WILD", entry_value=10_000, broker=broker, cvar_limit=0.05,
    )
    assert allowed is False


def test_risk_manager_cvar_check_passes_for_calm_candidate(risk_manager, db):
    broker = MockBroker()
    calm = [0.002 if i % 2 == 0 else -0.002 for i in range(60)]
    for b in _series_with_returns("CALM", calm):
        broker.ingest_bar(b)
    allowed = risk_manager.check_cvar_limit(
        candidate_ticker="CALM", entry_value=10_000, broker=broker, cvar_limit=0.05,
    )
    assert allowed is True
