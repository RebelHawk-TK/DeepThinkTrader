"""AlpacaBroker — thin wrapper over the live Alpaca REST API.

This is a narrow surface for new code (backtest, future strategies) to share
with MockBroker. The live `ExecutionAgent` still uses raw HTTP directly; that
migration is a separate piece of work.
"""
from __future__ import annotations

from datetime import datetime

import requests

from brokers.base import Account, Bar, IBroker, Order, OrderSide, OrderType, Position
from config import Config


class AlpacaBroker(IBroker):
    def __init__(self, api_key: str, secret_key: str) -> None:
        """Broker bound to one Alpaca account. Caller supplies per-user keys."""
        self._session = requests.Session()
        self._session.headers.update({
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        })
        self._trading_base = Config.ALPACA_BASE_URL
        self._data_base = "https://data.alpaca.markets"
        self._timeout = (5, 30)  # (connect, read)

    def get_account(self) -> Account:
        resp = self._session.get(f"{self._trading_base}/v2/account", timeout=self._timeout)
        resp.raise_for_status()
        d = resp.json()
        return Account(
            equity=float(d["equity"]),
            cash=float(d["cash"]),
            buying_power=float(d["buying_power"]),
        )

    def get_positions(self) -> list[Position]:
        resp = self._session.get(f"{self._trading_base}/v2/positions", timeout=self._timeout)
        resp.raise_for_status()
        return [self._to_position(p) for p in resp.json()]

    def get_position(self, ticker: str) -> Position | None:
        resp = self._session.get(
            f"{self._trading_base}/v2/positions/{ticker}", timeout=self._timeout
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._to_position(resp.json())

    def get_bars(
        self, ticker: str, start: datetime, end: datetime, timeframe: str = "1Day"
    ) -> list[Bar]:
        params = {
            "symbols": ticker,
            "timeframe": timeframe,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "feed": "iex",
            "limit": 10_000,
        }
        resp = self._session.get(
            f"{self._data_base}/v2/stocks/bars", params=params, timeout=self._timeout
        )
        resp.raise_for_status()
        payload = resp.json().get("bars", {}).get(ticker, [])
        return [self._to_bar(ticker, b) for b in payload]

    def submit_order(
        self,
        ticker: str,
        qty: int,
        side: OrderSide,
        order_type: OrderType = "market",
        limit_price: float | None = None,
    ) -> Order:
        body: dict = {
            "symbol": ticker,
            "qty": qty,
            "side": side,
            "type": order_type,
            "time_in_force": "day",
        }
        if order_type == "limit":
            if limit_price is None:
                raise ValueError("limit_price required for limit orders")
            body["limit_price"] = str(round(limit_price, 2))
        resp = self._session.post(
            f"{self._trading_base}/v2/orders", json=body, timeout=self._timeout
        )
        resp.raise_for_status()
        return self._to_order(resp.json())

    def cancel_order(self, order_id: str) -> bool:
        resp = self._session.delete(
            f"{self._trading_base}/v2/orders/{order_id}", timeout=self._timeout
        )
        return resp.status_code in (200, 204)

    def get_order(self, order_id: str) -> Order | None:
        resp = self._session.get(
            f"{self._trading_base}/v2/orders/{order_id}", timeout=self._timeout
        )
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return self._to_order(resp.json())

    # ── Response parsers ──────────────────────────────────────────────────

    @staticmethod
    def _to_position(d: dict) -> Position:
        return Position(
            ticker=d["symbol"],
            qty=int(float(d["qty"])),
            avg_entry_price=float(d["avg_entry_price"]),
            current_price=float(d.get("current_price") or d.get("market_value", 0)),
        )

    @staticmethod
    def _to_bar(ticker: str, d: dict) -> Bar:
        return Bar(
            ticker=ticker,
            timestamp=datetime.fromisoformat(d["t"].replace("Z", "+00:00")),
            open=float(d["o"]),
            high=float(d["h"]),
            low=float(d["l"]),
            close=float(d["c"]),
            volume=int(d["v"]),
        )

    @staticmethod
    def _to_order(d: dict) -> Order:
        filled_qty = int(float(d.get("filled_qty") or 0))
        status_raw = d.get("status", "pending")
        status_map = {
            "new": "pending", "pending_new": "pending", "accepted": "pending",
            "partially_filled": "partial", "filled": "filled",
            "canceled": "cancelled", "cancelled": "cancelled",
            "rejected": "rejected", "expired": "cancelled",
        }
        return Order(
            id=d["id"],
            ticker=d["symbol"],
            side=d["side"],
            qty=int(float(d["qty"])),
            order_type=d.get("order_type") or d.get("type", "market"),
            limit_price=float(d["limit_price"]) if d.get("limit_price") else None,
            status=status_map.get(status_raw, "pending"),
            filled_qty=filled_qty,
            filled_avg_price=float(d.get("filled_avg_price") or 0),
            submitted_at=datetime.fromisoformat(d["submitted_at"].replace("Z", "+00:00"))
            if d.get("submitted_at") else None,
            filled_at=datetime.fromisoformat(d["filled_at"].replace("Z", "+00:00"))
            if d.get("filled_at") else None,
        )
