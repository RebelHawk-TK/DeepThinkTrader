"""Execution Agent — Places trades via Alpaca with strict risk guardrails.

Captures X-Request-ID from every Alpaca API response and persists to SQLite
for debugging and support requests.

Phases 2/4/5: Trailing stops, partial exits, time stops, limit orders,
slippage tracking, trade transparency, earnings-based exits.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

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

    # ── Phase 5a: SPY Snapshot for Circuit Breaker ────────────────

    def _get_spy_change(self) -> float:
        """Get SPY intraday change percentage for circuit breaker."""
        try:
            resp = self._session.get(
                "https://data.alpaca.markets/v2/stocks/SPY/snapshot",
                headers={
                    "APCA-API-KEY-ID": self.config.ALPACA_API_KEY,
                    "APCA-API-SECRET-KEY": self.config.ALPACA_SECRET_KEY,
                },
            )
            if resp.ok:
                data = resp.json()
                daily_bar = data.get("dailyBar", {})
                prev_close = data.get("prevDailyBar", {}).get("c", 0)
                current = daily_bar.get("c", 0)
                if prev_close > 0:
                    return ((current - prev_close) / prev_close) * 100
        except Exception as e:
            logger.debug(f"SPY snapshot failed: {e}")
        return 0.0

    # ── Phase 4a: Limit Orders for Penny Stocks ──────────────────

    def _place_limit_order(self, ticker: str, shares: int, price: float, side: str) -> dict | None:
        """Place a limit order with slippage buffer for penny stocks."""
        if side == "buy":
            limit_price = round(price * (1 + self.config.PENNY_LIMIT_SLIPPAGE_PCT / 100), 2)
        else:
            limit_price = round(price * (1 - self.config.PENNY_LIMIT_SLIPPAGE_PCT / 100), 2)

        order_payload = {
            "symbol": ticker,
            "qty": str(shares),
            "side": side,
            "type": "limit",
            "limit_price": str(limit_price),
            "time_in_force": "day",
        }
        try:
            resp = self._session.post(f"{self._base_url}/v2/orders", json=order_payload)
            request_id = self._capture_request_id(resp, "/v2/orders", "POST", ticker=ticker)
            resp.raise_for_status()
            order_data = resp.json()
            logger.info(
                f"LIMIT ORDER placed: {side.upper()} {shares}x {ticker} @ limit ${limit_price} "
                f"| Order ID: {order_data['id']} | X-Request-ID: {request_id}"
            )
            return order_data
        except Exception as e:
            logger.error(f"Limit order failed for {ticker}: {e}")
            return None

    # ── Phase 4b: Check Pending Orders ────────────────────────────

    def check_pending_orders(self) -> list[dict]:
        """Check status of open orders, cancel stale ones (> 30 min unfilled)."""
        results = []
        try:
            resp = self._session.get(f"{self._base_url}/v2/orders?status=open")
            self._capture_request_id(resp, "/v2/orders?status=open", "GET")
            if not resp.ok:
                return results
            orders = resp.json()
            for order in orders:
                created = datetime.fromisoformat(order["created_at"].replace("Z", "+00:00"))
                age_minutes = (datetime.now(created.tzinfo) - created).total_seconds() / 60

                if age_minutes > 30 and order["type"] == "limit":
                    # Cancel stale limit order
                    cancel_resp = self._session.delete(f"{self._base_url}/v2/orders/{order['id']}")
                    self._capture_request_id(cancel_resp, f"/v2/orders/{order['id']}", "DELETE", ticker=order["symbol"])
                    logger.info(f"Cancelled stale limit order: {order['symbol']} (age: {age_minutes:.0f} min)")
                    results.append({"order_id": order["id"], "ticker": order["symbol"], "action": "cancelled"})
                elif order["status"] == "filled":
                    results.append({"order_id": order["id"], "ticker": order["symbol"], "action": "filled"})
        except Exception as e:
            logger.error(f"Check pending orders failed: {e}")
        return results

    # ── Phase 5d: Trade Transparency ──────────────────────────────

    def _log_trade_summary(
        self, ticker: str, action: str, shares: int, price: float,
        risk_amount: float, account_value: float, edges_firing: int,
        rr_ratio: float, stop_price: float, target_price: float,
        avg_daily_volume: int, portfolio: str,
    ) -> str:
        """Log a plain-English pre-trade summary."""
        risk_pct = (risk_amount / account_value * 100) if account_value > 0 else 0
        summary = (
            f"{action} {shares} shares of {ticker} @ ${price:.2f}\n"
            f"  Risk: ${risk_amount:.2f} ({risk_pct:.2f}% of portfolio) | "
            f"Edges: {edges_firing}/3\n"
            f"  R:R = {rr_ratio:.1f}:1 | Stop: ${stop_price:.2f} | Target: ${target_price:.2f}\n"
            f"  Portfolio: {portfolio} | ADV: {avg_daily_volume:,}"
        )
        logger.info(f"TRADE SUMMARY:\n{summary}")
        return summary

    # ── Main Execute Method ───────────────────────────────────────

    def execute(self, analysis: dict, portfolio: str = "main") -> dict:
        """Execute a trade based on DeepThink analysis, with full safety checks."""
        ticker = analysis["ticker"]
        action = analysis["action"]
        conviction = analysis["conviction"]
        stop_loss_pct = analysis["stop_loss_pct"]
        take_profit_pct = analysis["take_profit_pct"]
        current_price = analysis.get("current_price", 0)
        edges_firing = analysis.get("edges_firing", 0)

        # HOLD means no action
        if action == "HOLD":
            logger.info(f"HOLD signal for {ticker} — no trade executed")
            return {
                "status": "HOLD",
                "ticker": ticker,
                "message": "Conviction below threshold or insufficient edges. Waiting for better setup.",
            }

        account_value = self.get_account_value()

        # Get average daily volume for liquidity check
        avg_daily_volume = self._get_avg_daily_volume(ticker)

        # Get SPY change for circuit breaker
        spy_change = self._get_spy_change()

        # Calculate position size first (needed for liquidity check)
        shares = self.risk_manager.calculate_position_size(
            account_value=account_value,
            entry_price=current_price,
            stop_loss_pct=stop_loss_pct,
            portfolio=portfolio,
        )

        # Apply volatility adjustment if ATR data available
        adv_tech = analysis.get("advanced_technicals", {})
        if adv_tech:
            atr_data = adv_tech.get("atr", {})
            current_atr = atr_data.get("atr", 0) if atr_data else 0
            if current_atr > 0:
                # Use current_atr as both current and median for now (will improve with historical)
                vol_mult = self.risk_manager.check_volatility_adjustment(current_atr, current_atr * 0.7)
                if vol_mult < 1.0:
                    shares = int(shares * vol_mult)

        # Pre-trade validation with new checks
        validation = self.risk_manager.validate_trade(
            ticker=ticker,
            conviction=conviction,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            account_value=account_value,
            portfolio=portfolio,
            action=action,
            proposed_shares=shares,
            avg_daily_volume=avg_daily_volume,
            spy_change_pct=spy_change,
            edges_firing=edges_firing,
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
        if self.risk_manager.is_revenge_trading(portfolio=portfolio):
            logger.warning(f"REVENGE TRADING detected — blocking {ticker} trade")
            return {
                "status": "BLOCKED",
                "ticker": ticker,
                "message": "TRADE BLOCKED: Possible revenge trading detected (3+ consecutive losses). Cool down.",
            }

        if shares <= 0:
            logger.warning(f"Position size too small for {ticker}")
            return {
                "status": "BLOCKED",
                "ticker": ticker,
                "message": "Position size calculation resulted in 0 shares.",
            }

        # Auto-reduce if liquidity constrained
        max_liq_shares = avg_daily_volume // self.config.MIN_ADV_RATIO if avg_daily_volume > 0 else shares
        if shares > max_liq_shares > 0:
            logger.info(f"Reducing {ticker} from {shares} to {max_liq_shares} shares (liquidity)")
            shares = max_liq_shares

        # Sanity check: max loss in dollars
        risk_per_share = current_price * (stop_loss_pct / 100)
        risk_amount = round(shares * risk_per_share, 2)
        max_loss_pct_account = round((risk_amount / account_value) * 100, 2)

        # Calculate stop and target prices
        if action == "BUY":
            stop_price = round(current_price * (1 - stop_loss_pct / 100), 2)
            target_price = round(current_price * (1 + take_profit_pct / 100), 2)
            side = OrderSide.BUY
        else:  # SELL (short)
            stop_price = round(current_price * (1 + stop_loss_pct / 100), 2)
            target_price = round(current_price * (1 - take_profit_pct / 100), 2)
            side = OrderSide.SELL

        rr_ratio = take_profit_pct / stop_loss_pct if stop_loss_pct > 0 else 0

        # Phase 5d: Trade transparency — log summary before execution
        self._log_trade_summary(
            ticker, action, shares, current_price, risk_amount,
            account_value, edges_firing, rr_ratio, stop_price, target_price,
            avg_daily_volume, portfolio,
        )

        # Phase 4a: Use limit orders for penny stocks
        use_limit = portfolio == "penny"

        try:
            if use_limit:
                order_data = self._place_limit_order(
                    ticker, shares, current_price, "buy" if side == OrderSide.BUY else "sell"
                )
                if not order_data:
                    return {"status": "ERROR", "ticker": ticker, "message": "Limit order placement failed"}
                alpaca_order_id = order_data["id"]
                request_id = None
            else:
                # Place market order via raw HTTP to capture X-Request-ID
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

                # Update the request_id record with the order_id
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

            # Log trade to database with new fields
            edge_details_json = ""
            try:
                import json
                edge_details_json = json.dumps(analysis.get("edge_details", []))
            except Exception:
                pass

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
            trade_id = self.db.save_trade(trade_record, portfolio=portfolio)

            # Set original_quantity and edge data on the trade
            with self.db._get_conn() as conn:
                conn.execute(
                    """UPDATE trades SET original_quantity = ?, highest_price = ?,
                       edges_fired = ?, edge_details = ?, risk_amount = ?
                       WHERE id = ?""",
                    (shares, current_price, edges_firing, edge_details_json, risk_amount, trade_id),
                )

            logger.info(
                f"ORDER EXECUTED — {action} {shares}x {ticker} @ ~${current_price} | "
                f"SL: ${stop_price} | TP: ${target_price} | Edges: {edges_firing}/3 | "
                f"Order ID: {alpaca_order_id} | Risk: ${risk_amount}"
            )

            return {
                "status": "EXECUTED",
                "ticker": ticker,
                "action": action,
                "shares": shares,
                "entry_price": current_price,
                "stop_loss": stop_price,
                "take_profit": target_price,
                "max_loss": risk_amount,
                "order_id": alpaca_order_id,
                "request_id": request_id if not use_limit else None,
                "trade_id": trade_id,
                "edges_firing": edges_firing,
                "rr_ratio": rr_ratio,
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

    # ── Phase 4b: Slippage Tracking ───────────────────────────────

    def _check_fill_slippage(self, order_id: str, expected_price: float, ticker: str) -> float | None:
        """Check actual fill price vs expected and log slippage."""
        try:
            resp = self._session.get(f"{self._base_url}/v2/orders/{order_id}")
            if resp.ok:
                order = resp.json()
                filled_price = float(order.get("filled_avg_price", 0))
                if filled_price > 0 and expected_price > 0:
                    slippage_pct = ((filled_price - expected_price) / expected_price) * 100
                    if abs(slippage_pct) > self.config.MAX_SLIPPAGE_PCT:
                        logger.warning(
                            f"SLIPPAGE ALERT: {ticker} filled at ${filled_price:.2f} "
                            f"(expected ${expected_price:.2f}, slippage {slippage_pct:+.2f}%)"
                        )
                    return slippage_pct
        except Exception as e:
            logger.debug(f"Slippage check failed for {ticker}: {e}")
        return None

    # ── Helper: Average Daily Volume ──────────────────────────────

    def _get_avg_daily_volume(self, ticker: str) -> int:
        """Fetch 20-day average daily volume from Alpaca snapshot."""
        try:
            resp = self._session.get(
                f"https://data.alpaca.markets/v2/stocks/{ticker}/snapshot",
                headers={
                    "APCA-API-KEY-ID": self.config.ALPACA_API_KEY,
                    "APCA-API-SECRET-KEY": self.config.ALPACA_SECRET_KEY,
                },
            )
            if resp.ok:
                data = resp.json()
                # Use daily bar volume as approximation
                daily_vol = data.get("dailyBar", {}).get("v", 0)
                # For a better estimate, fetch 20-day bars
                bars_resp = self._session.get(
                    f"https://data.alpaca.markets/v2/stocks/{ticker}/bars",
                    headers={
                        "APCA-API-KEY-ID": self.config.ALPACA_API_KEY,
                        "APCA-API-SECRET-KEY": self.config.ALPACA_SECRET_KEY,
                    },
                    params={"timeframe": "1Day", "limit": "20", "feed": "iex"},
                )
                if bars_resp.ok:
                    bars = bars_resp.json().get("bars", [])
                    if bars:
                        avg_vol = sum(b.get("v", 0) for b in bars) // len(bars)
                        return avg_vol
                return daily_vol
        except Exception as e:
            logger.debug(f"ADV fetch failed for {ticker}: {e}")
        return 0

    # ── Positions ─────────────────────────────────────────────────

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

    # ── Phase 2: Enhanced Exit Conditions ─────────────────────────

    def check_exit_conditions(self) -> list[dict]:
        """Check open positions against SL, TP, trailing stops, time stops, and earnings."""
        exits = []
        open_trades = self.db.get_open_trades()
        positions = {p["ticker"]: p for p in self.get_positions()}

        for trade in open_trades:
            ticker = trade["ticker"]
            if ticker not in positions:
                continue

            pos = positions[ticker]
            current = pos["current_price"]
            entry = trade.get("entry_price", 0)
            sl = trade.get("stop_loss_price")
            tp = trade.get("take_profit_price")
            trailing_active = trade.get("trailing_stop_active", 0)
            trailing_stop = trade.get("trailing_stop_price")
            highest = trade.get("highest_price", entry)

            should_exit = False
            partial_exit = False
            exit_qty = 0
            reason = ""

            is_long = trade["action"] == "BUY"

            # Phase 2b: Update trailing stop
            if is_long and current > (highest or 0):
                highest = current
            elif not is_long and (highest == 0 or current < highest):
                highest = current

            # Check trailing stop activation
            if entry and entry > 0:
                profit_pct = ((current - entry) / entry * 100) if is_long else ((entry - current) / entry * 100)
                portfolio = trade.get("portfolio", "main")
                trail_dist = (
                    self.config.PENNY_TRAILING_STOP_DISTANCE_PCT
                    if portfolio == "penny"
                    else self.config.TRAILING_STOP_DISTANCE_PCT
                )

                if profit_pct >= self.config.TRAILING_STOP_ACTIVATION_PCT and not trailing_active:
                    # Activate trailing stop
                    trailing_active = True
                    if is_long:
                        trailing_stop = round(highest * (1 - trail_dist / 100), 2)
                    else:
                        trailing_stop = round(highest * (1 + trail_dist / 100), 2)
                    self.db.update_trailing_stop(trade["id"], highest, trailing_stop, True)
                    logger.info(
                        f"Trailing stop ACTIVATED for {ticker}: "
                        f"trail=${trailing_stop}, highest=${highest}, profit={profit_pct:.1f}%"
                    )
                elif trailing_active:
                    # Update trailing stop
                    if is_long:
                        new_trail = round(highest * (1 - trail_dist / 100), 2)
                        if new_trail > (trailing_stop or 0):
                            trailing_stop = new_trail
                    else:
                        new_trail = round(highest * (1 + trail_dist / 100), 2)
                        if trailing_stop is None or new_trail < trailing_stop:
                            trailing_stop = new_trail
                    self.db.update_trailing_stop(trade["id"], highest, trailing_stop, True)

                # Phase 2c: Partial scale-out
                if self.config.SCALE_OUT_ENABLED and entry > 0:
                    risk_amount = trade.get("risk_amount", 0)
                    original_qty = trade.get("original_quantity", trade["quantity"])
                    current_qty = trade["quantity"]

                    if risk_amount and risk_amount > 0 and original_qty and current_qty > 1:
                        r_per_share = risk_amount / original_qty if original_qty > 0 else 0
                        current_profit_per_share = (current - entry) if is_long else (entry - current)

                        if r_per_share > 0:
                            r_multiple = current_profit_per_share / r_per_share

                            for level_idx, level in enumerate(self.config.SCALE_OUT_LEVELS):
                                # Check if we should scale out at this R level
                                scale_qty = int(original_qty * 0.33)
                                remaining_for_level = original_qty - (scale_qty * (level_idx + 1))

                                if r_multiple >= level and current_qty > remaining_for_level and scale_qty > 0:
                                    exit_qty = min(scale_qty, current_qty - 1)
                                    if exit_qty > 0:
                                        partial_exit = True
                                        reason = f"Scale-out at {level}R (profit: {r_multiple:.1f}R)"
                                        break

            # Phase 2d: Time stop
            if not should_exit and not partial_exit:
                try:
                    entry_time = datetime.fromisoformat(trade["timestamp"])
                    days_held = (datetime.now() - entry_time).days
                    if days_held >= self.config.TIME_STOP_DAYS:
                        # Check if position has moved meaningfully (> 1x ATR equivalent, ~2%)
                        if entry and abs(current - entry) / entry * 100 < 2.0:
                            should_exit = True
                            reason = f"Time stop: {days_held} days held with < 2% movement"
                except Exception:
                    pass

            # Phase 5b: Earnings proximity exit
            if not should_exit and not partial_exit:
                earnings = self.risk_manager.check_earnings_proximity(ticker)
                if earnings["near_earnings"]:
                    if self.config.EARNINGS_EXIT_MODE == "close":
                        should_exit = True
                        reason = f"Earnings in {earnings['days_until']} days — auto-closing"
                    elif self.config.EARNINGS_EXIT_MODE == "tighten":
                        # Tighten stop to 50% of current distance
                        if sl and entry:
                            if is_long:
                                tightened = round(current - (current - sl) * 0.5, 2)
                                if tightened > sl:
                                    sl = tightened
                                    with self.db._get_conn() as conn:
                                        conn.execute(
                                            "UPDATE trades SET stop_loss_price = ? WHERE id = ?",
                                            (sl, trade["id"]),
                                        )
                                    logger.info(f"Earnings tighten: {ticker} SL moved to ${sl}")

            # Check exit conditions
            if not should_exit and not partial_exit:
                if is_long:
                    if trailing_active and trailing_stop and current <= trailing_stop:
                        should_exit = True
                        reason = f"Trailing stop hit (${current} <= ${trailing_stop})"
                    elif sl and current <= sl:
                        should_exit = True
                        reason = f"Stop-loss hit (${current} <= ${sl})"
                    elif tp and current >= tp:
                        should_exit = True
                        reason = f"Take-profit hit (${current} >= ${tp})"
                else:  # SHORT
                    if trailing_active and trailing_stop and current >= trailing_stop:
                        should_exit = True
                        reason = f"Trailing stop hit (${current} >= ${trailing_stop})"
                    elif sl and current >= sl:
                        should_exit = True
                        reason = f"Stop-loss hit (${current} >= ${sl})"
                    elif tp and current <= tp:
                        should_exit = True
                        reason = f"Take-profit hit (${current} <= ${tp})"

            # Execute partial exit
            if partial_exit and exit_qty > 0:
                try:
                    side = "sell" if is_long else "buy"
                    order_payload = {
                        "symbol": ticker,
                        "qty": str(exit_qty),
                        "side": side,
                        "type": "market",
                        "time_in_force": "day",
                    }
                    resp = self._session.post(f"{self._base_url}/v2/orders", json=order_payload)
                    req_id = self._capture_request_id(resp, "/v2/orders", "POST", ticker=ticker)
                    resp.raise_for_status()
                    order_data = resp.json()

                    partial_pnl = exit_qty * (current - entry if is_long else entry - current)
                    new_qty = trade["quantity"] - exit_qty

                    self.db.save_partial_exit(
                        trade["id"], exit_qty, current, partial_pnl, reason, order_data["id"]
                    )
                    self.db.update_trade_quantity(trade["id"], new_qty)
                    self.db.update_daily_pnl(partial_pnl, partial_pnl > 0)

                    logger.info(
                        f"PARTIAL EXIT — {ticker}: {exit_qty} shares @ ${current} | "
                        f"{reason} | P&L: ${partial_pnl:.2f} | Remaining: {new_qty}"
                    )
                    exits.append({
                        "trade_id": trade["id"],
                        "ticker": ticker,
                        "reason": reason,
                        "pnl": partial_pnl,
                        "partial": True,
                        "qty_sold": exit_qty,
                        "qty_remaining": new_qty,
                    })
                except Exception as e:
                    logger.error(f"Partial exit failed for {ticker}: {e}")

            # Execute full exit
            if should_exit:
                pnl = pos["unrealized_pnl"]
                exits.append({
                    "trade_id": trade["id"],
                    "ticker": ticker,
                    "reason": reason,
                    "pnl": pnl,
                })
                try:
                    resp = self._session.delete(
                        f"{self._base_url}/v2/positions/{ticker}"
                    )
                    req_id = self._capture_request_id(
                        resp, f"/v2/positions/{ticker}", "DELETE", ticker=ticker
                    )
                    resp.raise_for_status()
                    self.db.close_trade(trade["id"], current, pnl, exit_reason=reason)
                    self.db.update_daily_pnl(pnl, pnl > 0)
                    logger.info(
                        f"EXIT — {ticker}: {reason} | P&L: ${pnl:.2f} | X-Request-ID: {req_id}"
                    )
                except Exception as e:
                    logger.error(f"Failed to close {ticker}: {e}")

        return exits
