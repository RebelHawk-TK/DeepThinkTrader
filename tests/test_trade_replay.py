"""Tests for the exit-policy replay simulator (backtest/trade_replay.py).

These pin the exit-priority semantics (stop -> trailing -> take-profit, using
each bar's low/high) so the simulator stays consistent with production
(Engine._update_exits) and the policy comparison can be trusted.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from brokers.base import Bar
from backtest.trade_replay import Entry, ExitPolicy, simulate_exit

T0 = datetime(2026, 4, 1, 14, 0)


def _bars(rows: list[tuple[float, float, float]]) -> list[Bar]:
    """rows = [(low, high, close), ...] -> hourly bars."""
    return [
        Bar(ticker="T", timestamp=T0 + timedelta(hours=i),
            open=cl, high=hi, low=lo, close=cl, volume=1000)
        for i, (lo, hi, cl) in enumerate(rows)
    ]


def _entry(px: float = 100.0, stop: float = 96.0, tp: float = 110.0) -> Entry:
    return Entry(1, "T", T0, px, stop, tp, None, None, None)


def test_stop_loss_fires_at_stop_price():
    bars = _bars([(100, 101, 100), (94, 97, 95)])  # bar2 low 94 <= stop 96
    r = simulate_exit(_entry(), bars, ExitPolicy("p", 2.0, 1.5))
    assert r is not None and r.reason == "stop_loss"
    assert abs(r.exit_price - 96.0) < 1e-6


def test_take_profit_fires_when_trail_not_triggered():
    # tight-range bar: +2.6% activates trail but low stays above it; high hits TP
    bars = _bars([(102, 103, 102.6)])
    r = simulate_exit(_entry(tp=102.5), bars, ExitPolicy("p", 2.0, 1.5))
    assert r is not None and r.reason == "take_profit"
    assert abs(r.exit_price - 102.5) < 1e-6


def test_wider_trail_captures_more_than_tight():
    # b1 pulls back enough to stop a 1.5% trail but not a 4% trail; price then rises
    bars = _bars([(100, 103, 103), (104, 108, 108), (100, 105, 101)])
    tight = simulate_exit(_entry(tp=200), bars, ExitPolicy("tight", 2.0, 1.5))
    wide = simulate_exit(_entry(tp=200), bars, ExitPolicy("wide", 2.0, 4.0))
    assert tight is not None and wide is not None
    assert tight.reason == "trailing"
    assert wide.return_pct > tight.return_pct


def test_no_bars_after_entry_returns_none():
    bars = _bars([(100, 101, 100)])
    late = Entry(1, "T", datetime(2027, 1, 1), 100, 96, 110, None, None, None)
    assert simulate_exit(late, bars, ExitPolicy("p", 2.0, 1.5)) is None


def test_parse_ts_localizes_naive_db_timestamps_to_utc():
    """DB timestamps are naive local Eastern (datetime.now().isoformat()); bars
    are naive UTC. _parse_ts must shift naive input ET -> UTC or every next-bar
    entry is backdated ~4-5h (the 2026-06-09 look-ahead bug)."""
    from backtest.trade_replay import _parse_ts

    # EDT (UTC-4): a 14:00 ET report is 18:00 UTC
    assert _parse_ts("2026-06-09T14:00:00.123456") == datetime(2026, 6, 9, 18, 0, 0, 123456)
    # EST (UTC-5): winter timestamps shift by 5
    assert _parse_ts("2026-01-15T14:00:00") == datetime(2026, 1, 15, 19, 0)
    # Already-aware input still normalizes to naive UTC
    assert _parse_ts("2026-06-09T18:00:00+00:00") == datetime(2026, 6, 9, 18, 0)
    assert _parse_ts("2026-06-09T14:00:00-04:00") == datetime(2026, 6, 9, 18, 0)
