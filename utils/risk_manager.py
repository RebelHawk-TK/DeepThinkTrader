from __future__ import annotations

from datetime import datetime

from config import Config
from utils.database import Database


class RiskManager:
    def __init__(self, db: Database | None = None):
        self.db = db or Database()
        self.config = Config()

    def calculate_position_size(
        self, account_value: float, entry_price: float, stop_loss_pct: float
    ) -> int:
        """Calculate number of shares based on max risk per trade.

        Also caps position value at MAX_POSITION_PCT of account to prevent margin usage.
        """
        if entry_price <= 0:
            return 0
        risk_amount = account_value * self.config.MAX_RISK_PER_TRADE
        risk_per_share = entry_price * (stop_loss_pct / 100)
        if risk_per_share <= 0:
            return 0
        shares_by_risk = int(risk_amount / risk_per_share)

        # Cap position value (mode-driven)
        max_position_value = account_value * self.config.MAX_POSITION_PCT
        shares_by_value = int(max_position_value / entry_price)

        return max(0, min(shares_by_risk, shares_by_value))

    def check_daily_loss_limit(self, account_value: float) -> bool:
        """Return True if we're still within daily loss limit."""
        today_pnl = self.db.get_today_pnl()
        max_daily_loss = account_value * self.config.MAX_DAILY_LOSS
        return today_pnl["realized_pnl"] > -max_daily_loss

    def check_open_position_count(self) -> bool:
        """Return True if we can open another position."""
        open_trades = self.db.get_open_trades()
        return len(open_trades) < self.config.MAX_OPEN_POSITIONS

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
    ) -> dict:
        """Run all pre-trade safety checks. Returns pass/fail with reasons."""
        checks = {
            "conviction_met": conviction >= self.config.MIN_CONVICTION,
            "risk_within_limit": stop_loss_pct <= (self.config.MAX_RISK_PER_TRADE * 100 * 5),
            "reward_risk_ok": (
                take_profit_pct / stop_loss_pct >= self.config.MIN_REWARD_RISK_RATIO - 0.01
                if stop_loss_pct > 0
                else False
            ),
            "daily_loss_ok": self.check_daily_loss_limit(account_value),
            "position_count_ok": self.check_open_position_count(),
            "no_duplicate": self.check_duplicate_position(ticker),
            "market_open": self.is_market_hours(),
        }

        all_passed = all(checks.values())
        failures = [k for k, v in checks.items() if not v]

        return {
            "approved": all_passed,
            "checks": checks,
            "failures": failures,
            "message": "TRADE APPROVED" if all_passed else f"TRADE BLOCKED: {', '.join(failures)}",
        }

    def is_revenge_trading(self) -> bool:
        """Check if recent losses suggest emotional/revenge trading."""
        recent = self.db.get_recent_trades(limit=5)
        if len(recent) < 3:
            return False
        last_3 = recent[:3]
        losses = sum(1 for t in last_3 if (t.get("pnl") or 0) < 0)
        return losses >= 3
