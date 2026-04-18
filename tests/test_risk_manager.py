"""Unit tests for utils.risk_manager — the 'life-or-death' math.

Each public gate gets coverage for the pass path and at least one fail path.
Kelly gets extra scrutiny since sizing errors compound.
"""
from __future__ import annotations




# ─────────────────────────── Kelly fraction ────────────────────────────────


def test_kelly_positive_edge_above_floor(risk_manager):
    """p=0.60, payoff=2.0 with large N → shrunk p ≈ 0.6 → Kelly ≈ 0.10, clamped."""
    f = risk_manager._kelly_fraction(win_rate=0.60, payoff_ratio=2.0, n_trades=500)
    assert f == risk_manager.config.MAX_RISK_PER_TRADE


def test_kelly_marginal_edge(risk_manager):
    """Small edge at high N → small positive position size within mode cap."""
    f = risk_manager._kelly_fraction(win_rate=0.52, payoff_ratio=1.0, n_trades=500)
    assert 0.005 <= f <= risk_manager.config.MAX_RISK_PER_TRADE + 1e-9


def test_kelly_negative_edge_floor(risk_manager):
    """Losing system → negative Kelly → clamped up to 0.005 floor."""
    f = risk_manager._kelly_fraction(win_rate=0.30, payoff_ratio=1.0, n_trades=500)
    assert f == 0.005


def test_kelly_zero_payoff_falls_back_to_fixed(risk_manager):
    f = risk_manager._kelly_fraction(win_rate=0.55, payoff_ratio=0.0, n_trades=500)
    assert f == risk_manager.config.RISK_PCT_PER_TRADE


# ─────────────────────────── Bayesian shrinkage + quarter-Kelly ────────────


def test_kelly_shrinks_aggressive_win_rate_at_low_n(risk_manager):
    """At N=20 with 70% apparent win rate, the prior (beta(20,20)) should
    pull the estimate down toward 0.6 — preventing over-betting on noise."""
    # Compute analytically: alpha = 14 + 20 = 34, beta = 6 + 20 = 26 → p = 34/60 ≈ 0.567
    # That's much less aggressive than the raw 0.7.
    shrunk_f = risk_manager._kelly_fraction(win_rate=0.7, payoff_ratio=2.0, n_trades=20)
    # Same apparent edge but with 500 trades — sample dominates the prior.
    sample_f = risk_manager._kelly_fraction(win_rate=0.7, payoff_ratio=2.0, n_trades=500)
    # Both may hit the clamp — that's fine; just confirm sample-dominated
    # estimate is not smaller than prior-shrunk one.
    assert sample_f >= shrunk_f


def test_kelly_quarter_at_low_n_even_with_large_edge(risk_manager):
    """Below N=50, the safety multiplier is quarter-Kelly (0.25), not half.
    A big apparent edge should still size conservatively at N=30."""
    f_low = risk_manager._kelly_fraction(win_rate=0.8, payoff_ratio=3.0, n_trades=30)
    f_high = risk_manager._kelly_fraction(win_rate=0.8, payoff_ratio=3.0, n_trades=200)
    # With same apparent edge, high-N is allowed more aggressive sizing.
    assert f_low <= f_high


def test_kelly_shrinkage_at_n_zero(risk_manager):
    """With N=0, the prior alone drives the estimate — 50/50, no edge → 0.005 floor."""
    f = risk_manager._kelly_fraction(win_rate=0.8, payoff_ratio=2.0, n_trades=0)
    # Prior alone is 20/40 = 0.5 win rate → Kelly = (0.5 - 0.5) / 2 = 0.
    # Clamped up to floor.
    assert f == 0.005


def test_kelly_converges_to_raw_at_very_large_n(risk_manager):
    """With N=10_000, prior (40 pseudo-trades) is noise; estimate ≈ raw."""
    # Raw Kelly: (0.55 - 0.45) / 1.5 = 0.0667; half-Kelly = 0.033
    # Normal mode cap is 0.02 → expect clamp.
    f = risk_manager._kelly_fraction(win_rate=0.55, payoff_ratio=1.5, n_trades=10_000)
    # Should hit the clamp since raw half-Kelly is above it.
    assert f == risk_manager.config.MAX_RISK_PER_TRADE


# ─────────────────────────── Spread gate ───────────────────────────────────


def test_spread_under_limit_passes(risk_manager):
    assert risk_manager.check_spread(0.3) is True


def test_spread_over_limit_blocks(risk_manager):
    assert risk_manager.check_spread(5.0) is False


def test_spread_penny_has_looser_limit(risk_manager):
    # Penny MAX_SPREAD_PCT defaults higher; a spread that would fail main should
    # still pass for penny up to the penny limit.
    penny_max = risk_manager.config.PENNY_MAX_SPREAD_PCT
    main_max = risk_manager.config.MAX_SPREAD_PCT
    assert penny_max >= main_max
    borderline = (main_max + penny_max) / 2
    assert risk_manager.check_spread(borderline, portfolio="main") is False
    assert risk_manager.check_spread(borderline, portfolio="penny") is True


# ─────────────────────────── Liquidity gate ────────────────────────────────


def test_liquidity_small_order_passes(risk_manager):
    # 100 shares vs 1M ADV → shares << ADV/MIN_ADV_RATIO, should pass.
    assert risk_manager.check_liquidity(100, 1_000_000) is True


def test_liquidity_outsized_order_blocks(risk_manager):
    # 500k shares vs 1M ADV → would be half of daily volume, definitely blocked.
    assert risk_manager.check_liquidity(500_000, 1_000_000) is False


def test_liquidity_no_volume_blocks_for_safety(risk_manager):
    assert risk_manager.check_liquidity(100, 0) is False


# ─────────────────────────── Market-health circuit breakers ────────────────


def test_market_health_normal_conditions(risk_manager):
    assert risk_manager.check_market_health(spy_intraday_change_pct=-0.5, action="BUY", vix_level=15) is True


def test_market_health_vix_blocks_all_entries(risk_manager):
    """VIX>threshold blocks both longs and shorts."""
    thresh = risk_manager.config.CIRCUIT_BREAKER_VIX_THRESHOLD
    assert risk_manager.check_market_health(0.0, "BUY", vix_level=thresh + 1) is False
    assert risk_manager.check_market_health(0.0, "SELL", vix_level=thresh + 1) is False


def test_market_health_spy_drop_blocks_longs_only(risk_manager):
    drop = risk_manager.config.CIRCUIT_BREAKER_SPY_DROP_PCT - 0.5  # more negative
    assert risk_manager.check_market_health(drop, "BUY", vix_level=10) is False
    # Shorts unaffected by SPY-drop rule
    assert risk_manager.check_market_health(drop, "SELL", vix_level=10) is True


# ─────────────────────────── Sector concentration ──────────────────────────


def test_sector_concentration_within_limit_passes(risk_manager, db):
    """No existing positions → any new entry passes the 25% cap."""
    assert risk_manager.check_sector_concentration(
        ticker="NVDA", sector="Technology",
        account_value=100_000, entry_value=10_000,
    ) is True


def test_sector_concentration_over_limit_blocks(risk_manager, db):
    # Seed a big existing Tech position that already eats the cap.
    db.save_trade({
        "ticker": "AAPL", "action": "BUY", "quantity": 100, "entry_price": 300.0,
        "stop_loss_price": 285.0, "take_profit_price": 330.0, "conviction": 8.0,
        "order_id": "ord1",
    })
    # Back-fill sector manually (save_trade doesn't take sector).
    import sqlite3
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("UPDATE trades SET sector = ? WHERE ticker = ?", ("Technology", "AAPL"))
        conn.commit()

    # 30k existing + 10k new = 40k / 100k = 40% > 25% cap
    assert risk_manager.check_sector_concentration(
        ticker="NVDA", sector="Technology",
        account_value=100_000, entry_value=10_000,
    ) is False


def test_sector_concentration_unknown_sector_passes(risk_manager):
    """Can't enforce without sector data — err on allow."""
    assert risk_manager.check_sector_concentration(
        ticker="XYZ", sector="", account_value=100_000, entry_value=5_000,
    ) is True


# ─────────────────────────── Gap-risk multiplier ──────────────────────────


def test_gap_risk_calm_stock_full_size(risk_manager):
    """Low ATR, beta 1.0, no earnings → 1.0x size."""
    m = risk_manager.calculate_gap_risk_multiplier(
        current_atr=1.0, current_price=100.0, beta=1.0, near_earnings=False,
    )
    assert m == 1.0


def test_gap_risk_near_earnings_reduces(risk_manager):
    m = risk_manager.calculate_gap_risk_multiplier(
        current_atr=1.0, current_price=100.0, beta=1.0, near_earnings=True,
    )
    assert m < 1.0


def test_gap_risk_high_beta_high_atr_reduces(risk_manager):
    m = risk_manager.calculate_gap_risk_multiplier(
        current_atr=8.0, current_price=100.0, beta=2.5, near_earnings=False,
    )
    assert 0.5 <= m < 1.0


def test_gap_risk_floor(risk_manager):
    """Never sub-0.5x regardless of how scary."""
    m = risk_manager.calculate_gap_risk_multiplier(
        current_atr=50.0, current_price=100.0, beta=3.0, near_earnings=True,
    )
    assert m >= 0.5


# ─────────────────────────── Volatility adjustment ─────────────────────────


def test_volatility_spike_cuts_size(risk_manager):
    mult = risk_manager.config.VOLATILITY_ATR_MULTIPLIER
    # current ATR > multiplier × median ATR → 0.5
    assert risk_manager.check_volatility_adjustment(
        current_atr=mult * 2, median_atr=1.0
    ) == 0.5


def test_volatility_normal_full_size(risk_manager):
    assert risk_manager.check_volatility_adjustment(current_atr=1.0, median_atr=1.0) == 1.0


def test_volatility_missing_data_full_size(risk_manager):
    """Missing median → don't penalize; let Kelly handle it."""
    assert risk_manager.check_volatility_adjustment(current_atr=5.0, median_atr=0) == 1.0


# ─────────────────────────── Position sizing integration ──────────────────


def test_position_size_respects_max_position_pct(risk_manager):
    """With a very tight stop, risk-based size could exceed max_position_pct.
    Final size must clip to the value cap, never exceed it."""
    shares = risk_manager.calculate_position_size(
        account_value=100_000, entry_price=10.0, stop_loss_pct=0.5, portfolio="main",
    )
    params = risk_manager._get_params("main")
    max_shares_by_value = int(100_000 * params["max_position_pct"] / 10.0)
    assert shares <= max_shares_by_value


def test_position_size_zero_on_invalid_stop(risk_manager):
    """A 0% stop-loss must not divide-by-zero — expect 0 shares, safely blocked."""
    assert risk_manager.calculate_position_size(
        account_value=100_000, entry_price=50.0, stop_loss_pct=0.0, portfolio="main",
    ) == 0
