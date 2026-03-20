from __future__ import annotations

import logging
import math
from datetime import datetime

from config import Config
from utils.database import Database

logger = logging.getLogger(__name__)


class RiskManager:
    def __init__(self, db: Database | None = None):
        self.db = db or Database()
        self.config = Config()
        # In-memory cache for earnings dates (ticker -> (date_str, fetched_at))
        self._earnings_cache: dict[str, tuple[str | None, datetime]] = {}

    def _get_params(self, portfolio: str) -> dict:
        """Return risk parameters for the given portfolio."""
        if portfolio == "penny":
            return {
                "max_risk_per_trade": self.config.PENNY_MAX_RISK_PER_TRADE,
                "max_daily_loss": self.config.PENNY_MAX_DAILY_LOSS,
                "min_conviction": self.config.PENNY_MIN_CONVICTION,
                "min_reward_risk_ratio": self.config.PENNY_MIN_REWARD_RISK_RATIO,
                "max_position_pct": self.config.PENNY_MAX_POSITION_PCT,
                "max_open_positions": self.config.PENNY_MAX_OPEN_POSITIONS,
            }
        return {
            "max_risk_per_trade": self.config.MAX_RISK_PER_TRADE,
            "max_daily_loss": self.config.MAX_DAILY_LOSS,
            "min_conviction": self.config.MIN_CONVICTION,
            "min_reward_risk_ratio": self.config.MIN_REWARD_RISK_RATIO,
            "max_position_pct": self.config.MAX_POSITION_PCT,
            "max_open_positions": self.config.MAX_OPEN_POSITIONS,
        }

    # ── Phase 1a: Kelly-Based Position Sizing ─────────────────────

    def calculate_position_size(
        self, account_value: float, entry_price: float, stop_loss_pct: float,
        portfolio: str = "main",
    ) -> int:
        """Calculate shares using fractional Kelly when enough history exists,
        falling back to fixed-risk sizing (1% of equity).
        """
        if entry_price <= 0:
            return 0
        params = self._get_params(portfolio)

        # Try Kelly sizing if we have enough trade history
        stats = self.db.get_strategy_stats(portfolio)
        if stats["trade_count"] >= 20 and stats["payoff_ratio"] > 0:
            kelly_fraction = self._kelly_fraction(stats["win_rate"], stats["payoff_ratio"])
            risk_pct = kelly_fraction
            logger.info(
                f"Kelly sizing: f*={kelly_fraction:.4f} "
                f"(win_rate={stats['win_rate']:.2f}, payoff={stats['payoff_ratio']:.2f})"
            )
        else:
            risk_pct = self.config.RISK_PCT_PER_TRADE
            logger.info(f"Fixed-risk sizing: {risk_pct*100:.1f}% (insufficient history: {stats['trade_count']} trades)")

        risk_amount = account_value * risk_pct
        risk_per_share = entry_price * (stop_loss_pct / 100)
        if risk_per_share <= 0:
            return 0
        shares_by_risk = int(risk_amount / risk_per_share)

        # Cap position value (mode-driven)
        max_position_value = account_value * params["max_position_pct"]
        shares_by_value = int(max_position_value / entry_price)

        return max(0, min(shares_by_risk, shares_by_value))

    def _kelly_fraction(self, win_rate: float, payoff_ratio: float) -> float:
        """Fractional Kelly: f* = (p - q) / b × safety_multiplier.

        p = win rate, q = 1 - p, b = avg win / avg loss (payoff ratio).
        """
        p = win_rate
        q = 1 - p
        b = payoff_ratio
        if b <= 0:
            return self.config.RISK_PCT_PER_TRADE

        kelly = (p - q) / b
        # Apply safety multiplier (half-Kelly by default)
        safe_kelly = kelly * self.config.KELLY_SAFETY_MULTIPLIER
        # Clamp: never risk more than mode's max, never less than 0.5%
        return max(0.005, min(safe_kelly, self.config.MAX_RISK_PER_TRADE))

    # ── Phase 1b: Volatility Adjustment ───────────────────────────

    def check_volatility_adjustment(self, current_atr: float, median_atr: float) -> float:
        """If current ATR > VOLATILITY_ATR_MULTIPLIER × median ATR, cut risk in half.

        Returns a multiplier (1.0 = normal, 0.5 = high volatility).
        """
        if median_atr <= 0 or current_atr <= 0:
            return 1.0
        ratio = current_atr / median_atr
        if ratio > self.config.VOLATILITY_ATR_MULTIPLIER:
            logger.warning(
                f"High volatility detected: ATR ratio {ratio:.1f}x "
                f"(current={current_atr:.2f}, median={median_atr:.2f}) — cutting risk 50%"
            )
            return 0.5
        return 1.0

    # ── Phase 1c: Portfolio-Level Guards ───────────────────────────

    def check_drawdown_halt(self, account_value: float) -> bool:
        """Return True if drawdown from peak is within limits (OK to trade).

        Blocks new entries if drawdown > MAX_DRAWDOWN_HALT_PCT in last 30 days.
        """
        peak = self.db.get_peak_equity(days=30)
        if peak <= 0:
            return True  # No history yet, allow trading
        # Current drawdown = how much we've lost from peak
        # We approximate using today's realized P&L relative to peak
        today_pnl = self.db.get_today_pnl()
        cumulative = today_pnl["realized_pnl"]
        drawdown_from_peak = peak - max(cumulative, 0)
        if drawdown_from_peak <= 0:
            return True
        drawdown_pct = drawdown_from_peak / account_value
        if drawdown_pct > self.config.MAX_DRAWDOWN_HALT_PCT:
            logger.warning(
                f"DRAWDOWN HALT: {drawdown_pct*100:.1f}% drawdown from peak "
                f"exceeds {self.config.MAX_DRAWDOWN_HALT_PCT*100:.0f}% limit"
            )
            return False
        return True

    def check_risk_of_ruin(self, account_value: float, portfolio: str = "main") -> bool:
        """Return True if risk of ruin is acceptable (OK to trade).

        RoR ≈ e^(-2 × edge × capital / risk_per_trade). Block if > MAX_RISK_OF_RUIN_PCT.
        """
        stats = self.db.get_strategy_stats(portfolio)
        if stats["trade_count"] < 20:
            return True  # Not enough data, allow trading

        edge = stats["expectancy"]
        if edge <= 0:
            logger.warning(f"Negative expectancy (${edge:.2f}) — risk of ruin is high")
            return False

        risk_per_trade = account_value * self.config.RISK_PCT_PER_TRADE
        if risk_per_trade <= 0:
            return True

        exponent = -2 * edge * account_value / (risk_per_trade * risk_per_trade)
        # Clamp exponent to avoid overflow
        exponent = max(exponent, -500)
        ror = math.exp(exponent)

        if ror > self.config.MAX_RISK_OF_RUIN_PCT:
            logger.warning(
                f"RISK OF RUIN too high: {ror*100:.2f}% > {self.config.MAX_RISK_OF_RUIN_PCT*100:.0f}% limit"
            )
            return False
        return True

    # ── Phase 1d: Pre-Trade Liquidity Check ───────────────────────

    def check_liquidity(self, proposed_shares: int, avg_daily_volume: int) -> bool:
        """Return True if proposed shares < ADV / MIN_ADV_RATIO.

        Prevents outsized orders in illiquid names.
        """
        if avg_daily_volume <= 0:
            logger.warning("No volume data — blocking trade for liquidity safety")
            return False
        max_shares = avg_daily_volume // self.config.MIN_ADV_RATIO
        if proposed_shares > max_shares:
            logger.warning(
                f"LIQUIDITY CHECK FAILED: {proposed_shares} shares > ADV/{self.config.MIN_ADV_RATIO} "
                f"({max_shares} shares, ADV={avg_daily_volume:,})"
            )
            return False
        return True

    # ── Phase 5a: Market Circuit Breaker ──────────────────────────

    def check_market_health(self, spy_intraday_change_pct: float, action: str = "BUY") -> bool:
        """Return True if market conditions allow the trade.

        Blocks new LONG entries if SPY drops > CIRCUIT_BREAKER_SPY_DROP_PCT intraday.
        """
        if action != "BUY":
            return True  # Only block longs
        if spy_intraday_change_pct < self.config.CIRCUIT_BREAKER_SPY_DROP_PCT:
            logger.warning(
                f"CIRCUIT BREAKER: SPY down {spy_intraday_change_pct:.2f}% "
                f"(threshold: {self.config.CIRCUIT_BREAKER_SPY_DROP_PCT}%) — blocking LONG entries"
            )
            return False
        return True

    # ── Phase 5b: Earnings Awareness ─────────────────────────────

    def check_earnings_proximity(self, ticker: str) -> dict:
        """Check if ticker has earnings within EARNINGS_EXIT_DAYS trading days.

        Returns {"near_earnings": bool, "days_until": int|None, "action": str}.
        """
        import yfinance as yf

        # Check cache (24h TTL)
        cached = self._earnings_cache.get(ticker)
        if cached:
            cached_date, fetched_at = cached
            if (datetime.now() - fetched_at).total_seconds() < 86400:
                if cached_date:
                    try:
                        earn_dt = datetime.strptime(cached_date[:10], "%Y-%m-%d")
                        days = (earn_dt - datetime.now()).days
                        near = 0 <= days <= self.config.EARNINGS_EXIT_DAYS
                        return {"near_earnings": near, "days_until": days, "action": self.config.EARNINGS_EXIT_MODE if near else "none"}
                    except Exception:
                        pass
                return {"near_earnings": False, "days_until": None, "action": "none"}

        # Fetch from yfinance
        try:
            stock = yf.Ticker(ticker)
            cal = stock.calendar
            earn_date = None
            if cal is not None:
                if isinstance(cal, dict):
                    ed = cal.get("Earnings Date")
                    if ed:
                        earn_date = str(ed[0]) if isinstance(ed, list) and ed else str(ed)
                elif hasattr(cal, "iloc") and len(cal) > 0:
                    earn_date = str(cal.iloc[0])

            self._earnings_cache[ticker] = (earn_date, datetime.now())

            if earn_date:
                earn_dt = datetime.strptime(earn_date[:10], "%Y-%m-%d")
                days = (earn_dt - datetime.now()).days
                near = 0 <= days <= self.config.EARNINGS_EXIT_DAYS
                return {
                    "near_earnings": near,
                    "days_until": days,
                    "action": self.config.EARNINGS_EXIT_MODE if near else "none",
                }
        except Exception as e:
            logger.debug(f"Earnings check failed for {ticker}: {e}")

        return {"near_earnings": False, "days_until": None, "action": "none"}

    # ── Original methods (preserved) ──────────────────────────────

    def check_daily_loss_limit(self, account_value: float) -> bool:
        """Return True if we're still within daily loss limit."""
        today_pnl = self.db.get_today_pnl()
        max_daily_loss = account_value * self.config.MAX_DAILY_LOSS
        return today_pnl["realized_pnl"] > -max_daily_loss

    def check_open_position_count(self, portfolio: str = "main") -> bool:
        """Return True if we can open another position."""
        params = self._get_params(portfolio)
        open_trades = self.db.get_open_trades(portfolio=portfolio)
        return len(open_trades) < params["max_open_positions"]

    def check_duplicate_position(self, ticker: str) -> bool:
        """Return True if we DON'T already have an open position in this ticker."""
        open_trades = self.db.get_open_trades()
        return not any(t["ticker"] == ticker for t in open_trades)

    def is_market_hours(self) -> bool:
        """Check if US market is currently open (basic check, ET timezone)."""
        now = datetime.now()
        if now.weekday() > 4:
            return False
        market_minutes = now.hour * 60 + now.minute
        return 9 * 60 + 30 <= market_minutes < 16 * 60

    def validate_trade(
        self,
        ticker: str,
        conviction: float,
        stop_loss_pct: float,
        take_profit_pct: float,
        account_value: float,
        portfolio: str = "main",
        action: str = "BUY",
        proposed_shares: int = 0,
        avg_daily_volume: int = 0,
        spy_change_pct: float = 0.0,
        edges_firing: int = 3,
    ) -> dict:
        """Run all pre-trade safety checks including new risk gates. Returns pass/fail with reasons."""
        params = self._get_params(portfolio)
        checks = {
            "conviction_met": conviction >= params["min_conviction"],
            "risk_within_limit": stop_loss_pct <= (params["max_risk_per_trade"] * 100 * 5),
            "reward_risk_ok": (
                take_profit_pct / stop_loss_pct >= params["min_reward_risk_ratio"] - 0.01
                if stop_loss_pct > 0
                else False
            ),
            "daily_loss_ok": self.check_daily_loss_limit(account_value),
            "position_count_ok": self.check_open_position_count(portfolio=portfolio),
            "no_duplicate": self.check_duplicate_position(ticker),
            "market_open": self.is_market_hours(),
            # Phase 1c: Portfolio-level guards
            "drawdown_ok": self.check_drawdown_halt(account_value),
            "risk_of_ruin_ok": self.check_risk_of_ruin(account_value, portfolio),
            # Phase 1d: Liquidity
            "liquidity_ok": self.check_liquidity(proposed_shares, avg_daily_volume) if avg_daily_volume > 0 else True,
            # Phase 3: Edge validation
            "edges_ok": edges_firing >= self.config.MIN_EDGES_REQUIRED,
            # Phase 5a: Market circuit breaker
            "market_health_ok": self.check_market_health(spy_change_pct, action),
            # Phase 5b: Earnings awareness
            "earnings_ok": not self.check_earnings_proximity(ticker)["near_earnings"],
        }

        all_passed = all(checks.values())
        failures = [k for k, v in checks.items() if not v]

        return {
            "approved": all_passed,
            "checks": checks,
            "failures": failures,
            "message": "TRADE APPROVED" if all_passed else f"TRADE BLOCKED: {', '.join(failures)}",
        }

    def is_revenge_trading(self, portfolio: str = "main") -> bool:
        """Check if recent losses suggest emotional/revenge trading."""
        recent = self.db.get_recent_trades(limit=5, portfolio=portfolio)
        if len(recent) < 3:
            return False
        last_3 = recent[:3]
        losses = sum(1 for t in last_3 if (t.get("pnl") or 0) < 0)
        return losses >= 3
