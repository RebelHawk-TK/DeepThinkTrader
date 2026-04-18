"""Reference strategies for smoke-testing the backtest engine.

These are deliberately simple — the real work is making the engine trustworthy.
Once we port DeepThinkAgent's rule-based scoring (Sprint 4), it becomes a
Strategy that the engine runs the same way.
"""
from __future__ import annotations

from brokers.base import Account, Bar
from backtest.strategy import Signal


class SMACrossoverStrategy:
    """Classic 10/30 SMA crossover. Long-only. Fixed ATR-ish stop at 4%, TP at 8%."""

    name = "sma_10_30_crossover"

    def __init__(self, fast: int = 10, slow: int = 30) -> None:
        self.fast = fast
        self.slow = slow

    def on_bar(self, bar: Bar, lookback: list[Bar], account: Account) -> Signal:
        if len(lookback) < self.slow + 1:
            return Signal("HOLD", 0.0, 0.0, 0.0, "warming up")

        closes = [b.close for b in lookback]
        fast_today = sum(closes[-self.fast:]) / self.fast
        slow_today = sum(closes[-self.slow:]) / self.slow
        fast_yday = sum(closes[-self.fast - 1:-1]) / self.fast
        slow_yday = sum(closes[-self.slow - 1:-1]) / self.slow

        crossed_up = fast_yday <= slow_yday and fast_today > slow_today
        if crossed_up:
            return Signal("BUY", conviction=7.0, stop_loss_pct=4.0,
                          take_profit_pct=8.0, reason=f"{self.fast}/{self.slow} SMA cross up")
        return Signal("HOLD", 0.0, 0.0, 0.0, "no signal")


class BuyAndHoldStrategy:
    """Enter on the first bar, never exit. A floor for comparison."""

    name = "buy_and_hold"

    def __init__(self) -> None:
        self._bought = False

    def on_bar(self, bar: Bar, lookback: list[Bar], account: Account) -> Signal:
        if self._bought:
            return Signal("HOLD", 0.0, 0.0, 0.0, "already long")
        self._bought = True
        return Signal("BUY", conviction=5.0, stop_loss_pct=50.0,
                      take_profit_pct=1000.0, reason="buy-and-hold entry")
