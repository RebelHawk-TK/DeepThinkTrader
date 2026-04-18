"""Broker interface — the minimum surface backtest + strategies need.

Types are plain dataclasses (not Pydantic) to avoid runtime overhead on the
hot path. `IBroker` is a `Protocol` so neither `AlpacaBroker` nor `MockBroker`
has to inherit from anything — duck typing fits the Python norm.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

OrderSide = Literal["buy", "sell"]
OrderType = Literal["market", "limit"]
OrderStatus = Literal["pending", "filled", "partial", "cancelled", "rejected"]


@dataclass(frozen=True)
class Bar:
    ticker: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int

    @property
    def price(self) -> float:
        return self.close


@dataclass
class Order:
    id: str
    ticker: str
    side: OrderSide
    qty: int
    order_type: OrderType
    limit_price: float | None = None
    status: OrderStatus = "pending"
    filled_qty: int = 0
    filled_avg_price: float = 0.0
    submitted_at: datetime | None = None
    filled_at: datetime | None = None


@dataclass
class Position:
    ticker: str
    qty: int
    avg_entry_price: float
    current_price: float

    @property
    def market_value(self) -> float:
        return self.qty * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_entry_price) * self.qty


@dataclass
class Account:
    equity: float
    cash: float
    buying_power: float


class IBroker(Protocol):
    """Minimum broker surface for strategies, backtests, and execution.

    Intentionally small. If you find yourself wanting to add something
    Alpaca-specific, it probably belongs on a concrete subclass, not here.
    """

    def get_account(self) -> Account: ...

    def get_positions(self) -> list[Position]: ...

    def get_position(self, ticker: str) -> Position | None: ...

    def get_bars(
        self, ticker: str, start: datetime, end: datetime, timeframe: str = "1Day"
    ) -> list[Bar]: ...

    def submit_order(
        self,
        ticker: str,
        qty: int,
        side: OrderSide,
        order_type: OrderType = "market",
        limit_price: float | None = None,
    ) -> Order: ...

    def cancel_order(self, order_id: str) -> bool: ...

    def get_order(self, order_id: str) -> Order | None: ...
