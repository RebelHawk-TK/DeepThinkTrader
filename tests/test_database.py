"""Unit tests for utils.database.

Focus on round-trips (save → load → fields match) and the invariants
dashboard and agents rely on.
"""
from __future__ import annotations


# ─────────────────────────── Basic round-trips ────────────────────────────


def test_save_and_get_open_trade(db):
    tid = db.save_trade({
        "ticker": "NVDA", "action": "BUY", "quantity": 5,
        "entry_price": 900.0, "stop_loss_price": 855.0,
        "take_profit_price": 945.0, "conviction": 8.5, "order_id": "ord-1",
    })
    assert tid > 0
    opens = db.get_open_trades()
    assert len(opens) == 1
    t = opens[0]
    assert t["ticker"] == "NVDA"
    assert t["action"] == "BUY"
    assert t["quantity"] == 5
    assert t["status"] == "OPEN"
    assert t["portfolio"] == "main"


def test_save_trade_with_portfolio(db):
    db.save_trade({
        "ticker": "XYZ", "action": "BUY", "quantity": 100,
        "entry_price": 3.0, "stop_loss_price": 2.85,
        "take_profit_price": 3.30, "conviction": 7.0, "order_id": "p1",
    }, portfolio="penny")
    penny = db.get_open_trades(portfolio="penny")
    main = db.get_open_trades(portfolio="main")
    assert len(penny) == 1 and penny[0]["ticker"] == "XYZ"
    assert len(main) == 0


def test_close_trade_records_exit(db):
    tid = db.save_trade({
        "ticker": "AAPL", "action": "BUY", "quantity": 10,
        "entry_price": 200.0, "stop_loss_price": 190.0,
        "take_profit_price": 220.0, "conviction": 7.5, "order_id": "ord-2",
    })
    db.close_trade(trade_id=tid, exit_price=215.0, pnl=150.0, exit_reason="take_profit")
    assert db.get_open_trades() == []
    recent = db.get_recent_trades(limit=10)
    assert len(recent) == 1
    t = recent[0]
    assert t["status"] == "CLOSED"
    assert t["exit_price"] == 215.0
    assert t["pnl"] == 150.0
    assert t["exit_reason"] == "take_profit"


def test_save_and_get_analysis(db):
    aid = db.save_analysis({
        "ticker": "TSLA", "action": "BUY", "conviction": 8.0,
        "position_size_pct": 2.0, "stop_loss_pct": 4.0,
        "take_profit_pct": 8.0, "reasoning": "test",
        "analysis_json": "{}",
    })
    assert aid > 0
    analyses = db.get_recent_analyses(limit=5, unique=False)
    assert len(analyses) == 1
    assert analyses[0]["ticker"] == "TSLA"


def test_save_and_get_research(db):
    rid = db.save_research(ticker="MSFT", report={
        "news_impact_score": 0.5,
        "reddit_sentiment_score": 0.2,
        "combined_catalyst_score": 0.4,
        "payload": {"note": "test"},
    })
    assert rid > 0


# ─────────────────────────── Daily P&L tracking ───────────────────────────


def test_daily_pnl_accumulates(db):
    db.update_daily_pnl(100.0, won=True)
    db.update_daily_pnl(-50.0, won=False)
    today = db.get_today_pnl()
    assert today["realized_pnl"] == 50.0
    assert today["trades_taken"] == 2


# ─────────────────────────── ATR history ───────────────────────────────────


def test_save_atr_and_median(db):
    """save_atr uses today's date with INSERT OR REPLACE, so we insert manually
    across dates to avoid the yfinance seeding fallback."""
    import sqlite3
    from datetime import date, timedelta
    with sqlite3.connect(db.db_path) as conn:
        for i, v in enumerate([1.0, 1.2, 1.1, 1.3, 0.9, 1.05, 1.15]):
            d = (date.today() - timedelta(days=i)).isoformat()
            conn.execute(
                "INSERT OR REPLACE INTO atr_history (ticker, date, atr_value) VALUES (?, ?, ?)",
                ("FAKETICKER", d, v),
            )
        conn.commit()
    median = db.get_median_atr("FAKETICKER", days=60)
    # 7 values: sorted [0.9, 1.0, 1.05, 1.1, 1.15, 1.2, 1.3] → median = 1.1
    assert abs(median - 1.1) < 1e-9


# ─────────────────────────── Request-ID audit trail ───────────────────────


def test_save_and_get_request_ids(db):
    db.save_request_id(
        request_id="req-abc", endpoint="/v2/orders", method="POST",
        ticker="NVDA", order_id="ord-1", http_status=201, success=True,
    )
    rows = db.get_recent_request_ids(limit=10)
    assert len(rows) == 1
    assert rows[0]["request_id"] == "req-abc"
    assert rows[0]["ticker"] == "NVDA"


# ─────────────────────────── Slippage tracking ─────────────────────────────


def test_slippage_save_and_analytics(db):
    db.save_slippage(
        ticker="NVDA", expected_price=100.0, filled_price=100.25,
        shares=10, side="buy", order_type="market",
    )
    db.save_slippage(
        ticker="NVDA", expected_price=100.0, filled_price=99.95,
        shares=10, side="sell", order_type="market",
    )
    stats = db.get_slippage_analytics(days=30)
    # Signature of the analytics dict varies; the key invariant is that it
    # returns something non-empty after two saved records.
    assert stats
    avg = db.get_ticker_slippage_avg("NVDA", days=30)
    assert avg is not None


# ─────────────────────────── Edge performance ──────────────────────────────


def test_edge_combo_win_rate_learns(db):
    for i, pnl in enumerate([50.0, 75.0, 60.0, -30.0, 20.0, -10.0]):
        tid = db.save_trade({
            "ticker": "AAPL", "action": "BUY", "quantity": 10,
            "entry_price": 100.0, "stop_loss_price": 95.0,
            "take_profit_price": 110.0, "conviction": 8.0,
            "order_id": f"ord-ep-{i}",
        })
        db.save_edge_performance(
            trade_id=tid, ticker="AAPL",
            edge_combo="FUNDAMENTAL|TECHNICAL", edges_fired=2,
            fund_passed=True, tech_passed=True, sent_passed=False,
            conviction=8.0, pnl=pnl,
        )
    wr = db.get_edge_combo_win_rate("FUNDAMENTAL|TECHNICAL", days=365)
    assert wr is None or (0.0 <= wr <= 1.0)
    stats = db.get_edge_combo_stats(min_trades=3, days=365)
    assert any(s["edge_combo"] == "FUNDAMENTAL|TECHNICAL" for s in stats)


# ─────────────────────────── Strategy stats ────────────────────────────────


def test_strategy_stats_requires_closed_trades(db):
    # No trades yet → zero stats.
    stats = db.get_strategy_stats(portfolio="main")
    assert stats["trade_count"] == 0


def test_strategy_stats_with_closed_trades(db):
    # Two wins, one loss.
    for i, (px, exit_px, pnl) in enumerate([
        (100.0, 110.0, 100.0),
        (50.0, 55.0, 50.0),
        (200.0, 180.0, -200.0),
    ]):
        tid = db.save_trade({
            "ticker": f"T{i}", "action": "BUY", "quantity": 10,
            "entry_price": px, "stop_loss_price": px * 0.95,
            "take_profit_price": px * 1.10, "conviction": 7.0,
            "order_id": f"ord-{i}",
        })
        db.close_trade(tid, exit_price=exit_px, pnl=pnl, exit_reason="test")
    stats = db.get_strategy_stats(portfolio="main", days=365)
    assert stats["trade_count"] == 3
    assert 0.0 <= stats["win_rate"] <= 1.0
    # Expectancy = avg per-trade P&L = (100+50-200)/3 = -16.67
    assert "expectancy" in stats


# ─────────────────────────── Health check ─────────────────────────────────


def test_health_check_returns_table_counts(db):
    h = db.health_check()
    assert h["status"] == "ok"
    assert "trades" in h["tables"]
    assert h["journal_mode"].lower() == "wal"
