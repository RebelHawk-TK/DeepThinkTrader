"""Walk-forward runner tests — window splitting + end-to-end run."""
from __future__ import annotations

from datetime import datetime, timedelta

from backtest.strategies import BuyAndHoldStrategy
from backtest.walk_forward import build_windows, run_walk_forward, summarize_windows
from brokers.base import Bar


def _series(ticker: str, n: int) -> list[Bar]:
    t = datetime(2024, 1, 2)
    bars = []
    for i in range(n):
        px = 100.0 + i * 0.5
        bars.append(Bar(ticker=ticker, timestamp=t + timedelta(days=i),
                        open=px, high=px * 1.01, low=px * 0.99, close=px, volume=1_000_000))
    return bars


def test_build_windows_rolls_forward_by_oos_step():
    bars = _series("NVDA", 100)
    pairs = build_windows(bars, is_days=60, oos_days=20)
    # (100 - 60 - 20) / 20 + 1 = 2 windows
    assert len(pairs) == 2
    assert len(pairs[0][0]) == 60 and len(pairs[0][1]) == 20
    # Second window starts 20 bars later.
    assert pairs[1][0][0].timestamp == bars[20].timestamp


def test_build_windows_empty_when_history_too_short():
    bars = _series("NVDA", 50)
    assert build_windows(bars, is_days=60, oos_days=20) == []


def test_run_walk_forward_produces_window_metrics():
    bars = _series("NVDA", 120)
    windows = run_walk_forward(
        strategy_factory=BuyAndHoldStrategy,
        ticker="NVDA", bars=bars,
        is_days=60, oos_days=20,
    )
    # Window math: start can be 0, 20, 40 → 3 windows fit before (start + 60 + 20 > 120).
    assert len(windows) == 3
    # Each window has a fresh strategy instance → no state bleed between IS/OOS.
    for w in windows:
        assert w.result_is.num_trades <= 1  # buy-and-hold enters once per run
        assert w.result_oos.num_trades <= 1


def test_summarize_windows_handles_empty():
    out = summarize_windows([])
    assert "No walk-forward windows" in out


def test_summarize_windows_formats_rows():
    bars = _series("NVDA", 200)
    windows = run_walk_forward(
        strategy_factory=BuyAndHoldStrategy, ticker="NVDA",
        bars=bars, is_days=60, oos_days=20,
    )
    out = summarize_windows(windows)
    assert "IS Sharpe" in out
    assert "aggregate OOS" in out
