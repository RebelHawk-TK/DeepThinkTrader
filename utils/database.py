from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from config import Config


class Database:
    def __init__(self, db_path: str = Config.DB_PATH):
        self.db_path = db_path
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        with self._get_conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS research_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    news_impact_score REAL,
                    reddit_sentiment_score REAL,
                    combined_catalyst_score REAL,
                    report_json TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS analysis_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    conviction REAL NOT NULL,
                    position_size_pct REAL,
                    stop_loss_pct REAL,
                    take_profit_pct REAL,
                    reasoning TEXT,
                    analysis_json TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    action TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    entry_price REAL,
                    stop_loss_price REAL,
                    take_profit_price REAL,
                    conviction REAL,
                    status TEXT DEFAULT 'OPEN',
                    exit_price REAL,
                    exit_timestamp TEXT,
                    pnl REAL,
                    order_id TEXT,
                    reasoning TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_pnl (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    realized_pnl REAL DEFAULT 0,
                    unrealized_pnl REAL DEFAULT 0,
                    trades_taken INTEGER DEFAULT 0,
                    trades_won INTEGER DEFAULT 0,
                    trades_lost INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alpaca_request_ids (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    method TEXT NOT NULL,
                    ticker TEXT,
                    order_id TEXT,
                    http_status INTEGER,
                    success INTEGER DEFAULT 1
                )
            """)

    def save_research(self, ticker: str, report: dict) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO research_reports
                   (ticker, timestamp, news_impact_score, reddit_sentiment_score,
                    combined_catalyst_score, report_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    ticker,
                    datetime.now().isoformat(),
                    report.get("news_impact_score", 0),
                    report.get("reddit_sentiment_score", 0),
                    report.get("combined_catalyst_score", 0),
                    json.dumps(report),
                ),
            )
            return cursor.lastrowid

    def save_analysis(self, analysis: dict) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO analysis_results
                   (ticker, timestamp, action, conviction, position_size_pct,
                    stop_loss_pct, take_profit_pct, reasoning, analysis_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    analysis["ticker"],
                    datetime.now().isoformat(),
                    analysis["action"],
                    analysis["conviction"],
                    analysis.get("position_size_pct", 0),
                    analysis.get("stop_loss_pct", 0),
                    analysis.get("take_profit_pct", 0),
                    analysis.get("reasoning_summary", ""),
                    json.dumps(analysis),
                ),
            )
            return cursor.lastrowid

    def save_trade(self, trade: dict) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO trades
                   (ticker, timestamp, action, quantity, entry_price,
                    stop_loss_price, take_profit_price, conviction, order_id, reasoning)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    trade["ticker"],
                    datetime.now().isoformat(),
                    trade["action"],
                    trade["quantity"],
                    trade.get("entry_price"),
                    trade.get("stop_loss_price"),
                    trade.get("take_profit_price"),
                    trade.get("conviction"),
                    trade.get("order_id"),
                    trade.get("reasoning"),
                ),
            )
            return cursor.lastrowid

    def get_open_trades(self) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades WHERE status = 'OPEN'"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_today_pnl(self) -> dict:
        today = datetime.now().strftime("%Y-%m-%d")
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM daily_pnl WHERE date = ?", (today,)
            ).fetchone()
            if row:
                return dict(row)
            return {"date": today, "realized_pnl": 0, "trades_taken": 0}

    def update_daily_pnl(self, pnl: float, won: bool) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT * FROM daily_pnl WHERE date = ?", (today,)
            ).fetchone()
            if existing:
                conn.execute(
                    """UPDATE daily_pnl SET
                       realized_pnl = realized_pnl + ?,
                       trades_taken = trades_taken + 1,
                       trades_won = trades_won + ?,
                       trades_lost = trades_lost + ?
                       WHERE date = ?""",
                    (pnl, 1 if won else 0, 0 if won else 1, today),
                )
            else:
                conn.execute(
                    """INSERT INTO daily_pnl (date, realized_pnl, trades_taken, trades_won, trades_lost)
                       VALUES (?, ?, 1, ?, ?)""",
                    (today, pnl, 1 if won else 0, 0 if won else 1),
                )

    def get_recent_trades(self, limit: int = 50) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_recent_analyses(self, limit: int = 20, unique: bool = True) -> list[dict]:
        with self._get_conn() as conn:
            if unique:
                # Only the latest analysis per ticker
                rows = conn.execute(
                    """SELECT * FROM analysis_results
                       WHERE id IN (
                           SELECT MAX(id) FROM analysis_results GROUP BY ticker
                       )
                       ORDER BY timestamp DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM analysis_results ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]

    def was_recently_analyzed(self, ticker: str, minutes: int = 55) -> bool:
        """Check if ticker was analyzed within the last N minutes."""
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT timestamp FROM analysis_results
                   WHERE ticker = ? ORDER BY timestamp DESC LIMIT 1""",
                (ticker,),
            ).fetchone()
            if not row:
                return False
            last = datetime.fromisoformat(row["timestamp"])
            return (datetime.now() - last).total_seconds() < minutes * 60

    def save_request_id(
        self,
        request_id: str,
        endpoint: str,
        method: str = "POST",
        ticker: str | None = None,
        order_id: str | None = None,
        http_status: int | None = None,
        success: bool = True,
    ) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO alpaca_request_ids
                   (timestamp, request_id, endpoint, method, ticker, order_id, http_status, success)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    datetime.now().isoformat(),
                    request_id,
                    endpoint,
                    method,
                    ticker,
                    order_id,
                    http_status,
                    1 if success else 0,
                ),
            )
            return cursor.lastrowid

    def get_recent_request_ids(self, limit: int = 50) -> list[dict]:
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM alpaca_request_ids ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def close_trade(self, trade_id: int, exit_price: float, pnl: float) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE trades SET status = 'CLOSED', exit_price = ?,
                   exit_timestamp = ?, pnl = ? WHERE id = ?""",
                (exit_price, datetime.now().isoformat(), pnl, trade_id),
            )
