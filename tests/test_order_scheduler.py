"""Order scheduler tests — deterministic, no broker calls."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from agents.order_scheduler import (
    ADV_THRESHOLD_PCT,
    plan_order,
)


NOW = datetime(2026, 4, 17, 10, 0, 0)


def test_small_order_vs_adv_is_single_shot():
    """100 shares vs 1M ADV = 0.01% → well below 1% threshold."""
    plan = plan_order(
        ticker="NVDA", total_qty=100, side="buy",
        avg_daily_volume=1_000_000, now=NOW,
    )
    assert plan.is_single_shot
    assert plan.children[0].qty == 100
    assert plan.children[0].submit_at == NOW


def test_zero_adv_falls_back_to_single_shot():
    """No ADV data → don't block, just send the single order."""
    plan = plan_order("NVDA", 100_000, "buy", avg_daily_volume=0, now=NOW)
    assert plan.is_single_shot


def test_large_order_slices_into_equal_children():
    # 50k shares vs 1M ADV = 5% → above threshold, slice into 10 @ 5k each.
    plan = plan_order(
        ticker="NVDA", total_qty=50_000, side="buy",
        avg_daily_volume=1_000_000, now=NOW,
        slice_count=10, window_minutes=15,
    )
    assert not plan.is_single_shot
    assert len(plan.children) == 10
    assert sum(c.qty for c in plan.children) == 50_000
    assert all(c.qty == 5_000 for c in plan.children)


def test_slicing_handles_remainder_on_last_child():
    # 50_007 / 10 = 5000 base, remainder 7 → last child gets 5007.
    plan = plan_order("NVDA", 50_007, "buy", avg_daily_volume=1_000_000,
                      now=NOW, slice_count=10)
    assert sum(c.qty for c in plan.children) == 50_007
    assert plan.children[-1].qty == 5_007
    assert all(c.qty == 5_000 for c in plan.children[:-1])


def test_child_timings_span_window():
    plan = plan_order("NVDA", 50_000, "buy", avg_daily_volume=1_000_000,
                      now=NOW, slice_count=10, window_minutes=15)
    first = plan.children[0].submit_at
    last = plan.children[-1].submit_at
    assert first == NOW
    assert (last - first) == timedelta(minutes=15)
    # Even spacing → steps should all be equal.
    steps = [
        plan.children[i + 1].submit_at - plan.children[i].submit_at
        for i in range(len(plan.children) - 1)
    ]
    assert all(s == steps[0] for s in steps)


def test_parent_smaller_than_slice_count_clamps_to_qty():
    """If parent is 3 shares, slice_count clamps to 3 (one share each) — not
    10 × zero-share children. Total shares still match."""
    plan = plan_order("PENNY", 3, "buy", avg_daily_volume=10,
                      now=NOW, slice_count=10)
    assert len(plan.children) <= 3
    assert sum(c.qty for c in plan.children) == 3
    assert all(c.qty >= 1 for c in plan.children)


def test_threshold_boundary_just_above_triggers_slicing():
    # Make share count = 1.5% of ADV (above 1%).
    qty = 150
    adv = 10_000
    plan = plan_order("X", qty, "buy", avg_daily_volume=adv, now=NOW)
    # 150/10000 = 1.5% > 1% → sliced.
    assert not plan.is_single_shot


def test_threshold_boundary_just_below_single_shot():
    # Exactly at threshold — our comparison is `<=`, so exactly equal goes single-shot.
    qty = int(ADV_THRESHOLD_PCT * 10_000)  # 100
    plan = plan_order("X", qty, "buy", avg_daily_volume=10_000, now=NOW)
    assert plan.is_single_shot


def test_invalid_qty_raises():
    with pytest.raises(ValueError):
        plan_order("X", 0, "buy", avg_daily_volume=1_000_000, now=NOW)


def test_describe_formats_both_modes():
    single = plan_order("X", 100, "buy", avg_daily_volume=1_000_000, now=NOW)
    twap = plan_order("X", 50_000, "buy", avg_daily_volume=1_000_000, now=NOW)
    assert "not worth slicing" in single.describe()
    assert "TWAP" in twap.describe()
    assert "15min" in twap.describe() or "15 min" in twap.describe() or "15" in twap.describe()


def test_children_are_immutable_tuple():
    """The plan's children are frozen — callers can't mutate a submitted order."""
    plan = plan_order("X", 100, "buy", avg_daily_volume=1_000_000, now=NOW)
    assert isinstance(plan.children, tuple)
    with pytest.raises(Exception):
        plan.children[0].qty = 50  # type: ignore[misc]
