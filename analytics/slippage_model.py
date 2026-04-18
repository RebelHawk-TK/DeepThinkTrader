"""Slippage model fit from historical fills in slippage_records.

The schema we have is (ticker, expected_price, filled_price, slippage_pct,
order_type, side, shares, hour_of_day) — no spread, no ADV. Given that, the
most honest model is:

    estimate_bps(ticker, side, shares) =
        ticker_mean_side_adj(ticker, side)  (if ≥ MIN_SAMPLES fills)
        else global_mean_side_adj(side)
        + size_inflation(shares, ticker_median_shares)

`size_inflation` is a small log-scaled bump for orders larger than the
ticker's historical median shares — a crude stand-in for market-impact
without ADV data. When ADV becomes available (Sprint 4+), swap for an
AQR-style sqrt-impact model.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Literal

from utils.database import Database

MIN_SAMPLES = 10  # need this many fills for a per-ticker estimate
RECENCY_DAYS = 90  # only fit on the last 90 days of fills


@dataclass
class SlippageFit:
    """A fitted slippage model — callable via estimate_bps()."""
    global_buy_bps: float
    global_sell_bps: float
    ticker_stats: dict[str, dict]  # ticker → {buy_bps, sell_bps, median_shares, n}

    def estimate_bps(self, ticker: str, side: Literal["buy", "sell"], shares: int) -> float:
        """Return estimated cost in basis points (always positive)."""
        stats = self.ticker_stats.get(ticker)
        if stats and stats["n"] >= MIN_SAMPLES:
            base = stats[f"{side}_bps"]
            median_shares = stats["median_shares"] or max(shares, 1)
        else:
            base = self.global_buy_bps if side == "buy" else self.global_sell_bps
            median_shares = None

        base = abs(base)
        if median_shares and shares > median_shares:
            # +2 bps per doubling of order size above the ticker's historical median
            doublings = math.log2(max(shares / median_shares, 1.0))
            base += 2.0 * doublings
        return max(base, 0.0)


def fit_slippage(db: Database | None = None, recency_days: int = RECENCY_DAYS) -> SlippageFit:
    """Fit a SlippageFit from the DB's `slippage_records` table."""
    db = db or Database()
    cutoff = (datetime.now() - timedelta(days=recency_days)).isoformat()

    with db._get_conn() as conn:
        rows = conn.execute(
            """SELECT ticker, side, shares, slippage_pct
               FROM slippage_records
               WHERE timestamp >= ?""",
            (cutoff,),
        ).fetchall()

    # Group by ticker + side. slippage_pct is signed; we care about cost, so
    # flip sign for sells (a sell filled below expected is a cost).
    by_ticker: dict[str, dict[str, list]] = {}
    global_buy: list[float] = []
    global_sell: list[float] = []

    for r in rows:
        ticker = r["ticker"]
        side = r["side"].lower() if r["side"] else ""
        shares = int(r["shares"] or 0)
        slippage_pct = r["slippage_pct"] or 0.0
        # Convert pct → bps and make side-adjusted cost always positive.
        # Buy cost = filled > expected → slippage_pct > 0 → cost bps
        # Sell cost = filled < expected → slippage_pct < 0 → flip sign
        cost_bps = slippage_pct * 100 if side == "buy" else -slippage_pct * 100

        by_ticker.setdefault(ticker, {"buy": [], "sell": [], "shares": []})
        by_ticker[ticker][side].append(cost_bps)
        by_ticker[ticker]["shares"].append(shares)
        if side == "buy":
            global_buy.append(cost_bps)
        elif side == "sell":
            global_sell.append(cost_bps)

    ticker_stats = {}
    for ticker, data in by_ticker.items():
        buys = data["buy"]
        sells = data["sell"]
        ticker_stats[ticker] = {
            "buy_bps": sum(buys) / len(buys) if buys else 0.0,
            "sell_bps": sum(sells) / len(sells) if sells else 0.0,
            "median_shares": median(data["shares"]) if data["shares"] else 0,
            "n": len(buys) + len(sells),
        }

    global_buy_bps = sum(global_buy) / len(global_buy) if global_buy else 5.0
    global_sell_bps = sum(global_sell) / len(global_sell) if global_sell else 5.0

    return SlippageFit(
        global_buy_bps=global_buy_bps,
        global_sell_bps=global_sell_bps,
        ticker_stats=ticker_stats,
    )
