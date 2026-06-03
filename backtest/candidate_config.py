"""Candidate per-book config backtest — validate the EXACT entry-filter + exit-policy
combo we intend to deploy, per portfolio, against the bot's real recorded entries.

Deployment gate (per the plan): only deploy a per-book config that backtests
PF > 1.1 AND R:R > current-live for that book.

Reuses the trade_replay primitives (mechanical exit replay on real entries, hourly
bars). Caveats inherited: models mechanical exits only, NOT the LLM/news pipeline;
filtering shrinks the sample, so watch the n column. Read-only on trades.db.

Run: ~/.venvs/deepthinktrader/bin/python -m backtest.candidate_config
"""
from __future__ import annotations

from datetime import timedelta

from backtest.trade_replay import (
    ExitPolicy,
    aggregate,
    fetch_hourly_bars,
    load_entries,
    simulate_exit,
)


def _has(combo: str, letter: str) -> bool:
    return letter in (combo or "")


FILTERS = {
    "all": lambda e: True,
    "conv>=7": lambda e: e.conviction >= 7,
    "S & conv>=7": lambda e: _has(e.edge_combo, "S") and e.conviction >= 7,
    "F & conv>=7": lambda e: _has(e.edge_combo, "F") and e.conviction >= 7,
    "F & !T+S & conv>=8": lambda e: (
        _has(e.edge_combo, "F") and e.edge_combo != "T+S" and e.conviction >= 8
    ),
    "excl T+S": lambda e: e.edge_combo != "T+S",
}

EXITS = {
    "trail1.5": ExitPolicy("trail1.5", 2.0, 1.5),
    "trail2.0": ExitPolicy("trail2.0", 2.0, 2.0),
    "trail3.0": ExitPolicy("trail3.0", 2.0, 3.0),   # current live (both books)
    "trail3.5@2.5": ExitPolicy("trail3.5@2.5", 2.5, 3.5),
    "trail4.0@3": ExitPolicy("trail4.0@3", 3.0, 4.0),
}

# Per book: ordered rows of (label, filter_key, exit_key). First row = current-live baseline.
BOOK = {
    "penny": [
        ("current live  (all / trail3.0)",      "all",          "trail3.0"),
        ("cand A  (S&conv7 / trail1.5)",         "S & conv>=7",  "trail1.5"),
        ("cand B  (S&conv7 / trail2.0)",         "S & conv>=7",  "trail2.0"),
        ("cand C  (conv7 / trail2.0)",           "conv>=7",      "trail2.0"),
    ],
    "main": [
        ("current live  (F&conv7 / trail3.0)",   "F & conv>=7",          "trail3.0"),
        ("cand A  (F&!T+S&conv8 / trail3.5)",    "F & !T+S & conv>=8",   "trail3.5@2.5"),
        ("cand B  (F&!T+S&conv8 / trail3.0)",    "F & !T+S & conv>=8",   "trail3.0"),
        ("cand C  (exclT+S / trail4.0)",         "excl T+S",             "trail4.0@3"),
    ],
}


def run_book(book: str) -> None:
    entries = load_entries(book)
    # Simulate each entry under every exit policy once (bars cached per ticker).
    sims: list[tuple] = []   # (entry, {exit_key: return_pct})
    for e in entries:
        bars = fetch_hourly_bars(e.ticker, e.entry_time, e.entry_time + timedelta(days=30))
        rec = {}
        for xk, pol in EXITS.items():
            res = simulate_exit(e, bars, pol)
            if res is not None:
                rec[xk] = res.return_pct
        if rec:
            sims.append((e, rec))

    print(f"\n===== {book.upper()}  ({len(sims)} entries with bars) =====")
    print(f"  {'config':<36}{'n':>4}{'win%':>7}{'R:R':>6}{'exp%':>8}{'PF':>7}{'gate':>6}")
    base_rr = None
    for label, fk, xk in BOOK[book]:
        pred = FILTERS[fk]
        rs = [rec[xk] for e, rec in sims if xk in rec and pred(e)]
        a = aggregate(label, rs)
        if base_rr is None:                      # first row = current-live baseline
            base_rr = a.rr
            gate = "base"
        else:
            gate = "PASS" if (a.profit_factor > 1.1 and a.rr > base_rr) else "--"
        rr = "inf" if a.rr == float("inf") else f"{a.rr:.2f}"
        pf = "inf" if a.profit_factor == float("inf") else f"{a.profit_factor:.2f}"
        print(f"  {label:<36}{a.n:>4}{a.win_pct:>7.1f}{rr:>6}"
              f"{a.expectancy_pct:>8.2f}{pf:>7}{gate:>6}")


def main() -> None:
    for book in ("penny", "main"):
        run_book(book)
    print("\nGate: PF>1.1 AND R:R>current-live for that book. "
          "Caveat: mechanical exits on recorded entries; small n is noisy.")


if __name__ == "__main__":
    main()
