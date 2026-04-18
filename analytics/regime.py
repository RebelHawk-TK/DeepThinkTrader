"""Market regime classifier.

Uses SPY's 20-day annualized realized volatility to bucket the market into
LOW / NORMAL / HIGH regimes and recommend a trade mode. This isn't clever —
it's a stand-in for "don't be aggressive when VIX is 35" that works even
when VIX data is stale.

Regimes (calibrated against historical SPY data):
- LOW:    annualized vol <  10%  → aggressive mode allowed
- NORMAL: 10-20%                 → normal mode
- HIGH:   > 20%                  → safe mode (conservative sizing)

Call `classify_regime(broker)` once per cycle. Keep the result in memory;
don't rewrite `.env` on regime changes (the bot should adapt silently).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from brokers.base import IBroker

logger = logging.getLogger(__name__)

RegimeLabel = Literal["low", "normal", "high", "unknown"]
TradeMode = Literal["aggressive", "normal", "safe"]

# Thresholds in annualized volatility (i.e. σ × √252).
LOW_VOL_THRESHOLD = 0.10
HIGH_VOL_THRESHOLD = 0.20

TRADING_DAYS = 252


@dataclass(frozen=True)
class RegimeAssessment:
    label: RegimeLabel
    annualized_vol: float  # 0.0 = 0%, 0.15 = 15%
    recommended_mode: TradeMode
    n_bars: int

    def describe(self) -> str:
        return (
            f"regime={self.label} vol={self.annualized_vol * 100:.1f}% "
            f"→ recommend {self.recommended_mode} mode (from {self.n_bars} bars)"
        )


def classify_regime(broker: IBroker, lookback_days: int = 30) -> RegimeAssessment:
    """Compute realized vol of SPY daily returns and map to a regime.

    Fails gracefully to `unknown` / `normal` if data is missing — we never
    want a regime-classifier outage to block trading entirely.
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=lookback_days + 10)  # pad for non-trading days
    try:
        bars = broker.get_bars("SPY", start=start, end=end, timeframe="1Day")
    except Exception as e:
        logger.warning(f"Regime classifier: bar fetch failed ({e}); defaulting to normal")
        return RegimeAssessment("unknown", 0.0, "normal", 0)

    closes = [b.close for b in bars]
    if len(closes) < 10:
        logger.info(f"Regime classifier: only {len(closes)} bars, defaulting to normal")
        return RegimeAssessment("unknown", 0.0, "normal", len(closes))

    # Log returns — more stable for vol calc than arithmetic on small moves.
    returns = [
        math.log(closes[i] / closes[i - 1])
        for i in range(1, len(closes))
        if closes[i - 1] > 0 and closes[i] > 0
    ]
    if len(returns) < 5:
        return RegimeAssessment("unknown", 0.0, "normal", len(returns))

    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    daily_vol = math.sqrt(var)
    annualized = daily_vol * math.sqrt(TRADING_DAYS)

    if annualized < LOW_VOL_THRESHOLD:
        label: RegimeLabel = "low"
        mode: TradeMode = "aggressive"
    elif annualized > HIGH_VOL_THRESHOLD:
        label = "high"
        mode = "safe"
    else:
        label = "normal"
        mode = "normal"

    return RegimeAssessment(label, annualized, mode, len(closes))
