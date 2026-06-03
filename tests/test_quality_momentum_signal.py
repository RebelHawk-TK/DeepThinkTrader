"""Tests for the validated MAIN quality_momentum entry signal.

Pure logic on a research-report dict — no network/agent. Mirrors the validated rule
(backtest.validate_quality_momentum): above SMA-20 + revenue_growth>0 + profit_margin>0
+ up on the day (longs only).
"""
from __future__ import annotations

from agents.deepthink_agent import DeepThinkAgent


def _report(above20=True, chg=1.0, growth=0.1, margin=0.1):
    fin = {}
    if growth is not None:
        fin["revenue_growth"] = growth
    if margin is not None:
        fin["profit_margin"] = margin
    return {
        "technicals": {"above_sma_20": above20, "daily_change_pct": chg},
        "fundamentals": {"financials": fin},
    }


def test_fires_when_all_conditions_met():
    assert DeepThinkAgent._quality_momentum_signal(_report()) is True


def test_blocked_below_sma20():
    assert DeepThinkAgent._quality_momentum_signal(_report(above20=False)) is False


def test_blocked_on_down_day():
    assert DeepThinkAgent._quality_momentum_signal(_report(chg=-0.5)) is False


def test_blocked_on_negative_growth():
    assert DeepThinkAgent._quality_momentum_signal(_report(growth=-0.1)) is False


def test_blocked_on_negative_margin():
    assert DeepThinkAgent._quality_momentum_signal(_report(margin=-0.05)) is False


def test_blocked_when_fundamentals_missing():
    assert DeepThinkAgent._quality_momentum_signal(_report(growth=None, margin=None)) is False


def test_blocked_when_margin_zero():
    # strict >0
    assert DeepThinkAgent._quality_momentum_signal(_report(margin=0.0)) is False
