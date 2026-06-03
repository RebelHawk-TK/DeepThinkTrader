"""Full validation of the quality_momentum lead (MAIN book).

quality_momentum (above-SMA20 + revenue_growth>0 + profit_margin>0 + up-day) showed
PF 1.58 in signal_search. Before believing it, three rigor checks:

  1. EXECUTION / look-ahead — re-run with NEXT-BAR-OPEN entry (the open of the first
     hourly bar STRICTLY after the report timestamp) instead of the report's
     current_price. If PF collapses, the "edge" was intrabar look-ahead, not real.
     This is the most important test.
  2. WALK-FORWARD OOS — rolling IS->OOS windows; measure the fixed signal out-of-sample.
  3. COST + THRESHOLD sensitivity — PF vs cost; PF vs threshold variants (knife-edge?).

All on the bot's real scanned MAIN universe (research_reports, price>=$5), deduped to 1
position/ticker, net of cost. Read-only on trades.db.

Run: ~/.venvs/deepthinktrader/bin/python -m backtest.validate_quality_momentum
"""
from __future__ import annotations

from datetime import timedelta

from backtest.signal_search import load_candidates
from backtest.trade_replay import Entry, ExitPolicy, aggregate, fetch_hourly_bars, simulate_exit

POLICY = ExitPolicy("trail3.0", 2.0, 3.0)
COST = 0.3


def qm(margin=0.0, growth=0.0, up=True, also10=False):
    def f(c):
        if not c.above20:
            return False
        if also10 and not c.above10:
            return False
        if up and not (c.daily_chg > 0):
            return False
        return c.rev_growth > growth and c.margin > margin
    return f


def _stop_pct(price, atr):
    return max(2.0, min(10.0, atr * 2 / price * 100)) if (atr > 0 and price > 0) else 5.0


def sim(sig, cands, cost, nextbar):
    """Deduped net returns. nextbar=True enters at the OPEN of the first bar strictly
    after the report time (no intrabar look-ahead); else at the report current_price."""
    out, open_until = [], {}
    for c in cands:
        if not sig(c):
            continue
        if c.ticker in open_until and c.ts < open_until[c.ticker]:
            continue
        bars = fetch_hourly_bars(c.ticker, c.ts, c.ts + timedelta(days=30))
        if nextbar:
            fwd = [b for b in bars if b.timestamp > c.ts]
            if not fwd or fwd[0].open <= 0:
                continue
            eb = fwd[0]
            px, sp = eb.open, _stop_pct(eb.open, c.atr)
            e = Entry(0, c.ticker, eb.timestamp, px, px * (1 - sp / 100), px * (1 + sp * 1.5 / 100), None, None, None)
            simbars = fwd
        else:
            px, sp = c.price, _stop_pct(c.price, c.atr)
            e = Entry(0, c.ticker, c.ts, px, px * (1 - sp / 100), px * (1 + sp * 1.5 / 100), None, None, None)
            simbars = bars
        res = simulate_exit(e, simbars, POLICY)
        if res is None:
            continue
        after = [b for b in simbars if b.timestamp >= e.entry_time]
        idx = min(res.bars_held, len(after)) - 1
        open_until[c.ticker] = after[idx].timestamp if idx >= 0 else e.entry_time
        out.append((c.ts, res.return_pct - cost))
    return out


def _pf(a):
    return "inf" if a.profit_factor == float("inf") else f"{a.profit_factor:.2f}"


def _line(label, rets):
    a = aggregate("x", rets)
    print(f"  {label:<34} n={a.n:>4} win%={a.win_pct:>5.1f} exp%={a.expectancy_pct:>+6.2f} PF={_pf(a)}")
    return a


def main() -> None:
    cands = [c for c in load_candidates() if c.price >= 5]
    base = qm()
    print(f"MAIN candidates: {len(cands)} | signal=quality_momentum | exit {POLICY.name} | cost {COST}%\n")

    print("---- 1. EXECUTION (look-ahead test): same-bar vs next-bar-open entry ----")
    _line("same-bar (orig, optimistic)", [r for _, r in sim(base, cands, COST, False)])
    _line("NEXT-BAR open (no look-ahead)", [r for _, r in sim(base, cands, COST, True)])

    print("\n---- 2. WALK-FORWARD OOS (next-bar, IS=28d / OOS=14d) ----")
    t0, t1 = cands[0].ts, cands[-1].ts
    start, oos_rets, w = t0, [], 0
    while start + timedelta(days=42) <= t1 + timedelta(days=1):
        oos_lo = start + timedelta(days=28)
        oos_hi = oos_lo + timedelta(days=14)
        is_c = [c for c in cands if start <= c.ts < oos_lo]
        oos_c = [c for c in cands if oos_lo <= c.ts < oos_hi]
        w += 1
        ia = aggregate("is", [r for _, r in sim(base, is_c, COST, True)])
        oa_tr = sim(base, oos_c, COST, True)
        oa = aggregate("oos", [r for _, r in oa_tr])
        oos_rets += [r for _, r in oa_tr]
        print(f"  win{w} {start.date()}->{oos_hi.date()}: IS PF={_pf(ia)}(n{ia.n}) | "
              f"OOS PF={_pf(oa)}(n{oa.n}) exp={oa.expectancy_pct:+.2f}%")
        start += timedelta(days=14)
    agg = aggregate("oos", oos_rets)
    print(f"  AGGREGATE OOS: n={agg.n} win%={agg.win_pct:.1f} exp%={agg.expectancy_pct:+.2f} PF={_pf(agg)}")

    print("\n---- 3. COST sensitivity (next-bar, full history) ----")
    for c_ in (0.0, 0.3, 0.5, 1.0):
        _line(f"cost {c_:.1f}%", [r for _, r in sim(base, cands, c_, True)])

    print("\n---- 4. THRESHOLD sensitivity (next-bar, cost 0.3%) ----")
    variants = {
        "base (margin>0,growth>0,up)": qm(),
        "margin>0.05": qm(margin=0.05),
        "growth>0.05": qm(growth=0.05),
        "no up-day requirement": qm(up=False),
        "+require above SMA10": qm(also10=True),
        "margin>0 only (drop growth)": lambda c: c.above20 and c.daily_chg > 0 and c.margin > 0,
        "growth>0 only (drop margin)": lambda c: c.above20 and c.daily_chg > 0 and c.rev_growth > 0,
    }
    for name, sig in variants.items():
        _line(name, [r for _, r in sim(sig, cands, COST, True)])

    print("\nVerdict: REAL edge only if next-bar PF stays >~1.1 (test 1), aggregate OOS PF")
    print(">~1.1 with decent n (test 2), survives ~0.5-1% cost (test 3), and isn't a")
    print("knife-edge across thresholds (test 4). Same-bar >> next-bar = look-ahead artifact.")


if __name__ == "__main__":
    main()
