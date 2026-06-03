"""Entry-side walk-forward validator (Phase 2).

The exit replays (trade_replay / candidate_config) hold the bot's real ENTRIES
fixed and vary only exits, and they measure in-sample (fit and tested on the same
history). This module validates the ENTRY pipeline out-of-sample:

  1. It replays the bot's real DECISIONS from `analysis_results` — which store the
     recorded conviction, edge_details (F/T/S passed), stop/TP, price, AND the
     Claude judgment (conviction_adjustment / action_override / confidence) baked
     into the final conviction. So a candidate entry config can be re-applied to
     the *actual* LLM-influenced conviction without re-calling the API.
  2. For each decision a config would BUY, it simulates the trade forward from the
     decision's timestamp/price using hourly bars + the config's exit policy
     (reused from trade_replay), yielding a realized return.
  3. Walk-forward: slide an in-sample window, pick the best config from a grid on
     IS, apply it to the following out-of-sample window, accumulate OOS results.
     The IS↔OOS gap is the overfitting estimate. The static deployed config is
     measured on the same OOS windows for comparison.

Fidelity caveats (be honest):
  - Re-thresholding recorded conviction is faithful for conviction/edge-gate/exit
    changes (conviction is computed independently of the min_conviction threshold,
    edges are factual). It does NOT re-derive conviction, so it can't test changes
    to the scoring FORMULA or regime deltas.
  - The bot's BUY also requires catalyst>0; here we approximate by excluding
    recorded SELL decisions (catalyst<0) from the long universe.
  - Entry price = recorded current_price (the bot enters at market near analysis).
  - History is only ~2.5 months, so OOS windows are few — treat as a first signal.

Run: ~/.venvs/deepthinktrader/bin/python -m backtest.walk_forward_entries [--portfolio main|penny]
Read-only on trades.db.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
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


# ── Recorded decision (from analysis_results) ────────────────────────────────

@dataclass
class Decision:
    ticker: str
    ts: object              # datetime, UTC-naive
    conviction: float
    edges_firing: int
    has_f: bool
    has_t: bool
    has_s: bool
    price: float
    stop_pct: float
    tp_pct: float
    recorded_action: str


def load_decisions(portfolio: str) -> list[Decision]:
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT ticker, timestamp, action, conviction, stop_loss_pct, take_profit_pct, analysis_json "
        "FROM analysis_results WHERE portfolio = ? AND analysis_json IS NOT NULL ORDER BY timestamp",
        (portfolio,),
    ).fetchall()
    conn.close()
    out: list[Decision] = []
    for r in rows:
        try:
            a = json.loads(r["analysis_json"])
        except Exception:
            continue
        price = float(a.get("current_price") or 0)
        if price <= 0:
            continue
        eds = a.get("edge_details") or []
        def passed(lbl: str) -> bool:
            return any(e.get("passed") and e.get("label") == lbl for e in eds)
        out.append(Decision(
            ticker=r["ticker"],
            ts=_parse_ts(r["timestamp"]),
            conviction=float(a.get("conviction") or r["conviction"] or 0),
            edges_firing=int(a.get("edges_firing") or 0),
            has_f=passed("Fundamental"), has_t=passed("Technical"), has_s=passed("Sentiment"),
            price=price,
            stop_pct=float(a.get("stop_loss_pct") or r["stop_loss_pct"] or 5.0),
            tp_pct=float(a.get("take_profit_pct") or r["take_profit_pct"] or 0.0),
            recorded_action=(a.get("action") or r["action"] or "HOLD"),
        ))
    return out


# ── Candidate entry config ───────────────────────────────────────────────────

@dataclass
class EntryConfig:
    name: str
    min_conviction: float
    require_fundamental: bool
    require_sentiment: bool
    exit: ExitPolicy
    min_edges: int = 2


def would_buy(d: Decision, cfg: EntryConfig) -> bool:
    if d.recorded_action == "SELL":          # bearish catalyst — not a long
        return False
    if d.edges_firing < cfg.min_edges:
        return False
    if d.conviction < cfg.min_conviction:
        return False
    if cfg.require_fundamental and not d.has_f:
        return False
    if cfg.require_sentiment and not d.has_s:
        return False
    return True


def _entry_of(d: Decision) -> Entry:
    return Entry(
        trade_id=0, ticker=d.ticker, entry_time=d.ts, entry_price=d.price,
        stop_price=d.price * (1 - d.stop_pct / 100),
        tp_price=d.price * (1 + d.tp_pct / 100) if d.tp_pct else 0.0,
        actual_exit_price=None, actual_pnl=None, actual_return_pct=None,
        conviction=d.conviction,
    )


def evaluate(cfg: EntryConfig, decisions: list[Decision]) -> tuple:
    """Return (Agg, n_signals) for the config over `decisions`."""
    returns: list[float] = []
    for d in decisions:
        if not would_buy(d, cfg):
            continue
        bars = fetch_hourly_bars(d.ticker, d.ts, d.ts + timedelta(days=30))
        res = simulate_exit(_entry_of(d), bars, cfg.exit)
        if res is not None:
            returns.append(res.return_pct)
    return aggregate(cfg.name, returns), len(returns)


# ── Config grids (per book) ──────────────────────────────────────────────────

def _grid(portfolio: str) -> list[EntryConfig]:
    if portfolio == "penny":
        trails = [("trail1.5", 2.0, 1.5), ("trail2.0", 2.0, 2.0), ("trail3.0", 2.0, 3.0)]
        out = []
        for mc in (6.0, 7.0, 8.0):
            for req_s in (False, True):
                for nm, ta, td in trails:
                    out.append(EntryConfig(
                        f"conv{mc:g}{'+S' if req_s else ''}/{nm}", mc,
                        require_fundamental=False, require_sentiment=req_s,
                        exit=ExitPolicy(nm, ta, td)))
        return out
    trails = [("trail3.0", 2.0, 3.0), ("trail3.5", 2.5, 3.5), ("trail4.0", 3.0, 4.0)]
    out = []
    for mc in (7.0, 8.0):
        for req_f in (True,):  # main always requires fundamental (validated)
            for nm, ta, td in trails:
                out.append(EntryConfig(
                    f"conv{mc:g}{'+F' if req_f else ''}/{nm}", mc,
                    require_fundamental=req_f, require_sentiment=False,
                    exit=ExitPolicy(nm, ta, td)))
    return out


def _deployed(portfolio: str) -> EntryConfig:
    if portfolio == "penny":
        return EntryConfig("DEPLOYED penny (conv7+S/trail2.0)", 7.0, False, True,
                           ExitPolicy("trail2.0", 2.0, 2.0))
    return EntryConfig("DEPLOYED main (conv7+F/trail3.0)", 7.0, True, False,
                       ExitPolicy("trail3.0", 2.0, 3.0))


# ── Walk-forward ─────────────────────────────────────────────────────────────

def walk_forward(portfolio: str, is_days: int, oos_days: int, min_is_trades: int) -> None:
    decisions = load_decisions(portfolio)
    if not decisions:
        print(f"no decisions for {portfolio}")
        return
    t0, t1 = decisions[0].ts, decisions[-1].ts
    span = (t1 - t0).days
    print(f"\n===== {portfolio.upper()} — {len(decisions)} recorded decisions, "
          f"{t0.date()}..{t1.date()} ({span}d) =====")
    print(f"walk-forward: IS={is_days}d  OOS={oos_days}d  step={oos_days}d\n")

    grid = _grid(portfolio)
    deployed = _deployed(portfolio)

    wf_oos_returns: list[float] = []      # adaptive: pick best-on-IS, trade OOS
    dep_oos_returns: list[float] = []     # static deployed config, same OOS windows
    picks: list[str] = []
    win = 0
    start = t0
    while start + timedelta(days=is_days + oos_days) <= t1 + timedelta(days=1):
        is_lo, is_hi = start, start + timedelta(days=is_days)
        oos_lo, oos_hi = is_hi, is_hi + timedelta(days=oos_days)
        is_dec = [d for d in decisions if is_lo <= d.ts < is_hi]
        oos_dec = [d for d in decisions if oos_lo <= d.ts < oos_hi]
        win += 1
        # pick best config on IS by profit factor (require enough trades)
        scored = []
        for cfg in grid:
            agg, n = evaluate(cfg, is_dec)
            if n >= min_is_trades:
                scored.append((agg.profit_factor, agg.expectancy_pct, cfg, agg, n))
        if not scored:
            print(f"  win{win} {is_lo.date()}->{oos_hi.date()}: no IS config met min trades — skip")
            start = start + timedelta(days=oos_days)
            continue
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        _, _, best, best_is_agg, best_is_n = scored[0]
        # apply chosen config to OOS
        oos_returns_win: list[float] = []
        for d in oos_dec:
            if would_buy(d, best):
                bars = fetch_hourly_bars(d.ticker, d.ts, d.ts + timedelta(days=30))
                res = simulate_exit(_entry_of(d), bars, best.exit)
                if res is not None:
                    oos_returns_win.append(res.return_pct)
        oos_agg = aggregate("oos", oos_returns_win)
        wf_oos_returns.extend(oos_returns_win)
        picks.append(best.name)
        # deployed config on same OOS window
        for d in oos_dec:
            if would_buy(d, deployed):
                bars = fetch_hourly_bars(d.ticker, d.ts, d.ts + timedelta(days=30))
                res = simulate_exit(_entry_of(d), bars, deployed.exit)
                if res is not None:
                    dep_oos_returns.append(res.return_pct)
        print(f"  win{win} {is_lo.date()}->{oos_hi.date()}: IS pick={best.name} "
              f"(IS n={best_is_n} PF={best_is_agg.profit_factor:.2f}) | "
              f"OOS n={oos_agg.n} PF={oos_agg.profit_factor:.2f} exp={oos_agg.expectancy_pct:+.2f}%")
        start = start + timedelta(days=oos_days)

    print("\n  ---- aggregate across OOS windows ----")
    wf = aggregate("walk-forward (adaptive)", wf_oos_returns)
    dep = aggregate("deployed (static)", dep_oos_returns)
    full_dep, full_n = evaluate(deployed, decisions)   # in-sample, whole history
    hdr = f"  {'config':<32}{'n':>5}{'win%':>7}{'R:R':>6}{'exp%':>8}{'PF':>7}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    for a in (wf, dep, full_dep):
        rr = "inf" if a.rr == float("inf") else f"{a.rr:.2f}"
        pf = "inf" if a.profit_factor == float("inf") else f"{a.profit_factor:.2f}"
        label = a.label + (" [IS, full]" if a is full_dep else " [OOS]")
        print(f"  {label:<32}{a.n:>5}{a.win_pct:>7.1f}{rr:>6}{a.expectancy_pct:>8.2f}{pf:>7}")
    if full_dep.profit_factor and dep.profit_factor:
        gap = full_dep.profit_factor - dep.profit_factor
        print(f"\n  IS→OOS PF gap (deployed): {full_dep.profit_factor:.2f} → {dep.profit_factor:.2f} "
              f"({gap:+.2f}; large positive gap = overfit)")
    if picks:
        print(f"  IS picks across windows: {dict(Counter(picks))}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portfolio", default="penny", choices=["penny", "main"])
    ap.add_argument("--is-days", type=int, default=28)
    ap.add_argument("--oos-days", type=int, default=14)
    ap.add_argument("--min-is-trades", type=int, default=8)
    args = ap.parse_args()
    walk_forward(args.portfolio, args.is_days, args.oos_days, args.min_is_trades)


if __name__ == "__main__":
    main()
