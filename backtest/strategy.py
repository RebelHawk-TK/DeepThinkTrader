"""Strategy protocol for the backtest harness.

A strategy is stateless with respect to the engine — it receives a snapshot
of the market (bars + account) and returns signals. The engine is the single
owner of positions and order flow, so strategies stay small and testable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from brokers.base import Account, Bar


@dataclass(frozen=True)
class Signal:
    """Everything the engine needs to size and place an entry order.

    `stop_loss_pct` and `take_profit_pct` are expressed in percent (not bps),
    so a 4% stop is `stop_loss_pct=4.0`. Entry is assumed at the bar's close.
    """
    action: Literal["BUY", "SELL", "HOLD"]
    conviction: float
    stop_loss_pct: float
    take_profit_pct: float
    reason: str = ""


class Strategy(Protocol):
    """A backtestable trading strategy."""

    name: str

    def on_bar(
        self,
        bar: Bar,
        lookback: list[Bar],
        account: Account,
    ) -> Signal:
        """Evaluate one ticker at one bar and emit a Signal.

        `lookback` is all bars up to and including this one (oldest → newest),
        so the strategy can compute SMAs, RSI, etc. without peeking ahead.
        """
        ...
