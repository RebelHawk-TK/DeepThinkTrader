"""Behavioral tests for the backtest engine.

These drive the engine with synthetic bar streams so we can assert exact
entry/exit behavior, then spot-check against strategies on longer series.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from backtest.engine import Engine, EngineConfig
from backtest.metrics import compute_metrics
from backtest.strategies import BuyAndHoldStrategy, SMACrossoverStrategy
from brokers.base import Bar


def _series(ticker: str, closes: list[float], start: datetime | None = None) -> list[Bar]:
    t = start or datetime(2026, 1, 2)
    bars = []
    for c in closes:
        bars.append(Bar(
            ticker=ticker, timestamp=t,
            open=c, high=c * 1.005, low=c * 0.995, close=c, volume=1_000_000,
        ))
        t += timedelta(days=1)
    return bars


# ─────────────────────────── Engine basics ────────────────────────────────


def test_buy_and_hold_rides_uptrend():
    bars = _series("NVDA", [100.0 + i for i in range(50)])  # linear 100→149
    engine = Engine(strategy=BuyAndHoldStrategy(), ticker="NVDA",
                    config=EngineConfig(starting_equity=100_000))
    result = engine.run(bars)
    assert result.num_trades == 1
    # BuyAndHold has a 50% stop and 1000% TP — neither should trigger.
    # With ~10% position cap on $100k and entry at $100: ~100 shares.
    # Final equity must be > starting since we rode a 49% uptrend.
    assert result.ending_equity > result.starting_equity


def test_stop_loss_caps_loss():
    # Price dumps immediately.
    bars = _series("NVDA", [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0])
    engine = Engine(
        strategy=BuyAndHoldStrategy(), ticker="NVDA",
        config=EngineConfig(
            starting_equity=100_000, risk_pct_per_trade=0.02,
            max_position_pct=0.10,
        ),
    )
    # Override default 50% stop to 4% to make it bite.
    orig_on_bar = engine.strategy.on_bar

    def tight_stop(bar, lookback, account):
        sig = orig_on_bar(bar, lookback, account)
        if sig.action == "BUY":
            from dataclasses import replace
            return replace(sig, stop_loss_pct=4.0, take_profit_pct=8.0)
        return sig

    engine.strategy.on_bar = tight_stop  # type: ignore[method-assign]
    result = engine.run(bars)
    closed = [t for t in result.trades if t.exit_time is not None]
    assert len(closed) == 1
    assert closed[0].reason == "stop_loss"
    # Loss should be roughly risk amount (2% of $100k = $2k), not unbounded.
    assert closed[0].pnl < 0
    assert closed[0].pnl > -3_000


def test_trailing_stop_activates_and_captures_gain():
    # Price rises sharply then pulls back to test trailing.
    # Entry at 100 → peak 110 → trailing at 108.35 (1.5% below peak) → dip to 108.
    bars = _series("NVDA", [100.0, 104.0, 108.0, 110.0, 109.0, 107.5, 106.0])
    engine = Engine(
        strategy=BuyAndHoldStrategy(), ticker="NVDA",
        config=EngineConfig(
            starting_equity=100_000,
            trailing_stop_activation_pct=2.0,
            trailing_stop_distance_pct=1.5,
        ),
    )

    orig = engine.strategy.on_bar

    def wide_stop(bar, lookback, account):
        sig = orig(bar, lookback, account)
        if sig.action == "BUY":
            from dataclasses import replace
            return replace(sig, stop_loss_pct=20.0, take_profit_pct=100.0)
        return sig

    engine.strategy.on_bar = wide_stop  # type: ignore[method-assign]
    result = engine.run(bars)
    closed = [t for t in result.trades if t.exit_time is not None]
    assert len(closed) == 1
    assert closed[0].reason == "trailing_stop"
    assert closed[0].pnl > 0  # captured gain before reversal


def test_take_profit_closes_on_upside():
    bars = _series("NVDA", [100.0, 103.0, 106.0, 109.0, 112.0])
    engine = Engine(strategy=BuyAndHoldStrategy(), ticker="NVDA",
                    config=EngineConfig(starting_equity=100_000))

    orig = engine.strategy.on_bar
    def tight(bar, lookback, account):
        sig = orig(bar, lookback, account)
        if sig.action == "BUY":
            from dataclasses import replace
            # Disable trailing by pushing activation very high.
            return replace(sig, stop_loss_pct=10.0, take_profit_pct=5.0)
        return sig

    engine.strategy.on_bar = tight  # type: ignore[method-assign]
    # Bump activation so trailing doesn't race the TP.
    engine.config.trailing_stop_activation_pct = 50.0
    result = engine.run(bars)
    closed = [t for t in result.trades if t.exit_time is not None]
    assert closed[0].reason == "take_profit"
    assert closed[0].pnl > 0


def test_sma_crossover_enters_on_cross():
    # Build a series where 10SMA crosses above 30SMA at a known bar.
    # Slow decline then sharp reversal.
    closes = [100 - i * 0.5 for i in range(30)]  # 30 bars of decline
    closes += [80 + i * 2 for i in range(25)]    # 25 bars of rally
    bars = _series("NVDA", closes)
    engine = Engine(strategy=SMACrossoverStrategy(), ticker="NVDA",
                    config=EngineConfig(starting_equity=100_000))
    result = engine.run(bars)
    assert result.num_trades >= 1  # at least one entry from the crossover


# ─────────────────────────── Metrics sanity ────────────────────────────────


def test_metrics_flat_curve_is_zero():
    # A strategy that never trades → equity stays at starting cash.
    bars = _series("NVDA", [100.0] * 20)

    class NeverTrade:
        name = "never"
        def on_bar(self, bar, lookback, account):
            from backtest.strategy import Signal
            return Signal("HOLD", 0.0, 0.0, 0.0)

    engine = Engine(strategy=NeverTrade(), ticker="NVDA")
    result = engine.run(bars)
    m = compute_metrics(result)
    assert m.total_return_pct == 0.0
    assert m.max_drawdown_pct == 0.0
    assert m.num_trades == 0


def test_metrics_computed_for_winning_run():
    bars = _series("NVDA", [100.0 + i for i in range(100)])
    engine = Engine(strategy=BuyAndHoldStrategy(), ticker="NVDA")
    result = engine.run(bars)
    m = compute_metrics(result)
    assert m.total_return_pct > 0
    # Linear uptrend → max DD should be essentially zero.
    assert m.max_drawdown_pct < 1.0
