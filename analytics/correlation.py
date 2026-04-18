"""Correlation-aware position sizing.

The sector concentration check (25% per sector) is too coarse — "Technology"
covers NVDA, CRM, and MSFT, which behave nothing alike. This module computes
actual daily-return correlation between a candidate ticker and currently-held
positions and returns a size multiplier.

Model:
- Fetch last 60 daily bars for each held ticker + the candidate
- Compute pairwise Pearson correlation of log returns
- Take the average correlation with held positions
- Map: avg_corr > 0.6 → 0.5x size, 0.6 ≥ avg_corr > 0.4 → 0.75x, else 1.0x

If a ticker has insufficient history (new listing, data gap), it's treated
as uncorrelated — we never block a trade solely because we couldn't measure
correlation.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone

from brokers.base import IBroker

logger = logging.getLogger(__name__)

LOOKBACK_DAYS = 60
HIGH_CORR_THRESHOLD = 0.6
MODERATE_CORR_THRESHOLD = 0.4
HIGH_CORR_MULTIPLIER = 0.5
MODERATE_CORR_MULTIPLIER = 0.75


def _log_returns(closes: list[float]) -> list[float]:
    return [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i - 1] > 0 and closes[i] > 0
    ]


def _pearson(a: list[float], b: list[float]) -> float | None:
    """Pearson correlation coefficient. Returns None when undefined (zero
    variance in either series, or fewer than 5 joint observations)."""
    n = min(len(a), len(b))
    if n < 5:
        return None
    a_trim, b_trim = a[-n:], b[-n:]
    mean_a = sum(a_trim) / n
    mean_b = sum(b_trim) / n
    num = sum((a_trim[i] - mean_a) * (b_trim[i] - mean_b) for i in range(n))
    var_a = sum((x - mean_a) ** 2 for x in a_trim)
    var_b = sum((x - mean_b) ** 2 for x in b_trim)
    if var_a <= 0 or var_b <= 0:
        return None
    return num / math.sqrt(var_a * var_b)


def average_correlation(
    broker: IBroker,
    candidate: str,
    held_tickers: list[str],
    lookback_days: int = LOOKBACK_DAYS,
) -> float | None:
    """Average correlation of `candidate` log returns with each held position.

    Returns None if we can't compute any pairwise correlation (held list is
    empty, or data is missing for everyone).
    """
    if not held_tickers:
        return None

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days + 20)  # pad for non-trading days

    try:
        cand_bars = broker.get_bars(candidate, start=start, end=end, timeframe="1Day")
    except Exception as e:
        logger.warning(f"Correlation: candidate {candidate} bars fetch failed ({e})")
        return None
    cand_returns = _log_returns([b.close for b in cand_bars])
    if len(cand_returns) < 5:
        return None

    correlations: list[float] = []
    for held in held_tickers:
        if held == candidate:
            continue
        try:
            held_bars = broker.get_bars(held, start=start, end=end, timeframe="1Day")
        except Exception:
            continue
        held_returns = _log_returns([b.close for b in held_bars])
        corr = _pearson(cand_returns, held_returns)
        if corr is not None:
            correlations.append(corr)

    if not correlations:
        return None
    return sum(correlations) / len(correlations)


def correlation_size_multiplier(avg_corr: float | None) -> float:
    """Map average correlation to a sizing multiplier in [0.5, 1.0]."""
    if avg_corr is None:
        return 1.0
    if avg_corr > HIGH_CORR_THRESHOLD:
        return HIGH_CORR_MULTIPLIER
    if avg_corr > MODERATE_CORR_THRESHOLD:
        return MODERATE_CORR_MULTIPLIER
    return 1.0
