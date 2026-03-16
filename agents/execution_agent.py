"""Execution Agent — Places trades via Alpaca with strict risk guardrails.

Captures X-Request-ID from every Alpaca API response and persists to SQLite
for debugging and support requests.
"""

from __future__ import annotations

import logging

import requests as http_requests
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, OrderType, TimeInForce
from alpaca.trading.requests import (
    MarketOrderRequest,
)

from config import Config
from utils.database import Database
from utils.risk_manager import RiskManager

logger = logging.getLogger(__name__)


class ExecutionAgent:
    def __init__(self, db: Database | None = None):
        self.config = Config()
        self.db = db or Database()
        self.risk_manager = RiskManager(self.db)
        self.client = TradingClient(
            api_key=self.config.ALPACA_API_KEY,
            secret_key=self.config.ALPACA_SECRET_KEY,
            paper=True,
        )
        # HTTP session for raw API calls that capture X-Request-ID
        self._session = http_requests.Session()
        self._session.headers.update({
            "APCA-API-KEY-ID": self.config.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": self.config.ALPACA_SECRET_KEY,
        })
        self._base_url = self.config.ALPACA_BASE_URL

    def _capture_request_id(
        self,
        response: http_requests.Response,
        endpoint: str,
        method: str = "GET",
        ticker: str | None = None,
        order_id: str | None = None,
    ) -> str | None:
        """Extract X-Request-ID from response headers and persist it."""
        request_id = response.headers.get("X-Request-ID")
        if request_id:
            self.db.save_request_id(
                request_id=request_id,
                endpoint=endpoint,
                method=method,
                ticker=ticker,
                order_id=order_id,
                http_status=response.status_code,
                success=response.ok,
            )
            logger.debug(f"Alpaca X-Request-ID: {request_id} ({method} {endpoint} → {response.status_code})")
        else:
            logger.warning(f"No X-Request-ID in response for {method} {endpoint}")
        return request_id

    def get_account_value(self) -> float:
        """Get current account equity from Alpaca, capturing X-Request-ID."""
        try:
            resp = self._session.get(f"{self._base_url}/v2/account")
            self._capture_request_id(resp, "/v2/account", "GET")
            resp.raise_for_status()
            return float(resp.json()["equity"])
        except Exception as e:
            logger.error(f"Failed to fetch account: {e}")
            return self.config.ACCOUNT_SIZE

    def execute(self, analysis: dict) -> dict:
        """Execute a trade based on DeepThink analysis, with full safety checks."""
        ticker = analysis["ticker"]
        action = analysis["action"]
        conviction = analysis["conviction"]
        stop_loss_pct = analysis["stop_loss_pct"]
        take_profit_pct = analysis["take_profit_pct"]
        current_price = analysis.get("current_price", 0)

        # HOLD means no action
        if action == "HOLD":
            logger.info(f"HOLD signal for {ticker} — no trade executed")
            return {
                "status": "HOLD",
                "ticker": ticker,
                "message": "Conviction below threshold. Waiting for better setup.",
            }

        account_value = self.get_account_value()

        # Pre-trade validation
        validation = self.risk_manager.validate_trade(
            ticker=ticker,
            conviction=conviction,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            account_value=account_value,
        )

        if not validation["approved"]:
            logger.warning(f"TRADE BLOCKED for {ticker}: {validation['message']}")
            return {
                "status": "BLOCKED",
                "ticker": ticker,
                "message": validation["message"],
                "failures": validation["failures"],
            }

        # Revenge trading check
        if self.risk_manager.is_revenge_trading():
            logger.warning(f"REVENGE TRADING detected — blocking {ticker} trade")
            return {
                "status": "BLOCKED",
                "ticker": ticker,
                "message": "TRADE BLOCKED: Possible revenge trading detected (3+ consecutive losses). Cool down.",
            }

        # Calculate position size
        shares = self.risk_manager.calculate_position_size(
            account_value=account_value,
            entry_price=current_price,
            stop_loss_pct=stop_loss_pct,
        )

        if shares <= 0:
            logger.warning(f"Position size too small for {ticker}")
            return {
                "status": "BLOCKED",
                "ticker": ticker,
                "message": "Position size calculation resulted in 0 shares.",
            }

        # Sanity check: max loss in dollars
        max_loss_dollars = round(shares * current_price * (stop_loss_pct / 100), 2)
        max_loss_pct_account = round((max_loss_dollars / account_value) * 100, 2)
        logger.info(
            f"Sanity check — {ticker}: {shares} shares @ ${current_price}, "
            f"max loss ${max_loss_dollars} ({max_loss_pct_account}% of account)"
        )

        # Calculate stop and target prices
        if action == "BUY":
            stop_price = round(current_price * (1 - stop_loss_pct / 100), 2)
            target_price = round(current_price * (1 + take_profit_pct / 100), 2)
            side = OrderSide.BUY
        else:  # SELL (short)
            stop_price = round(current_price * (1 + stop_loss_pct / 100), 2)
            target_price = round(current_price * (1 - take_profit_pct / 100), 2)
            side = OrderSide.SELL

        # Place market order via raw HTTP to capture X-Request-ID
        try:
            order_payload = {
                "symbol": ticker,
                "qty": str(shares),
                "side": "buy" if side == OrderSide.BUY else "sell",
                "type": "market",
                "time_in_force": "day",
            }
            resp = self._session.post(
                f"{self._base_url}/v2/orders", json=order_payload
            )
            request_id = self._capture_request_id(
                resp, "/v2/orders", "POST", ticker=ticker
            )
            resp.raise_for_status()
            order_data = resp.json()
            alpaca_order_id = order_data["id"]

            # Update the request_id record with the order_id now that we have it
            if request_id:
                self.db.save_request_id(
                    request_id=request_id,
                    endpoint="/v2/orders",
                    method="POST",
                    ticker=ticker,
                    order_id=alpaca_order_id,
                    http_status=resp.status_code,
                    success=True,
                )

            # Log trade to database
            trade_record = {
                "ticker": ticker,
                "action": action,
                "quantity": shares,
                "entry_price": current_price,
                "stop_loss_price": stop_price,
                "take_profit_price": target_price,
                "conviction": conviction,
                "order_id": alpaca_order_id,
                "reasoning": analysis.get("reasoning_summary", ""),
            }
            trade_id = self.db.save_trade(trade_record)

            logger.info(
                f"ORDER EXECUTED — {action} {shares}x {ticker} @ ~${current_price} | "
                f"SL: ${stop_price} | TP: ${target_price} | "
                f"Order ID: {alpaca_order_id} | X-Request-ID: {request_id}"
            )

            return {
                "status": "EXECUTED",
                "ticker": ticker,
                "action": action,
                "shares": shares,
                "entry_price": current_price,
                "stop_loss": stop_price,
                "take_profit": target_price,
                "max_loss": max_loss_dollars,
                "order_id": alpaca_order_id,
                "request_id": request_id,
                "trade_id": trade_id,
            }

        except http_requests.HTTPError as e:
            request_id = e.response.headers.get("X-Request-ID") if e.response is not None else None
            if request_id:
                self._capture_request_id(
                    e.response, "/v2/orders", "POST", ticker=ticker
                )
            logger.error(
                f"Order execution failed for {ticker}: {e} | X-Request-ID: {request_id}"
            )
            return {
                "status": "ERROR",
                "ticker": ticker,
                "message": f"Execution failed: {e}",
                "request_id": request_id,
            }
        except Exception as e:
            logger.error(f"Order execution failed for {ticker}: {e}")
            return {
                "status": "ERROR",
                "ticker": ticker,
                "message": f"Execution failed: {e}",
            }

    def get_positions(self) -> list[dict]:
        """Get all current open positions from Alpaca, capturing X-Request-ID."""
        try:
            resp = self._session.get(f"{self._base_url}/v2/positions")
            self._capture_request_id(resp, "/v2/positions", "GET")
            resp.raise_for_status()
            positions = resp.json()
            return [
                {
                    "ticker": p["symbol"],
                    "qty": int(p["qty"]),
                    "entry_price": float(p["avg_entry_price"]),
                    "current_price": float(p["current_price"]),
                    "unrealized_pnl": float(p["unrealized_pl"]),
                    "unrealized_pnl_pct": float(p["unrealized_plpc"]) * 100,
                }
                for p in positions
            ]
        except Exception as e:
            logger.error(f"Failed to fetch positions: {e}")
            return []

    def check_exit_conditions(self) -> list[dict]:
        """Check open positions against stop-loss and take-profit levels."""
        exits = []
        open_trades = self.db.get_open_trades()
        positions = {p["ticker"]: p for p in self.get_positions()}

        for trade in open_trades:
            ticker = trade["ticker"]
            if ticker not in positions:
                continue

            pos = positions[ticker]
            current = pos["current_price"]
            sl = trade.get("stop_loss_price")
            tp = trade.get("take_profit_price")

            should_exit = False
            reason = ""

            if trade["action"] == "BUY":
                if sl and current <= sl:
                    should_exit = True
                    reason = f"Stop-loss hit (${current} <= ${sl})"
                elif tp and current >= tp:
                    should_exit = True
                    reason = f"Take-profit hit (${current} >= ${tp})"
            else:  # SHORT
                if sl and current >= sl:
                    should_exit = True
                    reason = f"Stop-loss hit (${current} >= ${sl})"
                elif tp and current <= tp:
                    should_exit = True
                    reason = f"Take-profit hit (${current} <= ${tp})"

            if should_exit:
                pnl = pos["unrealized_pnl"]
                exits.append({
                    "trade_id": trade["id"],
                    "ticker": ticker,
                    "reason": reason,
                    "pnl": pnl,
                })
                # Close in Alpaca via raw HTTP to capture X-Request-ID
                try:
                    resp = self._session.delete(
                        f"{self._base_url}/v2/positions/{ticker}"
                    )
                    req_id = self._capture_request_id(
                        resp, f"/v2/positions/{ticker}", "DELETE", ticker=ticker
                    )
                    resp.raise_for_status()
                    self.db.close_trade(trade["id"], current, pnl)
                    self.db.update_daily_pnl(pnl, pnl > 0)
                    logger.info(
                        f"EXIT — {ticker}: {reason} | P&L: ${pnl:.2f} | X-Request-ID: {req_id}"
                    )
                except Exception as e:
                    logger.error(f"Failed to close {ticker}: {e}")

        return exits
