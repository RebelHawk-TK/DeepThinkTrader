"""Order sizing & TWAP slicing.

When a parent order's share count exceeds `ADV_THRESHOLD_PCT` of the
ticker's average daily volume, a single market order risks moving the price
against us. TWAP (time-weighted average price) splits the parent into
equal-size children spaced across a window, smoothing the impact.

This module is broker-agnostic — it produces a `TWAPPlan` of child orders,
which callers submit through any IBroker implementation. That keeps the
logic testable without an Alpaca dependency.

We don't stream fills back into the plan — the bot's existing exit monitor
picks up positions once they appear in Alpaca, so we just submit & log.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

logger = logging.getLogger(__name__)

# Route through TWAP when parent shares > this fraction of ADV.
ADV_THRESHOLD_PCT = 0.01  # 1%
DEFAULT_SLICE_COUNT = 10
DEFAULT_WINDOW_MINUTES = 15
MIN_CHILD_SIZE = 1


@dataclass(frozen=True)
class ChildOrder:
    ticker: str
    qty: int
    side: Literal["buy", "sell"]
    submit_at: datetime


@dataclass(frozen=True)
class TWAPPlan:
    ticker: str
    total_qty: int
    side: Literal["buy", "sell"]
    children: tuple[ChildOrder, ...]

    @property
    def is_single_shot(self) -> bool:
        return len(self.children) == 1

    def describe(self) -> str:
        if self.is_single_shot:
            return (
                f"single {self.side} {self.total_qty} {self.ticker} "
                f"(below ADV threshold — not worth slicing)"
            )
        window = self.children[-1].submit_at - self.children[0].submit_at
        return (
            f"TWAP {self.side} {self.total_qty} {self.ticker} → "
            f"{len(self.children)} slices over {window.total_seconds() / 60:.0f}min "
            f"(avg {self.total_qty // len(self.children)} shares/slice)"
        )


def plan_order(
    ticker: str,
    total_qty: int,
    side: Literal["buy", "sell"],
    avg_daily_volume: int,
    now: datetime | None = None,
    slice_count: int = DEFAULT_SLICE_COUNT,
    window_minutes: int = DEFAULT_WINDOW_MINUTES,
    adv_threshold_pct: float = ADV_THRESHOLD_PCT,
) -> TWAPPlan:
    """Produce either a single-shot plan (small enough) or a TWAP slice plan.

    The first child always goes out at `now`. Remaining children are evenly
    spaced across `window_minutes`. Any rounding remainder is added to the
    final child so total_qty is exact.
    """
    if total_qty <= 0:
        raise ValueError(f"total_qty must be positive, got {total_qty}")
    now = now or datetime.now()

    if avg_daily_volume <= 0 or total_qty / avg_daily_volume <= adv_threshold_pct:
        return TWAPPlan(
            ticker=ticker, total_qty=total_qty, side=side,
            children=(ChildOrder(ticker=ticker, qty=total_qty, side=side, submit_at=now),),
        )

    slice_count = max(2, min(slice_count, total_qty))
    base = total_qty // slice_count
    remainder = total_qty - base * slice_count
    if base < MIN_CHILD_SIZE:
        # Parent too small to slice meaningfully — just send as one order.
        return TWAPPlan(
            ticker=ticker, total_qty=total_qty, side=side,
            children=(ChildOrder(ticker=ticker, qty=total_qty, side=side, submit_at=now),),
        )

    step = timedelta(minutes=window_minutes) / (slice_count - 1)
    children: list[ChildOrder] = []
    for i in range(slice_count):
        qty = base + (remainder if i == slice_count - 1 else 0)
        children.append(ChildOrder(
            ticker=ticker, qty=qty, side=side, submit_at=now + i * step,
        ))
    plan = TWAPPlan(ticker=ticker, total_qty=total_qty, side=side, children=tuple(children))
    logger.info(plan.describe())
    return plan
