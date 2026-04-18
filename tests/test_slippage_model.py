"""Slippage model tests."""
from __future__ import annotations

from analytics.slippage_model import MIN_SAMPLES, fit_slippage


def _seed(db, ticker: str, side: str, slippage_pct: float, shares: int, n: int = 1) -> None:
    for _ in range(n):
        db.save_slippage(
            ticker=ticker, expected_price=100.0,
            filled_price=100.0 * (1 + slippage_pct / 100),
            shares=shares, side=side, order_type="market",
        )


def test_empty_db_returns_default_globals(db):
    fit = fit_slippage(db)
    # No data → defaults shouldn't be zero (that would be a free lunch).
    assert fit.estimate_bps("NVDA", "buy", 100) >= 5.0


def test_per_ticker_estimate_uses_ticker_mean_when_enough_samples(db):
    # 15 buys at +3% (= 300 bps cost) for NVDA — enough to cross MIN_SAMPLES.
    _seed(db, "NVDA", "buy", 3.0, 100, n=MIN_SAMPLES + 5)
    fit = fit_slippage(db)
    est = fit.estimate_bps("NVDA", "buy", 100)
    # Should be near 300 bps (allowing a bit for median_shares=100 → 0 size inflation).
    assert 250 <= est <= 350


def test_unseen_ticker_falls_back_to_global_mean(db):
    _seed(db, "AAPL", "buy", 2.0, 100, n=MIN_SAMPLES + 5)  # 200 bps
    fit = fit_slippage(db)
    # NVDA never seen — use global.
    est_global = fit.estimate_bps("NVDA", "buy", 100)
    est_aapl = fit.estimate_bps("AAPL", "buy", 100)
    # Global should land near AAPL's 200 bps (only data we have).
    assert abs(est_global - est_aapl) < 50


def test_sell_slippage_sign_flip(db):
    # Sells that filled below expected → slippage_pct is negative but the
    # cost to us is positive bps.
    _seed(db, "NVDA", "sell", -1.5, 100, n=MIN_SAMPLES + 2)  # -1.5% = 150 bps cost
    fit = fit_slippage(db)
    est = fit.estimate_bps("NVDA", "sell", 100)
    assert 100 <= est <= 200


def test_larger_orders_inflate_estimate(db):
    # Fit a ticker at median 100 shares.
    _seed(db, "NVDA", "buy", 1.0, 100, n=MIN_SAMPLES + 5)  # 100 bps
    fit = fit_slippage(db)
    small = fit.estimate_bps("NVDA", "buy", 100)
    big = fit.estimate_bps("NVDA", "buy", 1000)  # 10× median = ~3.3 doublings
    assert big > small
    # Expect +2 bps per doubling = +6.6 bps above the 100 bps base
    assert 105 <= big <= 115


def test_returns_are_always_positive(db):
    # Edge case: a ticker that had positive slippage (got a better fill).
    # The model still must return a non-negative cost estimate.
    _seed(db, "FLOOR", "buy", -0.5, 100, n=MIN_SAMPLES + 1)  # free fills
    fit = fit_slippage(db)
    assert fit.estimate_bps("FLOOR", "buy", 100) >= 0.0
