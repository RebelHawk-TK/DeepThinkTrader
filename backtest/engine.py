"""Bar-replay backtest engine.

Single-ticker, long-only, one-position-at-a-time. Entries come from a
`Strategy.on_bar` signal; exits come from stop-loss, take-profit, or the
same trailing-stop logic used in production.

Design notes:
- Uses MockBroker as the sole source of order/position truth. No DB writes,
  no network calls.
- `trailing_stop_activation_pct` + `trailing_stop_distance_pct` mirror the
  production config so results correspond to what live execution would do.
- Slippage is a per-bar adjustment on the fill price, consumed from an
  optional SlippageFit.
- Returns a ResultSeries with bar-by-bar equity and a TradeLog. Metrics
  (Sharpe, Sortino, max DD) are computed elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from analytics.slippage_model import SlippageFit
from brokers.base import Bar
from brokers.mock import MockBroker
from backtest.strategy import Signal, Strategy


@dataclass
class Trade:
    ticker: str
    entry_time: datetime
    entry_price: float
    qty: int
    exit_time: datetime | None = None
    exit_price: float | None = None
    pnl: float = 0.0
    reason: str = ""
    stop_loss_price: float = 0.0
    take_profit_price: float = 0.0


@dataclass
class BacktestResult:
    strategy_name: str
    ticker: str
    starting_equity: float
    ending_equity: float
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)

    @property
    def total_return_pct(self) -> float:
        if self.starting_equity == 0:
            return 0.0
        return (self.ending_equity - self.starting_equity) / self.starting_equity * 100

    @property
    def num_trades(self) -> int:
        return len([t for t in self.trades if t.exit_time is not None])

    @property
    def win_rate(self) -> float:
        closed = [t for t in self.trades if t.exit_time is not None]
        if not closed:
            return 0.0
        return sum(1 for t in closed if t.pnl > 0) / len(closed)


@dataclass
class EngineConfig:
    starting_equity: float = 100_000.0
    risk_pct_per_trade: float = 0.02
    max_position_pct: float = 0.10
    trailing_stop_activation_pct: float = 2.0  # in %, mirrors prod
    trailing_stop_distance_pct: float = 1.5
    allow_short: bool = False


class Engine:
    def __init__(
        self,
        strategy: Strategy,
        ticker: str,
        config: EngineConfig | None = None,
        slippage: SlippageFit | None = None,
    ) -> None:
        self.strategy = strategy
        self.ticker = ticker
        self.config = config or EngineConfig()
        self.slippage = slippage
        self.broker = MockBroker(starting_cash=self.config.starting_equity)
        self.trades: list[Trade] = []
        self._active: Optional[Trade] = None
        self._highest_seen: float = 0.0
        self._trailing_active: bool = False
        self._trailing_stop: float = 0.0
        self._lookback: list[Bar] = []
        self._equity_curve: list[tuple[datetime, float]] = []

    # ── Core drive loop ──────────────────────────────────────────────────

    def run(self, bars: list[Bar]) -> BacktestResult:
        """Replay `bars` through the strategy."""
        for bar in bars:
            self.broker.ingest_bar(bar)
            self._lookback.append(bar)
            if self._active:
                self._update_exits(bar)
            if not self._active:
                self._consider_entry(bar)
            self._equity_curve.append((bar.timestamp, self.broker.get_account().equity))

        # Close any open position at the final bar so results are complete.
        if self._active and bars:
            self._close_trade(bars[-1], reason="backtest_end")

        final_equity = self.broker.get_account().equity
        return BacktestResult(
            strategy_name=self.strategy.name,
            ticker=self.ticker,
            starting_equity=self.config.starting_equity,
            ending_equity=final_equity,
            equity_curve=self._equity_curve,
            trades=self.trades,
        )

    # ── Entry logic ──────────────────────────────────────────────────────

    def _consider_entry(self, bar: Bar) -> None:
        signal: Signal = self.strategy.on_bar(
            bar=bar, lookback=self._lookback, account=self.broker.get_account()
        )
        if signal.action != "BUY":
            return
        account = self.broker.get_account()

        # Position sizing: risk-based with max-position-value cap.
        entry_px = self._apply_slippage(bar.close, "buy")
        risk_amount = account.equity * self.config.risk_pct_per_trade
        risk_per_share = entry_px * (signal.stop_loss_pct / 100)
        if risk_per_share <= 0:
            return
        shares_by_risk = int(risk_amount / risk_per_share)
        shares_by_value = int(account.equity * self.config.max_position_pct / entry_px)
        qty = max(0, min(shares_by_risk, shares_by_value))
        if qty == 0:
            return

        self.broker.submit_order(self.ticker, qty=qty, side="buy")
        stop_px = round(entry_px * (1 - signal.stop_loss_pct / 100), 4)
        tp_px = round(entry_px * (1 + signal.take_profit_pct / 100), 4)
        trade = Trade(
            ticker=self.ticker, entry_time=bar.timestamp, entry_price=entry_px,
            qty=qty, stop_loss_price=stop_px, take_profit_price=tp_px,
        )
        self.trades.append(trade)
        self._active = trade
        self._highest_seen = entry_px
        self._trailing_active = False
        self._trailing_stop = 0.0

    # ── Exit logic ───────────────────────────────────────────────────────

    def _update_exits(self, bar: Bar) -> None:
        assert self._active is not None
        trade = self._active
        cur = bar.close
        peak = max(bar.high, cur)
        if peak > self._highest_seen:
            self._highest_seen = peak

        profit_pct = (cur - trade.entry_price) / trade.entry_price * 100

        # Trailing stop activation — mirrors production (execution_agent.py:1078-1082).
        if (not self._trailing_active
                and profit_pct >= self.config.trailing_stop_activation_pct):
            self._trailing_active = True
            self._trailing_stop = round(
                self._highest_seen * (1 - self.config.trailing_stop_distance_pct / 100), 4
            )
        elif self._trailing_active:
            new_ts = round(
                self._highest_seen * (1 - self.config.trailing_stop_distance_pct / 100), 4
            )
            if new_ts > self._trailing_stop:
                self._trailing_stop = new_ts

        # Priority: stop-loss → trailing-stop → take-profit. Use bar's low/high
        # to detect intrabar touches, not just the close.
        if bar.low <= trade.stop_loss_price:
            self._close_trade(bar, reason="stop_loss", fill_at=trade.stop_loss_price)
            return
        if self._trailing_active and bar.low <= self._trailing_stop:
            self._close_trade(bar, reason="trailing_stop", fill_at=self._trailing_stop)
            return
        if bar.high >= trade.take_profit_price:
            self._close_trade(bar, reason="take_profit", fill_at=trade.take_profit_price)
            return

    def _close_trade(self, bar: Bar, reason: str, fill_at: float | None = None) -> None:
        assert self._active is not None
        trade = self._active
        exit_px = fill_at if fill_at is not None else bar.close
        exit_px = self._apply_slippage(exit_px, "sell")
        self.broker.submit_order(self.ticker, qty=trade.qty, side="sell")
        trade.exit_time = bar.timestamp
        trade.exit_price = exit_px
        trade.pnl = (exit_px - trade.entry_price) * trade.qty
        trade.reason = reason
        self._active = None
        self._highest_seen = 0.0
        self._trailing_active = False
        self._trailing_stop = 0.0

    # ── Helpers ──────────────────────────────────────────────────────────

    def _apply_slippage(self, price: float, side: str) -> float:
        if not self.slippage:
            return price
        bps = self.slippage.estimate_bps(self.ticker, side, 100)
        multiplier = 1 + (bps / 10_000) if side == "buy" else 1 - (bps / 10_000)
        return round(price * multiplier, 4)
