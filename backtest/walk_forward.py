"""Walk-forward runner for the backtest engine.

Chunks a bar series into rolling (in-sample, out-of-sample) windows and
reports per-window metrics. The in-sample window is a placeholder for
future parameter tuning — today it just runs the same strategy on both
windows so OOS performance can be compared to IS.

Usage:
    python -m backtest.walk_forward NVDA --days 730 --is-days 60 --oos-days 20

Data source: Alpaca via the IBroker-shaped AlpacaBroker (IEX feed). For
tests we inject a bars-provider instead.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from analytics.slippage_model import SlippageFit, fit_slippage
from backtest.engine import BacktestResult, Engine, EngineConfig
from backtest.metrics import Metrics, compute_metrics, format_metrics
from backtest.strategies import BuyAndHoldStrategy, SMACrossoverStrategy
from backtest.strategy import Strategy
from brokers.base import Bar

BarsProvider = Callable[[str, datetime, datetime], list[Bar]]


@dataclass
class Window:
    start: datetime
    end: datetime
    is_end: datetime  # in-sample slice ends here; out-of-sample runs start..is_end..end
    result_is: BacktestResult
    result_oos: BacktestResult
    metrics_is: Metrics
    metrics_oos: Metrics


def build_windows(
    bars: list[Bar],
    is_days: int,
    oos_days: int,
) -> list[tuple[list[Bar], list[Bar]]]:
    """Split a bar series into overlapping (in-sample, out-of-sample) pairs.

    Walk-forward protocol: slide forward by `oos_days` each iteration.
    """
    if not bars or is_days <= 0 or oos_days <= 0:
        return []
    pairs: list[tuple[list[Bar], list[Bar]]] = []
    total = len(bars)
    step = oos_days
    start = 0
    while start + is_days + oos_days <= total:
        is_slice = bars[start:start + is_days]
        oos_slice = bars[start + is_days:start + is_days + oos_days]
        pairs.append((is_slice, oos_slice))
        start += step
    return pairs


def run_walk_forward(
    strategy_factory: Callable[[], Strategy],
    ticker: str,
    bars: list[Bar],
    is_days: int,
    oos_days: int,
    engine_config: EngineConfig | None = None,
    slippage: SlippageFit | None = None,
) -> list[Window]:
    windows: list[Window] = []
    for is_bars, oos_bars in build_windows(bars, is_days, oos_days):
        engine_is = Engine(strategy_factory(), ticker, engine_config, slippage)
        res_is = engine_is.run(is_bars)

        engine_oos = Engine(strategy_factory(), ticker, engine_config, slippage)
        res_oos = engine_oos.run(oos_bars)

        windows.append(Window(
            start=is_bars[0].timestamp,
            end=oos_bars[-1].timestamp,
            is_end=is_bars[-1].timestamp,
            result_is=res_is,
            result_oos=res_oos,
            metrics_is=compute_metrics(res_is),
            metrics_oos=compute_metrics(res_oos),
        ))
    return windows


# ─────────────────────────── CLI ──────────────────────────────────────────


STRATEGY_REGISTRY: dict[str, Callable[[], Strategy]] = {
    "buy_and_hold": BuyAndHoldStrategy,
    "sma_crossover": SMACrossoverStrategy,
}


def _alpaca_bars(ticker: str, start: datetime, end: datetime) -> list[Bar]:
    from brokers.alpaca import AlpacaBroker
    broker = AlpacaBroker()
    return broker.get_bars(ticker, start=start, end=end, timeframe="1Day")


def summarize_windows(windows: list[Window]) -> str:
    if not windows:
        return "No walk-forward windows produced — check date range vs IS/OOS lengths."
    lines = [
        f"{'window':<28}  {'IS Sharpe':>10}  {'OOS Sharpe':>11}  {'IS Ret%':>8}  {'OOS Ret%':>9}  {'OOS DD%':>8}",
        "-" * 82,
    ]
    for w in windows:
        label = f"{w.start.date()} → {w.end.date()}"
        lines.append(
            f"{label:<28}  {w.metrics_is.sharpe:>10.2f}  "
            f"{w.metrics_oos.sharpe:>11.2f}  "
            f"{w.metrics_is.total_return_pct:>+8.2f}  "
            f"{w.metrics_oos.total_return_pct:>+9.2f}  "
            f"{w.metrics_oos.max_drawdown_pct:>8.2f}"
        )
    # Aggregate OOS stats (what actually matters).
    total_oos_trades = sum(w.metrics_oos.num_trades for w in windows)
    avg_oos_sharpe = sum(w.metrics_oos.sharpe for w in windows) / len(windows)
    avg_oos_ret = sum(w.metrics_oos.total_return_pct for w in windows) / len(windows)
    lines.append("-" * 82)
    lines.append(
        f"{'aggregate OOS':<28}  {'':>10}  {avg_oos_sharpe:>11.2f}  "
        f"{'':>8}  {avg_oos_ret:>+9.2f}  {'':>8}   ({total_oos_trades} trades)"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Walk-forward backtest on one ticker.")
    parser.add_argument("ticker")
    parser.add_argument("--strategy", default="sma_crossover", choices=STRATEGY_REGISTRY.keys())
    parser.add_argument("--days", type=int, default=730, help="total history lookback in days")
    parser.add_argument("--is-days", type=int, default=60, help="in-sample window (trading days)")
    parser.add_argument("--oos-days", type=int, default=20, help="out-of-sample window (trading days)")
    parser.add_argument("--equity", type=float, default=100_000, help="starting equity")
    parser.add_argument("--risk-pct", type=float, default=0.02, help="risk per trade as fraction")
    parser.add_argument("--no-slippage", action="store_true", help="ignore DB-fitted slippage model")
    args = parser.parse_args()

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)
    bars = _alpaca_bars(args.ticker, start, end)
    if not bars:
        print(f"No bars returned for {args.ticker} over the last {args.days} days.")
        return 1

    slippage = None if args.no_slippage else fit_slippage()
    cfg = EngineConfig(
        starting_equity=args.equity,
        risk_pct_per_trade=args.risk_pct,
    )
    factory = STRATEGY_REGISTRY[args.strategy]

    print(f"\n{args.strategy} on {args.ticker} — {len(bars)} bars "
          f"({bars[0].timestamp.date()} → {bars[-1].timestamp.date()})\n")

    # Full-period sanity-check result before walk-forward.
    whole = Engine(factory(), args.ticker, cfg, slippage).run(bars)
    print("— Full-period run —")
    print(format_metrics(compute_metrics(whole)))

    print("\n— Walk-forward —")
    windows = run_walk_forward(factory, args.ticker, bars, args.is_days, args.oos_days, cfg, slippage)
    print(summarize_windows(windows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
