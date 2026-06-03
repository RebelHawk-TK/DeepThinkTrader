"""Signal search — test genuinely NEW entry signals against history (Phase 2, path B).

walk_forward_entries re-thresholds the bot's RECORDED conviction, so it can only test
gate/threshold/exit changes — not a different decision rule. This re-scores from the raw
`research_reports` (which hold every input: momentum, RSI, volume, ATR, options flow,
catalyst/sentiment, fundamentals, regime), applies candidate SIGNAL functions to pick
entries, simulates them forward (ATR stop + per-book trailing, deduped to 1 position/ticker,
net of realistic cost), and reports net PF full-history + per time-third (consistency).

A signal with PF clearly >1, decent trade count, AND consistency across thirds (not one
lucky window — see penny_regime for why that matters) is a real lead worth deeper OOS work.
Most candidate signals are expected to FAIL the consistency check; that's the point — the
harness exists to reject them cheaply.

Scope: tests new decision rules on the bot's already-scanned universe (the scanner is a
separate component). Penny vs main split by entry price (<$5 = penny). Read-only on trades.db.

Run: ~/.venvs/deepthinktrader/bin/python -m backtest.signal_search
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import timedelta

from backtest.trade_replay import (
    DB_PATH,
    Entry,
    ExitPolicy,
    _parse_ts,
    aggregate,
    fetch_hourly_bars,
    simulate_exit,
)


@dataclass
class Cand:
    ticker: str
    ts: object
    price: float
    atr: float
    daily_chg: float
    vol_ratio: float
    rsi: float
    above10: bool
    above20: bool
    high30: float
    low30: float
    trend1h: str
    rsi1h: float
    news: float
    reddit: float
    catalyst: float
    sa_sent: float
    sa_bull: int
    sa_bear: int
    opt_bull: bool
    opt_strength: float
    pcr: float
    rev_growth: float
    d2e: float
    margin: float
    vix: float
    breadth: float


def _f(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def load_candidates() -> list[Cand]:
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    out: list[Cand] = []
    for ts, rj in con.execute(
        "SELECT timestamp, report_json FROM research_reports WHERE report_json IS NOT NULL ORDER BY timestamp"
    ):
        try:
            d = json.loads(rj)
        except Exception:
            continue
        t = d.get("technicals") or {}
        price = _f(t.get("current_price"))
        if price <= 0:
            continue
        adv = d.get("advanced_technicals") or {}
        atr = _f((adv.get("atr") or {}).get("atr"))
        intr = d.get("intraday") or {}
        fin = (d.get("fundamentals") or {}).get("financials") or {}
        sa = d.get("seeking_alpha") or {}
        opt = d.get("options_flow") or {}
        mr = d.get("market_regime") or {}
        out.append(Cand(
            ticker=d.get("ticker") or "", ts=_parse_ts(ts), price=price, atr=atr,
            daily_chg=_f(t.get("daily_change_pct")), vol_ratio=_f(t.get("volume_ratio")), rsi=_f(t.get("rsi_14")),
            above10=bool(t.get("above_sma_10")), above20=bool(t.get("above_sma_20")),
            high30=_f(t.get("high_30d")), low30=_f(t.get("low_30d")),
            trend1h=(intr.get("trend") or "neutral"), rsi1h=_f(intr.get("rsi_1h")),
            news=_f(d.get("news_impact_score")), reddit=_f(d.get("reddit_sentiment_score")),
            catalyst=_f(d.get("combined_catalyst_score")),
            sa_sent=_f(sa.get("avg_sentiment")), sa_bull=int(_f(sa.get("rss_bullish"))), sa_bear=int(_f(sa.get("rss_bearish"))),
            opt_bull=bool(opt.get("bullish_flow")), opt_strength=_f(opt.get("signal_strength")), pcr=_f(opt.get("put_call_ratio"), 1.0),
            rev_growth=_f(fin.get("revenue_growth")), d2e=_f(fin.get("debt_to_equity")), margin=_f(fin.get("profit_margin")),
            vix=_f(mr.get("vix")), breadth=_f(mr.get("breadth_ratio")),
        ))
    con.close()
    return out


# ── Candidate signals: pure functions of Cand (a long entry rule) ────────────
SIGNALS = {
    "momentum_breakout": lambda c: c.above10 and c.above20 and c.vol_ratio > 2 and c.daily_chg > 3 and c.rsi < 75,
    "relative_strength": lambda c: c.high30 > 0 and c.price >= 0.9 * c.high30 and c.vol_ratio > 1.5 and c.daily_chg > 0,
    "mean_reversion": lambda c: 0 < c.rsi < 35 and c.catalyst > 0 and c.above20,
    "options_flow": lambda c: c.opt_bull and c.opt_strength > 0.5,
    "catalyst_fresh": lambda c: c.catalyst > 0.5 and c.news > 2 and c.sa_sent > 0.1,
    "quality_momentum": lambda c: c.above20 and c.daily_chg > 0 and c.rev_growth > 0 and c.margin > 0,
    "SA_bull_skew": lambda c: c.sa_bull >= 3 and c.sa_bull > 2 * max(1, c.sa_bear) and c.above20,
    "1h_trend_align": lambda c: c.trend1h == "bullish" and c.above20 and c.catalyst > 0,
}


def _entry(c: Cand, rr: float = 1.5) -> Entry:
    stop_pct = max(2.0, min(10.0, c.atr * 2 / c.price * 100)) if (c.atr > 0 and c.price > 0) else 5.0
    return Entry(0, c.ticker, c.ts, c.price,
                 c.price * (1 - stop_pct / 100), c.price * (1 + stop_pct * rr / 100),
                 None, None, None)


def sim(sig, cands, policy, cost):
    out, open_until = [], {}
    for c in cands:
        if not sig(c):
            continue
        if c.ticker in open_until and c.ts < open_until[c.ticker]:
            continue
        bars = fetch_hourly_bars(c.ticker, c.ts, c.ts + timedelta(days=30))
        res = simulate_exit(_entry(c), bars, policy)
        if res is None:
            continue
        after = [b for b in bars if b.timestamp >= c.ts]
        idx = min(res.bars_held, len(after)) - 1
        open_until[c.ticker] = after[idx].timestamp if idx >= 0 else c.ts
        out.append((c.ts, res.return_pct - cost))
    return out


def _pf(a):
    return "inf" if a.profit_factor == float("inf") else f"{a.profit_factor:.2f}"


def main() -> None:
    cands = load_candidates()
    print(f"loaded {len(cands)} research-report candidates "
          f"({cands[0].ts.date()}..{cands[-1].ts.date()})")
    penny = [c for c in cands if c.price < 5]
    main_c = [c for c in cands if c.price >= 5]
    t0, t1 = cands[0].ts, cands[-1].ts
    span = t1 - t0
    edges = [t0, t0 + span / 3, t0 + 2 * span / 3, t1 + timedelta(seconds=1)]

    def third(ts):
        for j in range(3):
            if edges[j] <= ts < edges[j + 1]:
                return j
        return 2

    for book, cs, policy, cost in (
        ("PENNY (<$5)", penny, ExitPolicy("trail2.0", 2.0, 2.0), 2.5),
        ("MAIN (>=$5)", main_c, ExitPolicy("trail3.0", 2.0, 3.0), 0.3),
    ):
        print(f"\n===== {book}: {len(cs)} candidates | exit {policy.name} | cost {cost}% =====")
        print(f"  {'signal':<20}{'trades':>7}{'win%':>7}{'exp%':>8}{'PF':>7}   per-third PF [t1,t2,t3]")
        for name, sig in SIGNALS.items():
            tr = sim(sig, cs, policy, cost)
            a = aggregate(name, [r for _, r in tr])
            th = [[], [], []]
            for ts, r in tr:
                th[third(ts)].append(r)
            tp = [(_pf(aggregate("x", x)) if x else "--") for x in th]
            print(f"  {name:<20}{a.n:>7}{a.win_pct:>7.1f}{a.expectancy_pct:>+8.2f}{_pf(a):>7}   [{', '.join(tp)}]")

    print("\nLead = PF clearly >1, decent n, AND consistent across thirds. A signal good in")
    print("only one third is a lucky window, not an edge (cf. penny_regime). Prior is low.")


if __name__ == "__main__":
    main()
