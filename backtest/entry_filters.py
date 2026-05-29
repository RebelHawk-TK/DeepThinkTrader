"""Entry-filter backtest — which selection rules would lift expectancy?

Holds the recommended exit policy (trailing 3.0%, keep take-profit) FIXED and
replays the bot's real entries, then aggregates under different entry filters
(edge combo, conviction) using the RECORDED edge_combo/conviction.

It does NOT replay the LLM/news/sentiment pipeline — that isn't reproducible
historically. Instead it answers the decision-relevant question: "of the
entries the bot already chose, which selection rules separate the winners from
the losers?" That's the edge-recalibration signal.

Caveat: filtering shrinks the sample, so watch the n column — small subsets are
noisy. Pair with the descriptive edge_performance data, don't over-fit.

Run: ~/.venvs/deepthinktrader/bin/python -m backtest.entry_filters [--portfolio main]
"""
from __future__ import annotations

import argparse
from datetime import timedelta

from backtest.trade_replay import (
    ExitPolicy,
    aggregate,
    fetch_hourly_bars,
    load_entries,
    simulate_exit,
)

POLICY = ExitPolicy("trail3.0+TP", trail_activation_pct=2.0, trail_distance_pct=3.0, honor_tp=True)


def _has(combo: str, letter: str) -> bool:
    return letter in (combo or "")


FILTERS = [
    ("all entries", lambda e: True),
    ("conviction >= 7", lambda e: e.conviction >= 7),
    ("conviction >= 8", lambda e: e.conviction >= 8),
    ("has sentiment edge (S)", lambda e: _has(e.edge_combo, "S")),
    ("has fundamental edge (F)", lambda e: _has(e.edge_combo, "F")),
    ("no technical edge (drop any T)", lambda e: not _has(e.edge_combo, "T")),
    ("exclude T+S combo", lambda e: e.edge_combo != "T+S"),
    ("S-edge AND conv >= 7", lambda e: _has(e.edge_combo, "S") and e.conviction >= 7),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portfolio", default="main")
    args = ap.parse_args()

    entries = load_entries(args.portfolio)
    print(f"Loaded {len(entries)} closed long entries (portfolio={args.portfolio})")
    print(f"Exit policy held fixed: {POLICY.name} "
          f"(act {POLICY.trail_activation_pct} / trail {POLICY.trail_distance_pct})\n")

    results: list[tuple] = []  # (entry, return_pct)
    for e in entries:
        bars = fetch_hourly_bars(e.ticker, e.entry_time, e.entry_time + timedelta(days=30))
        res = simulate_exit(e, bars, POLICY)
        if res is not None:
            results.append((e, res.return_pct))
    print(f"Simulated {len(results)}/{len(entries)} entries with bars\n")

    # Descriptive: by edge combo.
    combos: dict[str, list[float]] = {}
    for e, r in results:
        combos.setdefault(e.edge_combo or "(none)", []).append(r)
    print("By edge combo (sorted by expectancy):")
    print(f"  {'combo':<12}{'n':>4}{'win%':>7}{'exp%':>8}{'PF':>6}")
    for combo, rs in sorted(combos.items(), key=lambda kv: -aggregate(kv[0], kv[1]).expectancy_pct):
        a = aggregate(combo, rs)
        pf = "inf" if a.profit_factor == float("inf") else f"{a.profit_factor:.2f}"
        print(f"  {combo:<12}{a.n:>4}{a.win_pct:>7.1f}{a.expectancy_pct:>8.2f}{pf:>6}")

    # Filter sweep.
    print(f"\n{'filter':<34}{'n':>4}{'win%':>7}{'avgW%':>7}{'avgL%':>7}{'exp%':>8}{'PF':>6}")
    print("-" * 73)
    for label, pred in FILTERS:
        rs = [r for e, r in results if pred(e)]
        a = aggregate(label, rs)
        pf = "inf" if a.profit_factor == float("inf") else f"{a.profit_factor:.2f}"
        print(f"{label:<34}{a.n:>4}{a.win_pct:>7.1f}{a.avg_win_pct:>7.2f}"
              f"{a.avg_loss_pct:>7.2f}{a.expectancy_pct:>8.2f}{pf:>6}")


if __name__ == "__main__":
    main()
