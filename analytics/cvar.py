"""Historical-simulation CVaR for portfolio tail-risk checks.

Conditional Value at Risk (CVaR) at α% = expected loss on the α% worst days.
At α = 5%, CVaR is "on the worst 5% of days, what's the average loss?" —
captures tail risk better than Value-at-Risk alone (which only tells you the
threshold, not how bad it gets beyond it).

We use historical simulation rather than parametric VaR: no normality
assumption, just replay the last N daily portfolio returns and take the
worst tail. Simple, defensible, and doesn't require fitting a distribution.

Use case: reject a candidate BUY if adding it pushes portfolio 5%-CVaR
past a configurable threshold (default 5% daily loss).
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

from brokers.base import IBroker

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 60
DEFAULT_ALPHA = 0.05  # 5% worst days
DEFAULT_CVAR_LIMIT = 0.05  # 5% expected loss on the worst 5% of days


def _log_returns(closes: list[float]) -> list[float]:
    return [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i - 1] > 0 and closes[i] > 0
    ]


def portfolio_cvar(
    broker: IBroker,
    holdings: dict[str, float],
    alpha: float = DEFAULT_ALPHA,
    lookback_days: int = LOOKBACK_DAYS,
) -> float | None:
    """Compute historical-simulation CVaR of the given portfolio.

    `holdings` maps ticker → market value (dollars). Weights are normalized
    internally. Returns the expected-loss magnitude as a positive number
    (e.g. 0.04 means "on the worst 5% of days the portfolio averages -4%"),
    or None if not enough data to compute.
    """
    if not holdings:
        return 0.0
    total = sum(abs(v) for v in holdings.values())
    if total <= 0:
        return 0.0
    weights = {t: v / total for t, v in holdings.items()}

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days + 20)

    per_ticker_returns: dict[str, list[float]] = {}
    for ticker in holdings:
        try:
            bars = broker.get_bars(ticker, start=start, end=end, timeframe="1Day")
        except Exception as e:
            logger.warning(f"CVaR: bar fetch failed for {ticker} ({e})")
            continue
        rs = _log_returns([b.close for b in bars])
        if len(rs) >= 5:
            per_ticker_returns[ticker] = rs

    if not per_ticker_returns:
        return None

    # Align lengths — take the shortest series as the common window.
    min_len = min(len(rs) for rs in per_ticker_returns.values())
    if min_len < 10:
        return None

    # Build portfolio return series as the weighted sum of per-ticker returns
    # over the aligned window.
    port_returns: list[float] = []
    for i in range(min_len):
        offset_i = i  # newest at the end; counting from 0 is fine — we only need the sample
        ret = 0.0
        w_sum = 0.0
        for ticker, rs in per_ticker_returns.items():
            w = weights.get(ticker, 0.0)
            # Use the last min_len returns for alignment.
            aligned = rs[-min_len:]
            ret += w * aligned[offset_i]
            w_sum += w
        # If weights only cover part of the portfolio (some tickers lacked data),
        # scale up so the remaining weights sum to 1. Better than pretending
        # the missing names contribute zero return.
        if w_sum > 0:
            ret /= w_sum
        port_returns.append(ret)

    return _cvar_of_returns(port_returns, alpha=alpha)


def _cvar_of_returns(returns: list[float], alpha: float = DEFAULT_ALPHA) -> float:
    """Average loss on the worst `alpha` fraction of days. Returns positive."""
    if not returns:
        return 0.0
    sorted_returns = sorted(returns)  # losses at the front
    k = max(1, int(alpha * len(sorted_returns)))
    tail = sorted_returns[:k]
    avg_tail_return = sum(tail) / len(tail)
    return max(0.0, -avg_tail_return)  # flip sign so loss is positive


def candidate_would_breach_cvar(
    broker: IBroker,
    current_holdings: dict[str, float],
    candidate_ticker: str,
    candidate_value: float,
    cvar_limit: float = DEFAULT_CVAR_LIMIT,
    alpha: float = DEFAULT_ALPHA,
) -> tuple[bool, float | None]:
    """Would adding `candidate` push portfolio CVaR past the limit?

    Returns (breached, projected_cvar). If `projected_cvar` is None, we
    couldn't compute — caller should treat as "don't block" (same default
    philosophy as correlation check).
    """
    projected = dict(current_holdings)
    projected[candidate_ticker] = projected.get(candidate_ticker, 0.0) + candidate_value
    cvar = portfolio_cvar(broker, projected, alpha=alpha)
    if cvar is None:
        return False, None
    return cvar > cvar_limit, cvar
