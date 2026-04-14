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
from utils.notifications import notify_trade_executed, notify_trade_exited
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

    # ── Phase 6a: Bid-Ask Spread Check ──────────────────────────

    def _get_spread_pct(self, ticker: str) -> float:
        """Fetch current bid-ask spread as percentage of mid price.

        Wide spreads cause hidden slippage on market orders.
        Returns 0.0 if quote unavailable.
        """
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
                quote = data.get("latestQuote", {})
                bid = quote.get("bp", 0)
                ask = quote.get("ap", 0)
                if bid > 0 and ask > 0:
                    mid = (bid + ask) / 2
                    spread_pct = ((ask - bid) / mid) * 100
                    logger.info(f"Spread for {ticker}: bid=${bid:.2f}, ask=${ask:.2f}, spread={spread_pct:.2f}%")
                    return round(spread_pct, 3)
        except Exception as e:
            logger.debug(f"Spread check failed for {ticker}: {e}")
        return 0.0

    # ── Phase 6b: VIX Level ────────────────────────────────────

    def _get_vix_level(self) -> float:
        """Fetch current VIX level. Returns 0.0 if unavailable."""
        try:
            import yfinance as yf
            vix = yf.Ticker("^VIX")
            hist = vix.history(period="1d")
            if not hist.empty:
                level = float(hist["Close"].iloc[-1])
                logger.info(f"VIX level: {level:.1f}")
                return level
        except Exception as e:
            logger.debug(f"VIX fetch failed: {e}")
        return 0.0

    # ── Phase 6c: Sector Lookup ────────────────────────────────

    _sector_cache: dict[str, str] = {}

    def _get_sector(self, ticker: str) -> str:
        """Get GICS sector for a ticker. Cached to avoid repeated lookups."""
        if ticker in self._sector_cache:
            return self._sector_cache[ticker]
        try:
            import yfinance as yf
            stock = yf.Ticker(ticker)
            info = stock.info
            sector = info.get("sector", "Unknown")
            self._sector_cache[ticker] = sector
            return sector
        except Exception as e:
            logger.debug(f"Sector lookup failed for {ticker}: {e}")
            self._sector_cache[ticker] = "Unknown"
            return "Unknown"

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
        analysis: dict | None = None,
    ) -> str:
        """Log a plain-English pre-trade summary with thesis and invalidation."""
        risk_pct = (risk_amount / account_value * 100) if account_value > 0 else 0
        summary = (
            f"{action} {shares} shares of {ticker} @ ${price:.2f}\n"
            f"  Risk: ${risk_amount:.2f} ({risk_pct:.2f}% of portfolio) | "
            f"Edges: {edges_firing}/3\n"
            f"  R:R = {rr_ratio:.1f}:1 | Stop: ${stop_price:.2f} | Target: ${target_price:.2f}\n"
            f"  Portfolio: {portfolio} | ADV: {avg_daily_volume:,}"
        )

        # Add thesis from analysis reasoning
        if analysis:
            reasoning = analysis.get("reasoning_summary", "")
            if reasoning:
                summary += f"\n  Thesis: {reasoning}"

            # Add invalidation criteria from top risks
            risks = analysis.get("risks", [])
            if risks:
                invalidation = "; ".join(risks[:3])
                summary += f"\n  Invalidated if: {invalidation}"

            # Add Claude's qualitative note if present
            claude = analysis.get("claude_analysis") or {}
            if claude.get("qualitative_assessment"):
                summary += f"\n  AI Note: {claude['qualitative_assessment']}"

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

        # Phase 6b: Get VIX level for volatility circuit breaker
        vix_level = self._get_vix_level()

        # Phase 6a: Get bid-ask spread
        spread_pct = self._get_spread_pct(ticker)

        # Phase 6c: Get sector for concentration check
        sector = self._get_sector(ticker)

        # Calculate position size first (needed for liquidity check)
        shares = self.risk_manager.calculate_position_size(
            account_value=account_value,
            entry_price=current_price,
            stop_loss_pct=stop_loss_pct,
            portfolio=portfolio,
        )

        # Apply volatility adjustment if ATR data available — uses real historical median
        adv_tech = analysis.get("advanced_technicals", {})
        current_atr = 0.0
        if adv_tech:
            atr_data = adv_tech.get("atr", {})
            current_atr = atr_data.get("atr", 0) if atr_data else 0
            if current_atr > 0:
                # Store today's ATR
                self.db.save_atr(ticker, current_atr)
                # get_median_atr auto-seeds from yfinance if insufficient history
                median_atr = self.db.get_median_atr(ticker)
                if median_atr > 0:
                    vol_mult = self.risk_manager.check_volatility_adjustment(current_atr, median_atr)
                    if vol_mult < 1.0:
                        shares = int(shares * vol_mult)

        # Phase 6d: Overnight gap risk — reduce position for high-gap-risk names
        fundamentals = analysis.get("fundamentals", {})
        beta = fundamentals.get("financials", {}).get("beta", 1.0) if fundamentals else 1.0
        earnings_info = self.risk_manager.check_earnings_proximity(ticker)
        gap_mult = self.risk_manager.calculate_gap_risk_multiplier(
            current_atr=current_atr,
            current_price=current_price,
            beta=beta or 1.0,
            near_earnings=earnings_info.get("near_earnings", False),
        )
        if gap_mult < 1.0:
            original_shares = shares
            shares = max(1, int(shares * gap_mult))
            logger.info(f"Gap risk: {ticker} position reduced {original_shares} → {shares} shares")

        # Phase 8c: Sector rotation awareness — warn if sector is weak
        if sector and sector != "Unknown":
            sector_trend = self.risk_manager.check_sector_trend(sector)
            if not sector_trend["uptrend"]:
                logger.warning(
                    f"SECTOR WEAK: {sector} ({sector_trend['etf']}) below 50-SMA — "
                    f"trade in {ticker} carries sector headwind risk"
                )

        # Pre-trade validation with all checks
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
            spread_pct=spread_pct,
            vix_level=vix_level,
            sector=sector,
            entry_price=current_price,
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

        # Hard cap: if dollar risk exceeds configured max risk per trade, tighten the stop
        params = self.risk_manager._get_params(portfolio)
        max_allowed_risk = account_value * params["max_risk_per_trade"]
        if risk_amount > max_allowed_risk and shares > 0 and current_price > 0:
            # Recalculate stop_loss_pct so dollar risk = max_allowed_risk
            max_risk_per_share = max_allowed_risk / shares
            capped_stop_pct = round((max_risk_per_share / current_price) * 100, 2)
            logger.warning(
                f"STOP CAP: {ticker} stop tightened from {stop_loss_pct:.1f}% to {capped_stop_pct:.1f}% "
                f"(risk ${risk_amount:.0f} > max ${max_allowed_risk:.0f})"
            )
            stop_loss_pct = capped_stop_pct
            take_profit_pct = round(stop_loss_pct * params["min_reward_risk_ratio"], 1)
            risk_per_share = current_price * (stop_loss_pct / 100)
            risk_amount = round(shares * risk_per_share, 2)

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

        # Phase 8a: Warn if this ticker has historically bad slippage
        historical_slippage = self.db.get_ticker_slippage_avg(ticker)
        if abs(historical_slippage) > 0.5:
            logger.warning(
                f"SLIPPAGE WARNING: {ticker} has avg slippage of {historical_slippage:+.2f}% "
                f"from past trades — consider limit order"
            )

        # Phase 5d: Trade transparency — log summary before execution
        trade_summary = self._log_trade_summary(
            ticker, action, shares, current_price, risk_amount,
            account_value, edges_firing, rr_ratio, stop_price, target_price,
            avg_daily_volume, portfolio, analysis=analysis,
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

                # Phase 7c: Poll order status for fill confirmation
                fill_result = self._poll_order_status(alpaca_order_id, ticker, shares)
                if fill_result["status"] in ("rejected", "canceled", "expired", "suspended"):
                    # Retry once as a limit order
                    side_str = "buy" if side == OrderSide.BUY else "sell"
                    retry_order = self._retry_as_limit_order(ticker, shares, current_price, side_str)
                    if retry_order:
                        alpaca_order_id = retry_order["id"]
                        logger.info(f"Order retried as limit: {alpaca_order_id}")
                    else:
                        return {
                            "status": "ERROR",
                            "ticker": ticker,
                            "message": f"Order {fill_result['status']} and retry failed",
                        }
                elif fill_result["filled_qty"] > 0 and fill_result["filled_qty"] < shares:
                    # Partial fill — adjust shares to what actually filled
                    shares = fill_result["filled_qty"]
                    current_price = fill_result["filled_price"] or current_price
                    risk_per_share = current_price * (stop_loss_pct / 100)
                    risk_amount = round(shares * risk_per_share, 2)
                    logger.warning(
                        f"PARTIAL FILL for {ticker}: adjusted to {shares} shares @ ${current_price:.2f}"
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
                "reasoning": trade_summary,
            }
            trade_id = self.db.save_trade(trade_record, portfolio=portfolio)

            # Set original_quantity, edge data, and sector on the trade
            with self.db._get_conn() as conn:
                conn.execute(
                    """UPDATE trades SET original_quantity = ?, highest_price = ?,
                       edges_fired = ?, edge_details = ?, risk_amount = ?, sector = ?
                       WHERE id = ?""",
                    (shares, current_price, edges_firing, edge_details_json, risk_amount, sector, trade_id),
                )

            # Phase 8a: Record slippage after fill
            fill_check = self._check_fill_slippage(alpaca_order_id, current_price, ticker)
            if fill_check is not None:
                order_type_str = "limit" if use_limit else "market"
                side_str = "buy" if side == OrderSide.BUY else "sell"
                # Get actual filled price for slippage record
                try:
                    fill_resp = self._session.get(f"{self._base_url}/v2/orders/{alpaca_order_id}")
                    if fill_resp.ok:
                        actual_price = float(fill_resp.json().get("filled_avg_price", 0) or 0)
                        if actual_price > 0:
                            self.db.save_slippage(
                                ticker, current_price, actual_price,
                                order_type_str, side_str, shares, portfolio,
                            )
                except Exception:
                    pass

            logger.info(
                f"ORDER EXECUTED — {action} {shares}x {ticker} @ ~${current_price} | "
                f"SL: ${stop_price} | TP: ${target_price} | Edges: {edges_firing}/3 | "
                f"Order ID: {alpaca_order_id} | Risk: ${risk_amount}"
            )
            notify_trade_executed(
                ticker, action, shares, current_price, conviction,
                reasoning=trade_summary[:200] if trade_summary else "",
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

    # ── Phase 7c: Order Status Polling & Partial Fill Handling ────

    def _poll_order_status(self, order_id: str, ticker: str, expected_qty: int, timeout_seconds: int = 30) -> dict:
        """Poll order status and handle partial fills and rejections.

        Returns {"status": str, "filled_qty": int, "filled_price": float, "order_id": str}.
        """
        import time

        deadline = time.time() + timeout_seconds
        last_status = "new"

        while time.time() < deadline:
            try:
                resp = self._session.get(f"{self._base_url}/v2/orders/{order_id}")
                if not resp.ok:
                    break
                order = resp.json()
                status = order.get("status", "")
                filled_qty = int(order.get("filled_qty", 0) or 0)
                filled_price = float(order.get("filled_avg_price", 0) or 0)
                last_status = status

                if status == "filled":
                    if filled_qty < expected_qty:
                        logger.warning(
                            f"PARTIAL FILL: {ticker} — expected {expected_qty}, got {filled_qty} "
                            f"@ ${filled_price:.2f}"
                        )
                    return {
                        "status": "filled",
                        "filled_qty": filled_qty,
                        "filled_price": filled_price,
                        "order_id": order_id,
                    }
                elif status == "partially_filled":
                    logger.info(
                        f"Order {order_id} partially filled: {filled_qty}/{expected_qty} "
                        f"for {ticker} @ ${filled_price:.2f}"
                    )
                    # Continue polling — may fill completely
                elif status in ("rejected", "canceled", "expired", "suspended"):
                    logger.warning(f"Order {order_id} {status} for {ticker}")
                    return {
                        "status": status,
                        "filled_qty": filled_qty,
                        "filled_price": filled_price,
                        "order_id": order_id,
                    }
                # new, accepted, pending_new — keep polling

            except Exception as e:
                logger.debug(f"Order poll error for {order_id}: {e}")

            time.sleep(2)

        # Timeout — check final state
        logger.info(f"Order {order_id} poll timeout (status={last_status}) for {ticker}")
        return {
            "status": last_status,
            "filled_qty": 0,
            "filled_price": 0.0,
            "order_id": order_id,
        }

    def _retry_as_limit_order(self, ticker: str, shares: int, price: float, side: str) -> dict | None:
        """Retry a failed market order as a limit order with slippage buffer."""
        limit_price = round(price * (1 + self.config.MAX_SLIPPAGE_PCT / 100), 2) if side == "buy" else \
                      round(price * (1 - self.config.MAX_SLIPPAGE_PCT / 100), 2)

        logger.info(f"RETRY: placing limit order for {shares}x {ticker} @ ${limit_price} ({side})")
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
            self._capture_request_id(resp, "/v2/orders", "POST", ticker=ticker)
            resp.raise_for_status()
            order_data = resp.json()
            logger.info(f"RETRY limit order placed: {order_data['id']} for {ticker}")
            return order_data
        except Exception as e:
            logger.error(f"Retry limit order failed for {ticker}: {e}")
            return None

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

    def _get_daily_high_low(self, ticker: str) -> tuple[float, float]:
        """Fetch today's intraday high and low from Alpaca snapshot.

        Prevents trailing stop race condition where a spike+reversal within
        one check cycle would miss the true high.
        """
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
                daily = data.get("dailyBar", {})
                return float(daily.get("h", 0)), float(daily.get("l", 0))
        except Exception as e:
            logger.debug(f"Daily high/low fetch failed for {ticker}: {e}")
        return 0.0, 0.0

    # ── Phase 7a: Momentum Divergence Exit ─────────────────────

    def _check_momentum_divergence(self, ticker: str, entry: float, current: float, is_long: bool) -> dict:
        """Check if RSI/MACD signals suggest momentum is fading on a profitable position.

        Returns {"should_tighten": bool, "should_exit": bool, "reason": str}.
        """
        result = {"should_tighten": False, "should_exit": False, "reason": ""}

        if entry <= 0:
            return result

        profit_pct = ((current - entry) / entry * 100) if is_long else ((entry - current) / entry * 100)
        if profit_pct <= 0:
            return result  # Only check divergence on profitable positions

        try:
            from utils.alpaca_data import AlpacaMarketData
            alpaca = AlpacaMarketData(self.db)
            tech = alpaca.get_technicals(ticker)
            if "error" in tech:
                return result

            rsi = tech.get("rsi_14", 50)

            # RSI overbought on a profitable long — tighten stop
            if is_long and rsi > 75:
                result["should_tighten"] = True
                result["reason"] = f"Momentum divergence: RSI overbought ({rsi:.0f}) on profitable position"
                logger.info(f"MOMENTUM WARN {ticker}: RSI={rsi:.0f}, profit={profit_pct:.1f}% — tightening stop")

            # RSI oversold on a profitable short — tighten stop
            if not is_long and rsi < 25:
                result["should_tighten"] = True
                result["reason"] = f"Momentum divergence: RSI oversold ({rsi:.0f}) on profitable short"

            # Strong reversal signal: RSI was overbought and now dropping fast
            if is_long and rsi > 70 and profit_pct > 5:
                # Check if price is near daily high but volume is weak
                vol_ratio = tech.get("volume_ratio", 1.0)
                if vol_ratio < 0.7:
                    result["should_tighten"] = True
                    result["reason"] = (
                        f"Momentum fading: RSI={rsi:.0f}, volume weak ({vol_ratio:.1f}x avg), "
                        f"profit={profit_pct:.1f}% — tightening stop"
                    )

        except Exception as e:
            logger.debug(f"Momentum divergence check failed for {ticker}: {e}")

        return result

    def _reconcile_missing_position(self, trade: dict, exits: list[dict]) -> None:
        """Reconcile a DB trade marked OPEN whose position no longer exists in Alpaca.

        Queries Alpaca closed orders to find the actual exit price and P&L,
        then closes the trade in the DB so it can be used for learning.
        """
        ticker = trade["ticker"]
        trade_id = trade["id"]
        entry = trade.get("entry_price", 0)
        qty = trade.get("quantity", 0)
        is_long = trade.get("action") == "BUY"

        try:
            # Look for recent sell orders for this ticker
            side_filter = "sell" if is_long else "buy"
            resp = self._session.get(
                f"{self._base_url}/v2/orders",
                params={
                    "status": "closed",
                    "symbols": ticker,
                    "limit": 10,
                    "direction": "desc",
                },
            )
            if not resp.ok:
                logger.warning(f"DB SYNC: Could not query orders for {ticker} (HTTP {resp.status_code})")
                return

            orders = resp.json()
            exit_order = None
            for order in orders:
                if order.get("side") == side_filter and order.get("status") == "filled":
                    filled_price = float(order.get("filled_avg_price", 0) or 0)
                    if filled_price > 0:
                        exit_order = order
                        break

            if exit_order:
                exit_price = float(exit_order["filled_avg_price"])
                filled_qty = int(exit_order.get("filled_qty", qty) or qty)
                if is_long:
                    pnl = round((exit_price - entry) * filled_qty, 2)
                else:
                    pnl = round((entry - exit_price) * filled_qty, 2)

                self.db.close_trade(trade_id, exit_price, pnl, exit_reason="alpaca_reconcile")
                self.db.update_daily_pnl(pnl, pnl > 0)
                logger.info(
                    f"DB SYNC: Reconciled {ticker} — closed at ${exit_price:.2f}, "
                    f"P&L: ${pnl:+.2f} (was missing from Alpaca positions)"
                )
                exits.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "reason": "alpaca_reconcile",
                    "pnl": pnl,
                })
            else:
                # No matching sell order found — close at last known price as fallback
                logger.warning(
                    f"DB SYNC: No exit order found for {ticker} — marking CLOSED with estimated P&L"
                )
                try:
                    import yfinance as yf
                    last_price = float(yf.Ticker(ticker).history(period="1d")["Close"].iloc[-1])
                except Exception:
                    last_price = entry  # worst case: 0 P&L

                if is_long:
                    pnl = round((last_price - entry) * qty, 2)
                else:
                    pnl = round((entry - last_price) * qty, 2)

                self.db.close_trade(trade_id, last_price, pnl, exit_reason="alpaca_reconcile_estimated")
                self.db.update_daily_pnl(pnl, pnl > 0)
                logger.info(
                    f"DB SYNC: Reconciled {ticker} (estimated) — ${last_price:.2f}, "
                    f"P&L: ${pnl:+.2f}"
                )
                exits.append({
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "reason": "alpaca_reconcile_estimated",
                    "pnl": pnl,
                })

        except Exception as e:
            # Retry once after 2s — DB lock is the most common failure
            logger.warning(f"DB SYNC failed for {ticker}: {e} — retrying in 2s")
            import time
            time.sleep(2)
            try:
                # Simplified retry: just close the trade at last known price
                import yfinance as yf
                try:
                    last_price = float(yf.Ticker(ticker).history(period="1d")["Close"].iloc[-1])
                except Exception:
                    last_price = entry
                pnl = round((last_price - entry) * qty, 2) if is_long else round((entry - last_price) * qty, 2)
                self.db.close_trade(trade_id, last_price, pnl, exit_reason="alpaca_reconcile_retry")
                logger.info(f"DB SYNC retry succeeded for {ticker} — closed at ${last_price:.2f}, P&L: ${pnl:+.2f}")
                exits.append({"trade_id": trade_id, "ticker": ticker, "reason": "alpaca_reconcile_retry", "pnl": pnl})
            except Exception as e2:
                logger.error(f"DB SYNC retry also failed for {ticker}: {e2}")

    def check_exit_conditions(self) -> list[dict]:
        """Check open positions against SL, TP, trailing stops, time stops, momentum, and earnings."""
        exits = []
        open_trades = self.db.get_open_trades()
        positions = {p["ticker"]: p for p in self.get_positions()}

        for trade in open_trades:
            ticker = trade["ticker"]
            if ticker not in positions:
                # Position gone from Alpaca but still OPEN in DB — reconcile
                self._reconcile_missing_position(trade, exits)
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

            # Phase 7 fix: Use daily high/low instead of just current price
            # to prevent trailing stop race condition on intraday spikes
            daily_high, daily_low = self._get_daily_high_low(ticker)

            if is_long:
                # Use the greater of current price and today's intraday high
                peak = max(current, daily_high) if daily_high > 0 else current
                if peak > (highest or 0):
                    highest = peak
            else:
                trough = min(current, daily_low) if daily_low > 0 else current
                if highest == 0 or trough < highest:
                    highest = trough

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

            # Phase 7a: Momentum divergence exit — tighten stop if RSI overbought on profit
            if not should_exit and not partial_exit and entry and entry > 0:
                momentum = self._check_momentum_divergence(ticker, entry, current, is_long)
                if momentum["should_tighten"] and sl and entry:
                    if is_long:
                        # Tighten stop to 50% of current distance
                        tightened = round(current - (current - sl) * 0.5, 2)
                        if tightened > sl:
                            sl = tightened
                            with self.db._get_conn() as conn:
                                conn.execute(
                                    "UPDATE trades SET stop_loss_price = ? WHERE id = ?",
                                    (sl, trade["id"]),
                                )
                            logger.info(
                                f"MOMENTUM TIGHTEN {ticker}: SL moved to ${sl} — {momentum['reason']}"
                            )
                    else:
                        tightened = round(current + (sl - current) * 0.5, 2)
                        if tightened < sl:
                            sl = tightened
                            with self.db._get_conn() as conn:
                                conn.execute(
                                    "UPDATE trades SET stop_loss_price = ? WHERE id = ?",
                                    (sl, trade["id"]),
                                )
                            logger.info(
                                f"MOMENTUM TIGHTEN {ticker}: SL moved to ${sl} — {momentum['reason']}"
                            )

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

                    notify_trade_exited(ticker, reason, partial_pnl, partial=True)
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
                    notify_trade_exited(ticker, reason, pnl)
                    logger.info(
                        f"EXIT — {ticker}: {reason} | P&L: ${pnl:.2f} | X-Request-ID: {req_id}"
                    )
                except Exception as e:
                    logger.error(f"Failed to close {ticker}: {e}")

        return exits
