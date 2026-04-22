"""Dashboard data-builder tests. Logic is pure — no Streamlit required."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from utils.dashboard_data import (
    compute_30day_pnl,
    compute_alerts,
    compute_bot_status,
    compute_drawdown_from_peak,
    compute_kelly_state,
    compute_market_state,
    compute_recent_reflections,
    compute_today_pnl,
    compute_total_exposure_pct,
)


# ─────────────────────────── Bot status ──────────────────────────────────


def test_bot_status_fresh_log_is_ok(tmp_path):
    log = tmp_path / "deep.log"
    log.write_text("fresh\n")
    status, detail = compute_bot_status(str(log))
    assert status == "ok"
    assert "last log" in detail


def test_bot_status_stale_log_is_warning(tmp_path):
    import os
    log = tmp_path / "deep.log"
    log.write_text("stale\n")
    # Backdate the log by 10 min.
    ten_min_ago = datetime.now().timestamp() - 600
    os.utime(str(log), (ten_min_ago, ten_min_ago))
    status, _ = compute_bot_status(str(log))
    assert status == "warning"


def test_bot_status_very_stale_log_is_down(tmp_path):
    import os
    log = tmp_path / "deep.log"
    log.write_text("dead\n")
    one_hour_ago = datetime.now().timestamp() - 3600
    os.utime(str(log), (one_hour_ago, one_hour_ago))
    status, _ = compute_bot_status(str(log))
    assert status == "down"


def test_bot_status_missing_log_is_warning(tmp_path):
    status, detail = compute_bot_status(str(tmp_path / "nope.log"))
    assert status == "warning"
    assert "log not found" in detail


# ─────────────────────────── Market state ───────────────────────────────


def test_market_state_open_with_countdown():
    clock = MagicMock()
    clock.get_status.return_value = {"is_open": True, "minutes_to_close": 135}
    label, is_open = compute_market_state(clock)
    assert is_open
    assert "OPEN" in label
    assert "2h 15m" in label


def test_market_state_closed_uses_minutes_to_open():
    clock = MagicMock()
    clock.get_status.return_value = {"is_open": False, "minutes_to_open": 90}
    label, is_open = compute_market_state(clock)
    assert not is_open
    assert "CLOSED" in label
    assert "1h 30m" in label


def test_market_state_broken_clock_falls_back_safely():
    clock = MagicMock()
    clock.get_status.side_effect = RuntimeError("network")
    label, is_open = compute_market_state(clock)
    assert label == "CLOSED"
    assert not is_open


# ─────────────────────────── Alerts ─────────────────────────────────────


def test_alerts_empty_when_healthy():
    assert compute_alerts(
        paused_portfolios=set(), drawdown_pct=1.0, drawdown_halt_pct=8.0,
        consecutive_losses=0, circuit_breaker_active=False,
    ) == []


def test_alerts_flag_near_drawdown_halt():
    alerts = compute_alerts(
        paused_portfolios=set(), drawdown_pct=7.0, drawdown_halt_pct=8.0,
        consecutive_losses=0, circuit_breaker_active=False,
    )
    assert any("Drawdown" in a for a in alerts)


def test_alerts_flag_revenge_trading():
    alerts = compute_alerts(
        paused_portfolios=set(), drawdown_pct=0, drawdown_halt_pct=8.0,
        consecutive_losses=3, circuit_breaker_active=False,
    )
    assert any("consecutive" in a.lower() for a in alerts)


def test_alerts_combine_all_sources():
    alerts = compute_alerts(
        paused_portfolios={"penny"}, drawdown_pct=7.5, drawdown_halt_pct=8.0,
        consecutive_losses=4, circuit_breaker_active=True,
    )
    # 4 distinct alerts: breaker, drawdown, revenge, paused.
    assert len(alerts) == 4


# ─────────────────────────── 30-day P&L ─────────────────────────────────


def test_30day_pnl_empty_hist_returns_zeros():
    assert compute_30day_pnl(None) == (0.0, 0.0)
    assert compute_30day_pnl({"equity": [], "timestamp": []}) == (0.0, 0.0)


def test_30day_pnl_uses_equity_endpoints():
    # Simple: start at 100k 30 days ago, end at 110k today → +10k (+10%)
    thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).timestamp()
    pnl, pct = compute_30day_pnl({
        "equity": [100_000, 110_000],
        "timestamp": [int(thirty_days_ago), int(yesterday)],
    })
    assert abs(pnl - 10_000) < 1
    assert 9.9 < pct < 10.1


def test_30day_pnl_falls_back_to_earliest_if_no_30d_data():
    """History shorter than 30d still produces something sensible."""
    five_days_ago = (datetime.now(timezone.utc) - timedelta(days=5)).timestamp()
    pnl, pct = compute_30day_pnl({
        "equity": [100_000, 105_000],
        "timestamp": [int(five_days_ago) - 86400, int(five_days_ago)],
    })
    assert abs(pnl - 5_000) < 1


def test_30day_pnl_current_equity_override_reflects_intraday():
    """Alpaca's daily timeframe freezes at yesterday's close during market
    hours. Passing live `current_equity` must use it as the endpoint."""
    thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).timestamp()
    hist = {
        "equity": [100_000, 105_000],  # yesterday's close = 105k
        "timestamp": [int(thirty_days_ago), int(yesterday)],
    }
    # Without override: uses 105k → +5k.
    pnl_stale, _ = compute_30day_pnl(hist)
    # With override at 107k: should show +7k instead.
    pnl_live, _ = compute_30day_pnl(hist, current_equity=107_000)
    assert abs(pnl_stale - 5_000) < 1
    assert abs(pnl_live - 7_000) < 1


# ─────────────────────────── Today's P&L (Alpaca last_equity) ───────────


def test_today_pnl_uses_last_equity():
    """Alpaca returns both equity (now) and last_equity (yesterday's close).
    Today's P&L is the difference — no DB lookups, no portfolio_history."""
    pnl, pct = compute_today_pnl({"equity": "101000", "last_equity": "100000"})
    assert abs(pnl - 1_000) < 0.01
    assert 0.99 < pct < 1.01


def test_today_pnl_negative_today():
    pnl, pct = compute_today_pnl({"equity": "99250", "last_equity": "100000"})
    assert abs(pnl - (-750)) < 0.01
    assert -0.76 < pct < -0.74


def test_today_pnl_missing_account_is_zero():
    assert compute_today_pnl(None) == (0.0, 0.0)
    assert compute_today_pnl({}) == (0.0, 0.0)


def test_today_pnl_invalid_values_dont_crash():
    assert compute_today_pnl({"equity": "bad", "last_equity": "100000"}) == (0.0, 0.0)
    assert compute_today_pnl({"equity": "100000", "last_equity": "0"}) == (0.0, 0.0)


# ─────────────────────────── Exposure ───────────────────────────────────


def test_total_exposure_pct():
    positions = [{"market_value": 10_000}, {"market_value": 5_000}]
    assert compute_total_exposure_pct(positions, equity=100_000) == 15.0
    assert compute_total_exposure_pct([], equity=100_000) == 0.0
    assert compute_total_exposure_pct(positions, equity=0) == 0.0


# ─────────────────────────── Drawdown from peak ─────────────────────────


def test_drawdown_from_peak():
    hist = {"equity": [100, 110, 120, 108], "timestamp": [1, 2, 3, 4]}
    dd = compute_drawdown_from_peak(hist)
    # Peak 120, current 108 → 10% drawdown.
    assert 9.9 < dd < 10.1


def test_drawdown_zero_at_all_time_high():
    hist = {"equity": [100, 110, 120], "timestamp": [1, 2, 3]}
    assert compute_drawdown_from_peak(hist) == 0.0


def test_drawdown_empty_hist_is_zero():
    assert compute_drawdown_from_peak(None) == 0.0
    assert compute_drawdown_from_peak({"equity": [], "timestamp": []}) == 0.0


# ─────────────────────────── Kelly state ────────────────────────────────


def test_kelly_state_insufficient_history(db, risk_manager, test_user_id):
    # Fresh DB → 0 trades, no Kelly.
    s = compute_kelly_state(db, risk_manager, test_user_id)
    assert s["fraction"] is None
    assert s["n_trades"] == 0


def test_kelly_state_with_enough_history(db, risk_manager, test_user_id):
    # Seed 25 closed trades, mixed outcomes.
    for i in range(25):
        tid = db.save_trade(test_user_id, {
            "ticker": f"T{i}", "action": "BUY", "quantity": 1,
            "entry_price": 100.0, "stop_loss_price": 95.0,
            "take_profit_price": 110.0, "conviction": 7.0,
            "order_id": f"o{i}",
        })
        db.close_trade(tid, exit_price=105.0 if i % 2 == 0 else 98.0,
                       pnl=5.0 if i % 2 == 0 else -5.0, exit_reason="test")
    s = compute_kelly_state(db, risk_manager, test_user_id)
    assert s["n_trades"] >= 20
    # With ~50% win rate, the Kelly fraction may fall to the 0.5% floor.
    assert s["fraction"] is not None


# ─────────────────────────── Reflections ────────────────────────────────


def test_recent_reflections_empty_db(db, test_user_id):
    assert compute_recent_reflections(db, test_user_id) == []


def test_recent_reflections_returns_most_recent(db, test_user_id):
    tid = db.save_trade(test_user_id, {
        "ticker": "NVDA", "action": "BUY", "quantity": 10,
        "entry_price": 100.0, "stop_loss_price": 95.0,
        "take_profit_price": 110.0, "conviction": 7.0, "order_id": "o1",
    })
    for i in range(5):
        db.save_reflection(
            user_id=test_user_id, trade_id=tid, ticker="NVDA", thesis="test",
            outcome_pnl=10.0 * (1 if i % 2 == 0 else -1),
            lesson=f"lesson {i}",
        )
    rows = compute_recent_reflections(db, test_user_id, limit=3)
    assert len(rows) == 3
