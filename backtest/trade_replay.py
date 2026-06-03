"""Exit-policy replay backtest.

Replays the bot's ACTUAL recorded entries (from trades.db) against historical
hourly bars under different exit policies, so we can compare realized
reward:risk *before* changing the live trailing-stop / take-profit logic.

Why this design (vs the bar-replay Engine in engine.py): the Engine generates
its own entries from a toy Strategy. The expectancy problem is in the EXITS, so
we hold the real entries fixed and vary only the exit policy. `simulate_exit`
mirrors `Engine._update_exits` exactly (stop -> trailing -> take-profit, using
each bar's low/high for intrabar touches) so results correspond to production.

Resolution: holds average ~1 day, so daily bars are too coarse — we use hourly
(yfinance `1h`, available ~730 days back, covers the full trade history).

Run:  ~/.venvs/deepthinktrader/bin/python -m backtest.trade_replay [--limit N] [--portfolio main]
Read-only on trades.db (opened mode=ro). No live state is touched.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from brokers.base import Bar

DB_PATH = Path(__file__).resolve().parents[1] / "trades.db"


# ── Entry records (the bot's real trades) ────────────────────────────────────

@dataclass
class Entry:
    trade_id: int
    ticker: str
    entry_time: datetime          # UTC-naive
    entry_price: float
    stop_price: float
    tp_price: float
    actual_exit_price: float | None
    actual_pnl: float | None
    actual_return_pct: float | None
    conviction: float = 0.0
    edge_combo: str = ""


def _parse_ts(s: str) -> datetime:
    """Parse a trades.db timestamp into a UTC-naive datetime."""
    s = s.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        dt = datetime.fromisoformat(s[:19])
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def load_entries(portfolio: str = "main", limit: int | None = None) -> list[Entry]:
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    q = """
        SELECT t.id, t.ticker, t.timestamp, t.entry_price, t.stop_loss_price,
               t.take_profit_price, t.exit_price, t.pnl, t.conviction,
               (SELECT edge_combo FROM edge_performance ep
                WHERE ep.trade_id = t.id LIMIT 1) AS edge_combo
        FROM trades t
        WHERE t.status='CLOSED' AND t.action='BUY' AND t.entry_price > 0
          AND t.portfolio = ?
        ORDER BY t.id
    """
    rows = conn.execute(q, (portfolio,)).fetchall()
    conn.close()
    out: list[Entry] = []
    for r in rows:
        entry_px = float(r["entry_price"])
        exit_px = float(r["exit_price"]) if r["exit_price"] is not None else None
        ret = ((exit_px - entry_px) / entry_px * 100) if exit_px else None
        out.append(Entry(
            trade_id=r["id"],
            ticker=r["ticker"],
            entry_time=_parse_ts(r["timestamp"]),
            entry_price=entry_px,
            stop_price=float(r["stop_loss_price"] or 0),
            tp_price=float(r["take_profit_price"] or 0),
            actual_exit_price=exit_px,
            actual_pnl=float(r["pnl"]) if r["pnl"] is not None else None,
            actual_return_pct=ret,
            conviction=float(r["conviction"]) if r["conviction"] is not None else 0.0,
            edge_combo=r["edge_combo"] or "",
        ))
    if limit:
        out = out[:limit]
    return out


# ── Hourly bar feed (yfinance, cached per ticker) ────────────────────────────

_bar_cache: dict[str, list[Bar]] = {}
_CACHE_DIR = os.path.expanduser("~/.cache/deepthinktrader/bars")
# Wide fetch window so one cached file per ticker serves every decision and script.
# Covers the backtest era (first decisions 2026-03-23) with buffer.
_FETCH_START = date(2026, 2, 1)


def _wide_bars(ticker: str) -> list[Bar]:
    """Full hourly history for a ticker, memoized + disk-cached as JSON so repeat runs
    are DETERMINISTIC. yfinance revises/varies recent bars and intermittently 404s
    run-to-run, which made backtest PF wobble; freezing the first successful fetch fixes
    that. Failed (empty) fetches are NOT cached, so they retry next run."""
    if ticker in _bar_cache:
        return _bar_cache[ticker]
    path = os.path.join(_CACHE_DIR, f"{ticker.replace('/', '_')}.json")
    if os.path.exists(path):
        with open(path) as f:
            raw = json.load(f)
        bars = [Bar(ticker=ticker, timestamp=datetime.fromisoformat(r[0]),
                    open=r[1], high=r[2], low=r[3], close=r[4], volume=r[5]) for r in raw]
        _bar_cache[ticker] = bars
        return bars
    import yfinance as yf

    bars = []
    try:
        df = yf.Ticker(ticker).history(
            start=_FETCH_START, end=date.today() + timedelta(days=1),
            interval="1h", auto_adjust=False, raise_errors=False,
        )
        for ts, row in df.iterrows():
            t = ts.to_pydatetime()
            if t.tzinfo is not None:
                t = t.astimezone(timezone.utc).replace(tzinfo=None)
            bars.append(Bar(
                ticker=ticker, timestamp=t,
                open=float(row["Open"]), high=float(row["High"]),
                low=float(row["Low"]), close=float(row["Close"]),
                volume=int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
            ))
    except Exception as e:  # noqa: BLE001 - data feed is best-effort
        print(f"  ! bar fetch failed for {ticker}: {e}", file=sys.stderr)
    if bars:  # only freeze successful fetches; let transient failures retry
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(path, "w") as f:
            json.dump([[b.timestamp.isoformat(), b.open, b.high, b.low, b.close, b.volume] for b in bars], f)
    _bar_cache[ticker] = bars
    return bars


def fetch_hourly_bars(ticker: str, start: datetime, end: datetime) -> list[Bar]:
    """Hourly OHLCV bars within [start, end], UTC-naive. Served from a per-ticker disk
    cache so backtests are reproducible across runs."""
    return [b for b in _wide_bars(ticker) if start <= b.timestamp <= end]


# ── Exit policy + simulator (mirrors Engine._update_exits) ───────────────────

@dataclass(frozen=True)
class ExitPolicy:
    name: str
    trail_activation_pct: float
    trail_distance_pct: float
    honor_tp: bool = True               # honor the trade's recorded take-profit
    stop_pct_override: float | None = None  # replace the recorded stop distance


@dataclass
class ExitResult:
    exit_price: float
    reason: str
    return_pct: float
    bars_held: int


def simulate_exit(entry: Entry, bars: list[Bar], policy: ExitPolicy) -> ExitResult | None:
    """Replay one long trade's exit under `policy`. Returns None if no bars."""
    after = [b for b in bars if b.timestamp >= entry.entry_time]
    if not after:
        return None
    px = entry.entry_price

    if policy.stop_pct_override is not None:
        stop_price = px * (1 - policy.stop_pct_override / 100)
    else:
        stop_price = entry.stop_price if entry.stop_price > 0 else px * 0.96
    tp_price = entry.tp_price if (policy.honor_tp and entry.tp_price > 0) else 0.0

    highest = px
    trailing_active = False
    trailing_stop = 0.0

    for i, bar in enumerate(after):
        cur = bar.close
        peak = max(bar.high, cur)
        if peak > highest:
            highest = peak
        profit_pct = (cur - px) / px * 100

        if not trailing_active and profit_pct >= policy.trail_activation_pct:
            trailing_active = True
            trailing_stop = highest * (1 - policy.trail_distance_pct / 100)
        elif trailing_active:
            trailing_stop = max(trailing_stop, highest * (1 - policy.trail_distance_pct / 100))

        # Priority: stop -> trailing -> take-profit (same as production).
        if bar.low <= stop_price:
            return ExitResult(stop_price, "stop_loss", (stop_price - px) / px * 100, i + 1)
        if trailing_active and bar.low <= trailing_stop:
            return ExitResult(trailing_stop, "trailing", (trailing_stop - px) / px * 100, i + 1)
        if tp_price > 0 and bar.high >= tp_price:
            return ExitResult(tp_price, "take_profit", (tp_price - px) / px * 100, i + 1)

    last = after[-1].close
    return ExitResult(last, "window_end", (last - px) / px * 100, len(after))


# ── Aggregation ──────────────────────────────────────────────────────────────

@dataclass
class Agg:
    label: str
    n: int
    win_pct: float
    avg_win_pct: float
    avg_loss_pct: float
    rr: float            # avg_win / |avg_loss|  (realized reward:risk)
    expectancy_pct: float
    profit_factor: float


def aggregate(label: str, returns: list[float]) -> Agg:
    if not returns:
        return Agg(label, 0, 0, 0, 0, 0, 0, 0)
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r <= 0]
    avg_win = statistics.mean(wins) if wins else 0.0
    avg_loss = statistics.mean(losses) if losses else 0.0
    win_pct = len(wins) / len(returns) * 100
    gross_win = sum(wins)
    gross_loss = -sum(losses)
    pf = (gross_win / gross_loss) if gross_loss > 0 else float("inf")
    rr = (avg_win / abs(avg_loss)) if avg_loss != 0 else float("inf")
    expectancy = statistics.mean(returns)
    return Agg(label, len(returns), win_pct, avg_win, avg_loss, rr, expectancy, pf)


POLICIES = [
    ExitPolicy("baseline (live: act2.0/trail1.5)", 2.0, 1.5),
    ExitPolicy("trail wider (act2.0/trail3.0)", 2.0, 3.0),
    ExitPolicy("later+wider (act3.0/trail2.5)", 3.0, 2.5),
    ExitPolicy("ride trend (act3.0/trail4.0)", 3.0, 4.0),
    ExitPolicy("trail-only no-TP (act2.0/trail3.0)", 2.0, 3.0, honor_tp=False),
    ExitPolicy("trail-only wide (act3.0/trail4.0)", 3.0, 4.0, honor_tp=False),
    ExitPolicy("tighter stop 3% (act2.0/trail3.0)", 2.0, 3.0, honor_tp=False, stop_pct_override=3.0),
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portfolio", default="main")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    entries = load_entries(args.portfolio, args.limit)
    print(f"Loaded {len(entries)} closed long entries from portfolio={args.portfolio}\n")

    # Fetch bars once per trade (cached per ticker), build per-trade bar slices.
    sims: dict[str, list[float]] = {p.name: [] for p in POLICIES}
    actual_returns: list[float] = []
    covered = 0
    no_bars = 0
    for e in entries:
        bars = fetch_hourly_bars(e.ticker, e.entry_time, e.entry_time + timedelta(days=30))
        slice_after = [b for b in bars if b.timestamp >= e.entry_time]
        if not slice_after:
            no_bars += 1
            continue
        covered += 1
        if e.actual_return_pct is not None:
            actual_returns.append(e.actual_return_pct)
        for p in POLICIES:
            res = simulate_exit(e, bars, p)
            if res is not None:
                sims[p.name].append(res.return_pct)

    print(f"Bar coverage: {covered}/{len(entries)} trades had hourly bars "
          f"({no_bars} missing)\n")

    rows = [aggregate("ACTUAL (live results)", actual_returns)]
    rows += [aggregate(p.name, sims[p.name]) for p in POLICIES]

    hdr = f"{'policy':<38}{'n':>4}{'win%':>7}{'avgW%':>7}{'avgL%':>7}{'R:R':>6}{'exp%':>7}{'PF':>6}"
    print(hdr)
    print("-" * len(hdr))
    for a in rows:
        rr = "inf" if a.rr == float("inf") else f"{a.rr:.2f}"
        pf = "inf" if a.profit_factor == float("inf") else f"{a.profit_factor:.2f}"
        print(f"{a.label:<38}{a.n:>4}{a.win_pct:>7.1f}{a.avg_win_pct:>7.2f}"
              f"{a.avg_loss_pct:>7.2f}{rr:>6}{a.expectancy_pct:>7.2f}{pf:>6}")


if __name__ == "__main__":
    main()
