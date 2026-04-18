"""Backtest result metrics — Sharpe, Sortino, max drawdown, Calmar.

Pure math on equity curves. Assumes 252 trading days/year. No dependency on
QuantStats (it's optional — see report_tear_sheet); these core metrics should
always be computable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from backtest.engine import BacktestResult

TRADING_DAYS_PER_YEAR = 252


@dataclass
class Metrics:
    total_return_pct: float
    cagr_pct: float
    sharpe: float
    sortino: float
    max_drawdown_pct: float
    calmar: float
    win_rate: float
    num_trades: int
    avg_pnl_per_trade: float


def compute_metrics(result: BacktestResult) -> Metrics:
    curve = [eq for _, eq in result.equity_curve]
    if len(curve) < 2 or curve[0] <= 0:
        return Metrics(0, 0, 0, 0, 0, 0, 0, 0, 0)

    # Daily-ish simple returns. We assume one bar = one trading day; if it's
    # intraday, callers should aggregate upstream.
    returns = [
        (curve[i] - curve[i - 1]) / curve[i - 1]
        for i in range(1, len(curve))
        if curve[i - 1] > 0
    ]
    total_return_pct = (curve[-1] - curve[0]) / curve[0] * 100
    years = len(curve) / TRADING_DAYS_PER_YEAR
    cagr_pct = ((curve[-1] / curve[0]) ** (1 / years) - 1) * 100 if years > 0 else 0.0

    sharpe = _sharpe(returns)
    sortino = _sortino(returns)
    max_dd_pct = _max_drawdown_pct(curve)
    calmar = cagr_pct / max_dd_pct if max_dd_pct > 0 else 0.0

    closed = [t for t in result.trades if t.exit_time is not None]
    win_rate = sum(1 for t in closed if t.pnl > 0) / len(closed) if closed else 0.0
    avg_pnl = sum(t.pnl for t in closed) / len(closed) if closed else 0.0

    return Metrics(
        total_return_pct=total_return_pct,
        cagr_pct=cagr_pct,
        sharpe=sharpe,
        sortino=sortino,
        max_drawdown_pct=max_dd_pct,
        calmar=calmar,
        win_rate=win_rate,
        num_trades=len(closed),
        avg_pnl_per_trade=avg_pnl,
    )


def _sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _sortino(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean = sum(returns) / len(returns)
    downside = [r for r in returns if r < 0]
    if not downside:
        return 0.0
    var = sum(r ** 2 for r in downside) / len(downside)
    std = math.sqrt(var)
    if std == 0:
        return 0.0
    return (mean / std) * math.sqrt(TRADING_DAYS_PER_YEAR)


def _max_drawdown_pct(curve: list[float]) -> float:
    peak = curve[0]
    max_dd = 0.0
    for v in curve:
        if v > peak:
            peak = v
        if peak > 0:
            dd = (peak - v) / peak * 100
            if dd > max_dd:
                max_dd = dd
    return max_dd


def format_metrics(m: Metrics) -> str:
    return (
        f"Total return:   {m.total_return_pct:+.2f}%\n"
        f"CAGR:           {m.cagr_pct:+.2f}%\n"
        f"Sharpe:         {m.sharpe:.2f}\n"
        f"Sortino:        {m.sortino:.2f}\n"
        f"Max drawdown:   {m.max_drawdown_pct:.2f}%\n"
        f"Calmar:         {m.calmar:.2f}\n"
        f"Num trades:     {m.num_trades}\n"
        f"Win rate:       {m.win_rate * 100:.1f}%\n"
        f"Avg P&L/trade:  ${m.avg_pnl_per_trade:+.2f}"
    )
