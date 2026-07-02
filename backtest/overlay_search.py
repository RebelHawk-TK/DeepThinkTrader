"""Overlay search — test filters/selection ON TOP of a validated base signal.

signal_search tests standalone entry rules; this tests OVERLAYS on the deployed
momentum_breakout base: does adding a filter (SA-bearish veto) or a selection
rule (same-day rank, top-N) improve the base's net PF — and does the improvement
survive a bootstrap CI and per-thirds consistency?

All variants below are PRE-SPECIFIED and all results are reported (no
cherry-picking; the variant count is part of the evidence — Deflated Sharpe
logic). MAIN book (>=$5) only; the penny book is retired.

Data caveat: the seeking_alpha fields in historical research_reports come from
the RSS feed only (the vault-email leg was broken until 2026-07-02), so this
tests RSS-derived SA sentiment.

Gate (same as the 2026-06-25 signal validation): 5,000-sample bootstrap PF 95%
CI on net returns; PASS = CI lower bound > 1.0, plus PF > 1 in all three
time-thirds.

Run: ~/.venvs/deepthinktrader/bin/python -m backtest.overlay_search
"""
from __future__ import annotations

import random
from collections import defaultdict
from datetime import timedelta

from backtest.signal_search import SIGNALS, Cand, load_candidates, sim
from backtest.trade_replay import ExitPolicy, aggregate, fetch_hourly_bars, simulate_exit
from backtest.signal_search import _entry

BASE = SIGNALS["momentum_breakout"]

MAIN_POLICY = ExitPolicy("trail3.0", 2.0, 3.0)
MAIN_COST = 0.3
BOOTSTRAP_N = 5_000
BOOTSTRAP_SEED = 20260702  # deterministic runs


# ── Pre-specified overlay variants ───────────────────────────────────────────

def _sa_covered(c: Cand) -> bool:
    return (c.sa_bull + c.sa_bear) >= 2


VETOES = {
    # veto when average RSS sentiment is negative with minimum coverage
    "sa_veto_sent": lambda c: _sa_covered(c) and c.sa_sent < -0.1,
    # veto when bearish articles outnumber bullish with minimum volume
    "sa_veto_skew": lambda c: c.sa_bear >= 2 and c.sa_bear > c.sa_bull,
}

RANK_TOP_N = 3
# rank key: proximity to 30-day high (relative-strength proxy available in reports)
RANK_KEY = lambda c: (c.price / c.high30) if c.high30 > 0 else 0.0  # noqa: E731


def sim_ranked(cands: list[Cand], policy: ExitPolicy, cost: float, top_n: int) -> list[tuple]:
    """Base signal + same-day ranked selection: dedup per ticker per day (first
    firing), rank the day's valid signals by RANK_KEY, keep top_n, then apply
    the same 1-open-position-per-ticker dedup and exit simulation as sim()."""
    by_day: dict[object, dict[str, Cand]] = defaultdict(dict)
    for c in cands:
        if BASE(c) and c.ticker not in by_day[c.ts.date()]:
            by_day[c.ts.date()][c.ticker] = c

    selected: list[Cand] = []
    for day in sorted(by_day):
        day_cands = sorted(by_day[day].values(), key=RANK_KEY, reverse=True)
        selected.extend(day_cands[:top_n])
    selected.sort(key=lambda c: c.ts)

    out, open_until = [], {}
    for c in selected:
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


# ── Bootstrap PF confidence interval ─────────────────────────────────────────

def _profit_factor(returns: list[float]) -> float:
    gains = sum(r for r in returns if r > 0)
    losses = -sum(r for r in returns if r < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def bootstrap_pf_ci(returns: list[float], n_samples: int = BOOTSTRAP_N) -> tuple[float, float, float]:
    """95% CI on profit factor via resampling with replacement."""
    rng = random.Random(BOOTSTRAP_SEED)
    n = len(returns)
    pfs = sorted(
        _profit_factor([returns[rng.randrange(n)] for _ in range(n)])
        for _ in range(n_samples)
    )
    return pfs[int(0.025 * n_samples)], pfs[int(0.5 * n_samples)], pfs[int(0.975 * n_samples)]


def _fmt_pf(x: float) -> str:
    return "inf" if x == float("inf") else f"{x:.2f}"


def report(name: str, trades: list[tuple], edges) -> None:
    rets = [r for _, r in trades]
    a = aggregate(name, rets)
    th: list[list[float]] = [[], [], []]
    for ts, r in trades:
        for j in range(3):
            if edges[j] <= ts < edges[j + 1]:
                th[j].append(r)
                break
        else:
            th[2].append(r)
    thirds = [(_fmt_pf(_profit_factor(x)) if x else "--") for x in th]
    if len(rets) >= 10:
        lo, med, hi = bootstrap_pf_ci(rets)
        gate = "PASS" if (lo > 1.0 and all(x not in ("--",) and (x == "inf" or float(x) > 1.0) for x in thirds)) else "fail"
        ci = f"[{_fmt_pf(lo)}, {_fmt_pf(med)}, {_fmt_pf(hi)}]"
    else:
        ci, gate = "n too small", "fail"
    print(f"  {name:<24}{a.n:>6}{a.win_pct:>7.1f}{a.expectancy_pct:>+8.2f}{_fmt_pf(a.profit_factor):>7}"
          f"   {ci:<22} thirds [{', '.join(thirds)}]  {gate}")


def main() -> None:
    cands = [c for c in load_candidates() if c.price >= 5]
    t0, t1 = cands[0].ts, cands[-1].ts
    span = t1 - t0
    edges = [t0, t0 + span / 3, t0 + 2 * span / 3, t1 + timedelta(seconds=1)]
    print(f"MAIN book: {len(cands)} candidates {t0.date()}..{t1.date()} | "
          f"exit {MAIN_POLICY.name} | cost {MAIN_COST}% | bootstrap n={BOOTSTRAP_N}")
    print(f"  {'variant':<24}{'n':>6}{'win%':>7}{'exp%':>8}{'PF':>7}   {'PF 95% CI':<22} consistency        gate")

    base_trades = sim(BASE, cands, MAIN_POLICY, MAIN_COST)
    report("mb_base", base_trades, edges)

    for vname, veto in VETOES.items():
        kept = sim(lambda c, v=veto: BASE(c) and not v(c), cands, MAIN_POLICY, MAIN_COST)
        report(f"mb+{vname}", kept, edges)
        # the vetoed complement: what the filter removed (helps iff its PF < base)
        removed = sim(lambda c, v=veto: BASE(c) and v(c), cands, MAIN_POLICY, MAIN_COST)
        rets = [r for _, r in removed]
        a = aggregate("removed", rets)
        print(f"    └─ vetoed subset       {a.n:>4}{a.win_pct:>7.1f}{a.expectancy_pct:>+8.2f}"
              f"{_fmt_pf(a.profit_factor):>7}   (veto helps iff this PF < base PF)")

    ranked = sim_ranked(cands, MAIN_POLICY, MAIN_COST, RANK_TOP_N)
    report(f"mb+rank_top{RANK_TOP_N}", ranked, edges)

    print(f"\nVariants tested this run: {2 + len(VETOES) + 1} (count feeds the multiple-testing prior).")
    print("Adopt an overlay only if it PASSes AND clearly beats mb_base's CI — not on a nudge.")


if __name__ == "__main__":
    main()
