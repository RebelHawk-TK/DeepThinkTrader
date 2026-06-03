"""Entry-side walk-forward validator (Phase 2) — with cost + dedupe.

The exit replays (trade_replay / candidate_config) hold the bot's real ENTRIES
fixed and vary only exits, in-sample. This module validates the ENTRY pipeline
out-of-sample, and (v2) under realistic frictions:

  1. Replays the bot's recorded DECISIONS from `analysis_results` — recorded
     conviction, edge_details (F/T/S passed), stop/TP, price, AND the Claude
     judgment (conviction_adjustment / action_override) baked into the final
     conviction. So a candidate entry config is re-applied to the *actual*
     LLM-influenced conviction without re-calling the API.
  2. DEDUPE: the bot re-analyzes the same ticker every cycle, so one setup yields
     many correlated signals. We replay position-aware — at most one open position
     per ticker at a time (which is also the bot's real duplicate-position gate),
     so each trade is independent. This collapses ~10-20 correlated signals into 1.
  3. COST: round-trip slippage+spread subtracted from every trade, taken from the
     bot's OWN recorded fills (`slippage_records`, median |slippage_pct| x2), with
     a config-spread fallback when data is thin. Penny spreads are wide, so this is
     where the idealized edge gets reality-tested.
  4. Walk-forward: slide IS -> OOS, pick best-on-IS from a grid, trade it OOS,
     accumulate. IS<->OOS gap = overfitting; GROSS vs NET = friction impact.

Fidelity caveats: re-thresholding recorded conviction is faithful for
conviction/edge-gate/exit changes (not for scoring-formula changes); BUY also
needs catalyst>0, approximated by excluding recorded SELLs; entry price =
recorded current_price; ~2.5mo history = few OOS windows.

Run: ~/.venvs/deepthinktrader/bin/python -m backtest.walk_forward_entries [--portfolio main|penny] [--gross]
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

        def passed(lbl: str, _eds=eds) -> bool:
            return any(e.get("passed") and e.get("label") == lbl for e in _eds)

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


# Spread-based round-trip cost (%). The bot uses LIMIT orders for penny, so its
# recorded slippage (~0%) masks the true ~2% penny spread + non-fill cost; penny
# therefore uses this spread estimate, not recorded slippage. Main uses market
# orders, so its recorded slippage is reliable.
_SPREAD_COST = {"penny": 2.5, "main": 0.30}


def load_round_trip_cost(portfolio: str) -> tuple[float, str]:
    """Realistic round-trip cost %. Main from recorded fills (floored at spread);
    penny from the spread estimate (recorded penny slippage is a limit-order artifact)."""
    if portfolio == "main":
        conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        try:
            vals = sorted(
                abs(float(r[0])) for r in conn.execute(
                    "SELECT slippage_pct FROM slippage_records WHERE portfolio='main' AND slippage_pct IS NOT NULL"
                ) if r[0] is not None
            )
        finally:
            conn.close()
        if len(vals) >= 20:
            med = vals[len(vals) // 2]
            cost = max(round(2 * med, 3), _SPREAD_COST["main"])
            return cost, f"recorded: {len(vals)} fills, median |slip| {med:.2f}%x2, floored at {_SPREAD_COST['main']}% spread"
    return _SPREAD_COST[portfolio], (
        "spread-based (recorded penny slippage unreliable: limit orders)"
        if portfolio == "penny" else "spread-based (thin recorded data)"
    )


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


def sim_returns(cfg: EntryConfig, decisions: list[Decision], cost_pct: float,
                dedupe: bool = True) -> list[float]:
    """Position-aware, cost-adjusted forward returns. `decisions` must be ts-sorted.

    With dedupe, at most one open position per ticker at a time (mirrors the bot's
    duplicate-position gate) so trades are independent. cost_pct is the round-trip
    friction subtracted from each trade's % return.
    """
    returns: list[float] = []
    open_until: dict[str, object] = {}
    for d in decisions:
        if not would_buy(d, cfg):
            continue
        if dedupe and d.ticker in open_until and d.ts < open_until[d.ticker]:
            continue
        bars = fetch_hourly_bars(d.ticker, d.ts, d.ts + timedelta(days=30))
        res = simulate_exit(_entry_of(d), bars, cfg.exit)
        if res is None:
            continue
        if dedupe:
            after = [b for b in bars if b.timestamp >= d.ts]
            idx = min(res.bars_held, len(after)) - 1
            open_until[d.ticker] = after[idx].timestamp if idx >= 0 else d.ts
        returns.append(res.return_pct - cost_pct)
    return returns


def evaluate(cfg: EntryConfig, decisions: list[Decision], cost_pct: float,
             dedupe: bool = True) -> tuple:
    rs = sim_returns(cfg, decisions, cost_pct, dedupe)
    return aggregate(cfg.name, rs), len(rs)


# ── Config grids (per book) ──────────────────────────────────────────────────

def _grid(portfolio: str) -> list[EntryConfig]:
    if portfolio == "penny":
        trails = [("trail1.5", 2.0, 1.5), ("trail2.0", 2.0, 2.0), ("trail3.0", 2.0, 3.0)]
        return [
            EntryConfig(f"conv{mc:g}{'+S' if req_s else ''}/{nm}", mc, False, req_s, ExitPolicy(nm, ta, td))
            for mc in (6.0, 7.0, 8.0) for req_s in (False, True) for nm, ta, td in trails
        ]
    trails = [("trail3.0", 2.0, 3.0), ("trail3.5", 2.5, 3.5), ("trail4.0", 3.0, 4.0)]
    return [
        EntryConfig(f"conv{mc:g}+F/{nm}", mc, True, False, ExitPolicy(nm, ta, td))
        for mc in (7.0, 8.0) for nm, ta, td in trails
    ]


def _deployed(portfolio: str) -> EntryConfig:
    if portfolio == "penny":
        return EntryConfig("DEPLOYED penny (conv7+S/trail2.0)", 7.0, False, True, ExitPolicy("trail2.0", 2.0, 2.0))
    return EntryConfig("DEPLOYED main (conv7+F/trail3.0)", 7.0, True, False, ExitPolicy("trail3.0", 2.0, 3.0))


# ── Walk-forward ─────────────────────────────────────────────────────────────

def _fmt(a, label_override=None):
    rr = "inf" if a.rr == float("inf") else f"{a.rr:.2f}"
    pf = "inf" if a.profit_factor == float("inf") else f"{a.profit_factor:.2f}"
    label = label_override or a.label
    return f"  {label:<40}{a.n:>5}{a.win_pct:>7.1f}{rr:>6}{a.expectancy_pct:>8.2f}{pf:>7}"


def walk_forward(portfolio: str, is_days: int, oos_days: int, min_is_trades: int,
                 gross: bool) -> None:
    decisions = load_decisions(portfolio)
    if not decisions:
        print(f"no decisions for {portfolio}")
        return
    cost_pct, cost_src = load_round_trip_cost(portfolio)
    if gross:
        cost_pct = 0.0
    t0, t1 = decisions[0].ts, decisions[-1].ts
    print(f"\n===== {portfolio.upper()} — {len(decisions)} decisions, "
          f"{t0.date()}..{t1.date()} ({(t1 - t0).days}d) =====")
    print(f"cost: round-trip {cost_pct:.2f}% ({cost_src}){'  [GROSS override]' if gross else ''} | "
          f"dedupe: 1 open position/ticker")
    print(f"walk-forward: IS={is_days}d  OOS={oos_days}d  step={oos_days}d\n")

    grid = _grid(portfolio)
    deployed = _deployed(portfolio)

    wf_oos: list[float] = []
    dep_oos: list[float] = []
    picks: list[str] = []
    win = 0
    start = t0
    while start + timedelta(days=is_days + oos_days) <= t1 + timedelta(days=1):
        is_hi = start + timedelta(days=is_days)
        oos_hi = is_hi + timedelta(days=oos_days)
        is_dec = [d for d in decisions if start <= d.ts < is_hi]
        oos_dec = [d for d in decisions if is_hi <= d.ts < oos_hi]
        win += 1
        scored = []
        for cfg in grid:
            agg, n = evaluate(cfg, is_dec, cost_pct)
            if n >= min_is_trades:
                scored.append((agg.profit_factor, agg.expectancy_pct, cfg, agg, n))
        if not scored:
            print(f"  win{win} {start.date()}->{oos_hi.date()}: no IS config met min {min_is_trades} trades — skip")
            start = start + timedelta(days=oos_days)
            continue
        scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
        _, _, best, bis, bis_n = scored[0]
        ow = sim_returns(best, oos_dec, cost_pct)
        wf_oos.extend(ow)
        dep_oos.extend(sim_returns(deployed, oos_dec, cost_pct))
        picks.append(best.name)
        oa = aggregate("oos", ow)
        print(f"  win{win} {start.date()}->{oos_hi.date()}: IS pick={best.name} "
              f"(IS n={bis_n} PF={bis.profit_factor:.2f}) | OOS n={oa.n} PF={oa.profit_factor:.2f} "
              f"exp={oa.expectancy_pct:+.2f}%")
        start = start + timedelta(days=oos_days)

    print("\n  ---- deployed config: friction + OOS impact (all deduped) ----")
    hdr = f"  {'config / regime':<40}{'n':>5}{'win%':>7}{'R:R':>6}{'exp%':>8}{'PF':>7}"
    print(hdr)
    print("  " + "-" * (len(hdr) - 2))
    gross_full = evaluate(deployed, decisions, 0.0)[0]
    net_full = evaluate(deployed, decisions, cost_pct)[0]
    print(_fmt(gross_full, "GROSS (no cost), full history [IS]"))
    print(_fmt(net_full, f"NET (cost {cost_pct:.2f}%), full history [IS]"))
    print(_fmt(aggregate("x", dep_oos), "NET, OUT-OF-SAMPLE [OOS]"))
    print(_fmt(aggregate("x", wf_oos), "NET, adaptive walk-forward [OOS]"))

    print("\n  ---- cost sensitivity (deployed, full history, deduped) ----")
    print(f"  {'round-trip cost':<18}{'trades':>7}{'win%':>7}{'exp%':>9}{'PF':>7}")
    for c in (0.0, 1.0, 2.0, 2.5, 3.0, 4.0):
        a = aggregate("x", sim_returns(deployed, decisions, c))
        pf = "inf" if a.profit_factor == float("inf") else f"{a.profit_factor:.2f}"
        print(f"  {c:>4.1f}%{'':<13}{a.n:>7}{a.win_pct:>7.1f}{a.expectancy_pct:>9.2f}{pf:>7}")
    if picks:
        print(f"\n  IS picks across windows: {dict(Counter(picks))}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portfolio", default="penny", choices=["penny", "main"])
    ap.add_argument("--is-days", type=int, default=28)
    ap.add_argument("--oos-days", type=int, default=14)
    ap.add_argument("--min-is-trades", type=int, default=6)
    ap.add_argument("--gross", action="store_true", help="disable cost (idealized)")
    args = ap.parse_args()
    walk_forward(args.portfolio, args.is_days, args.oos_days, args.min_is_trades, args.gross)


if __name__ == "__main__":
    main()
