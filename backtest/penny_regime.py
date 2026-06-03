"""Penny regime-gating experiment (Phase 2 follow-up).

Hypothesis: penny only has an edge in favorable (risk-on / high-breadth) regimes.
The walk-forward showed penny made money in one window (+3.6% OOS) and lost in
flat ones. This:
  (A) DISCOVERY — buckets the deployed-penny independent trades (deduped, net of the
      2.5% cost) by the market regime recorded at entry (breadth, VIX level, VIX
      direction) to see what separates winners from losers; and
  (B) VALIDATION — applies candidate regime GATES as a pre-filter on the deployed
      penny config and re-measures net PF over the full history AND per time-third
      (consistency), vs the ungated baseline (net OOS PF ~0.81). A real conditional
      edge should lift PF clearly above 1.0 with decent trade count AND hold across
      thirds — not just rerun the one good window.

Regime is market-wide (market_regime.{breadth_ratio, vix, vix_change} in
research_reports); the nearest-prior reading applies to each decision. Caveat: the
bucketing/gate selection is in-sample, so the per-third consistency is the guard
against overfitting a single favorable window.

Run: ~/.venvs/deepthinktrader/bin/python -m backtest.penny_regime
Read-only on trades.db.
"""
from __future__ import annotations

import bisect
import json
import sqlite3
from datetime import timedelta

from backtest.trade_replay import DB_PATH, _parse_ts, aggregate, fetch_hourly_bars, simulate_exit
from backtest.walk_forward_entries import (
    _deployed,
    _entry_of,
    load_decisions,
    load_round_trip_cost,
    would_buy,
)


class Regime:
    """Market-wide regime time-series with nearest-prior lookup."""

    def __init__(self) -> None:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        rows = []
        for ts, rj in con.execute(
            "SELECT timestamp, report_json FROM research_reports WHERE report_json IS NOT NULL"
        ):
            try:
                mr = json.loads(rj).get("market_regime") or {}
            except Exception:
                continue
            v, b, c = mr.get("vix"), mr.get("breadth_ratio"), mr.get("vix_change")
            if v is None and b is None:
                continue
            rows.append((_parse_ts(ts), v, b, c))
        con.close()
        rows.sort(key=lambda x: x[0])
        self.t = [r[0] for r in rows]
        self.vix = [r[1] for r in rows]
        self.breadth = [r[2] for r in rows]
        self.vc = [r[3] for r in rows]

    def at(self, ts):
        i = bisect.bisect_right(self.t, ts) - 1
        if i < 0:
            i = 0
        return (self.vix[i], self.breadth[i], self.vc[i])   # (vix, breadth, vix_change)


def sim_trades(cfg, decisions, cost_pct):
    """Deduped forward trades; one (entry_ts, ticker, net_return_pct) per trade."""
    out, open_until = [], {}
    for d in decisions:
        if not would_buy(d, cfg):
            continue
        if d.ticker in open_until and d.ts < open_until[d.ticker]:
            continue
        bars = fetch_hourly_bars(d.ticker, d.ts, d.ts + timedelta(days=30))
        res = simulate_exit(_entry_of(d), bars, cfg.exit)
        if res is None:
            continue
        after = [b for b in bars if b.timestamp >= d.ts]
        idx = min(res.bars_held, len(after)) - 1
        open_until[d.ticker] = after[idx].timestamp if idx >= 0 else d.ts
        out.append((d.ts, d.ticker, res.return_pct - cost_pct))
    return out


def _pf(a):
    return "inf" if a.profit_factor == float("inf") else f"{a.profit_factor:.2f}"


def main() -> None:
    decisions = load_decisions("penny")
    cost, src = load_round_trip_cost("penny")
    deployed = _deployed("penny")
    reg = Regime()
    print(f"===== PENNY REGIME-GATING — {len(decisions)} decisions, cost {cost:.1f}% ({src}) =====")
    print(f"regime readings: {len(reg.t)}\n")

    trades = sim_trades(deployed, decisions, cost)
    tagged = [(ts, tk, ret, reg.at(ts)) for ts, tk, ret in trades]
    print(f"deployed penny: {len(tagged)} independent trades (deduped, net cost)\n")

    # ── (A) Discovery ──
    print("---- (A) DISCOVERY: deployed-penny trades bucketed by entry regime ----")

    def show(name, keyfn):
        print(f"  by {name}:")
        groups = {}
        for ts, tk, ret, (v, b, c) in tagged:
            k = keyfn(v, b, c)
            if k is not None:
                groups.setdefault(k, []).append(ret)
        for k in sorted(groups):
            a = aggregate(str(k), groups[k])
            print(f"    {k:<16} n={a.n:>4} win%={a.win_pct:>5.1f} exp%={a.expectancy_pct:>+6.2f} PF={_pf(a)}")
        print()

    show("breadth", lambda v, b, c: None if b is None else (
        "1 <0.30" if b < 0.30 else "2 0.30-0.50" if b < 0.50 else "3 0.50-0.70" if b < 0.70 else "4 >=0.70"))
    show("VIX level", lambda v, b, c: None if v is None else (
        "1 <17" if v < 17 else "2 17-18" if v < 18 else "3 18-20" if v < 20 else "4 >=20"))
    show("VIX direction", lambda v, b, c: None if c is None else ("falling/flat" if c <= 0 else "rising"))

    # ── (B) Validation ──
    print("---- (B) VALIDATION: regime gate on deployed penny (net cost), full + per-third ----")
    t0, t1 = decisions[0].ts, decisions[-1].ts
    span = t1 - t0
    edges = [t0, t0 + span / 3, t0 + 2 * span / 3, t1 + timedelta(seconds=1)]

    def third_of(ts):
        for j in range(3):
            if edges[j] <= ts < edges[j + 1]:
                return j
        return 2

    gates = {
        "ungated (baseline)": lambda v, b, c: True,
        "breadth>0.40": lambda v, b, c: (b or 0) > 0.40,
        "breadth>0.50": lambda v, b, c: (b or 0) > 0.50,
        "breadth>0.60": lambda v, b, c: (b or 0) > 0.60,
        "vix falling/flat": lambda v, b, c: (c if c is not None else 1) <= 0,
        "breadth>0.5 & vix<18": lambda v, b, c: (b or 0) > 0.5 and (v or 99) < 18,
    }
    print(f"  {'gate':<24}{'n':>5}{'win%':>7}{'exp%':>8}{'PF':>7}   per-third PF [t1,t2,t3]")
    for name, pred in gates.items():
        sel = [(ts, ret) for ts, tk, ret, (v, b, c) in tagged if pred(v, b, c)]
        a = aggregate(name, [r for _, r in sel])
        thirds = [[], [], []]
        for ts, r in sel:
            thirds[third_of(ts)].append(r)
        tpf = []
        for tt in thirds:
            ta = aggregate("x", tt)
            tpf.append(_pf(ta) if ta.n else "--")
        print(f"  {name:<24}{a.n:>5}{a.win_pct:>7.1f}{a.expectancy_pct:>+8.2f}{_pf(a):>7}   [{', '.join(tpf)}]")
    print("\n  A real conditional edge = PF clearly >1, decent n, AND consistent across thirds")
    print("  (not just one favorable window). Baseline ungated net PF ~ the top row.")


if __name__ == "__main__":
    main()
