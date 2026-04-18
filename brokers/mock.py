"""Deterministic in-memory broker for tests and backtests.

Fills market orders at the bar's close price of `set_current_bar(...)` —
tests must advance the current bar explicitly. Limit orders fill when
price crosses the limit. No partial fills (future work).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from brokers.base import Account, Bar, Order, OrderSide, OrderType, Position


class MockBroker:
    """In-memory broker. Tests drive it by calling `ingest_bar`."""

    def __init__(self, starting_cash: float = 100_000.0) -> None:
        self._cash = starting_cash
        self._positions: dict[str, Position] = {}
        self._orders: dict[str, Order] = {}
        self._open_orders: list[str] = []
        self._history: dict[str, list[Bar]] = {}
        self._current: dict[str, Bar] = {}
        self._realized_pnl = 0.0

    # ── Bar feed (tests use this to drive the clock) ──────────────────────

    def ingest_bar(self, bar: Bar) -> None:
        """Record a bar as history and make it the 'current' price.

        Also runs the fill check for any resting orders on this ticker.
        """
        self._history.setdefault(bar.ticker, []).append(bar)
        self._current[bar.ticker] = bar
        pos = self._positions.get(bar.ticker)
        if pos is not None:
            self._positions[bar.ticker] = Position(
                ticker=pos.ticker,
                qty=pos.qty,
                avg_entry_price=pos.avg_entry_price,
                current_price=bar.close,
            )
        self._try_fill_open_orders(bar)

    # ── IBroker surface ───────────────────────────────────────────────────

    def get_account(self) -> Account:
        equity = self._cash + sum(p.market_value for p in self._positions.values())
        return Account(equity=equity, cash=self._cash, buying_power=self._cash)

    def get_positions(self) -> list[Position]:
        return [p for p in self._positions.values() if p.qty != 0]

    def get_position(self, ticker: str) -> Position | None:
        pos = self._positions.get(ticker)
        return pos if pos and pos.qty != 0 else None

    def get_bars(
        self, ticker: str, start: datetime, end: datetime, timeframe: str = "1Day"
    ) -> list[Bar]:
        return [b for b in self._history.get(ticker, []) if start <= b.timestamp <= end]

    def submit_order(
        self,
        ticker: str,
        qty: int,
        side: OrderSide,
        order_type: OrderType = "market",
        limit_price: float | None = None,
    ) -> Order:
        if qty <= 0:
            raise ValueError(f"qty must be positive, got {qty}")
        if order_type == "limit" and limit_price is None:
            raise ValueError("limit order requires limit_price")

        order = Order(
            id=str(uuid.uuid4()),
            ticker=ticker,
            side=side,
            qty=qty,
            order_type=order_type,
            limit_price=limit_price,
            submitted_at=datetime.now(),
        )
        self._orders[order.id] = order

        current = self._current.get(ticker)
        if order_type == "market" and current is not None:
            self._fill(order, current.close, current.timestamp)
        else:
            self._open_orders.append(order.id)
        return order

    def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order is None or order.status not in ("pending", "partial"):
            return False
        order.status = "cancelled"
        if order_id in self._open_orders:
            self._open_orders.remove(order_id)
        return True

    def get_order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    # ── Internals ─────────────────────────────────────────────────────────

    def _try_fill_open_orders(self, bar: Bar) -> None:
        still_open: list[str] = []
        for oid in self._open_orders:
            order = self._orders[oid]
            if order.ticker != bar.ticker:
                still_open.append(oid)
                continue
            if order.order_type == "market":
                self._fill(order, bar.close, bar.timestamp)
                continue
            # Limit: buy fills when low <= limit, sell fills when high >= limit.
            if order.side == "buy" and bar.low <= (order.limit_price or 0):
                fill_px = min(bar.open, order.limit_price)
                self._fill(order, fill_px, bar.timestamp)
            elif order.side == "sell" and bar.high >= (order.limit_price or 0):
                fill_px = max(bar.open, order.limit_price)
                self._fill(order, fill_px, bar.timestamp)
            else:
                still_open.append(oid)
        self._open_orders = still_open

    def _fill(self, order: Order, price: float, when: datetime) -> None:
        order.status = "filled"
        order.filled_qty = order.qty
        order.filled_avg_price = price
        order.filled_at = when

        ticker = order.ticker
        pos = self._positions.get(ticker)
        signed_qty = order.qty if order.side == "buy" else -order.qty

        if pos is None:
            new_qty = signed_qty
            avg_px = price if new_qty != 0 else 0.0
        else:
            new_qty = pos.qty + signed_qty
            if pos.qty * signed_qty >= 0:
                # Adding to existing exposure — weighted-avg entry.
                total_cost = pos.avg_entry_price * pos.qty + price * signed_qty
                avg_px = total_cost / new_qty if new_qty != 0 else 0.0
            else:
                # Reducing / flipping. Realize P&L on the reduced portion.
                reduce_qty = min(abs(pos.qty), abs(signed_qty))
                direction = 1 if pos.qty > 0 else -1
                self._realized_pnl += direction * reduce_qty * (price - pos.avg_entry_price)
                if new_qty == 0:
                    avg_px = 0.0
                elif pos.qty * new_qty > 0:
                    avg_px = pos.avg_entry_price  # same side, same basis
                else:
                    avg_px = price  # flipped through zero — reset basis

        cash_delta = -signed_qty * price
        self._cash += cash_delta
        if new_qty == 0:
            self._positions.pop(ticker, None)
        else:
            self._positions[ticker] = Position(
                ticker=ticker, qty=new_qty, avg_entry_price=avg_px,
                current_price=price,
            )

    # ── Test helpers ──────────────────────────────────────────────────────

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl
