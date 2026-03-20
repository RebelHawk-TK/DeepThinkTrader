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
                    report_json TEXT NOT NULL,
                    portfolio TEXT DEFAULT 'main'
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
                    analysis_json TEXT NOT NULL,
                    portfolio TEXT DEFAULT 'main'
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
                    reasoning TEXT,
                    portfolio TEXT DEFAULT 'main'
                )
            """)
            # Migrate existing tables: add portfolio column if missing
            self._migrate_add_portfolio(conn)
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
            # Run additional migrations
            self._migrate_trailing_stops(conn)
            self._init_partial_exits_table(conn)
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

    def _migrate_add_portfolio(self, conn: sqlite3.Connection) -> None:
        """Add portfolio column to existing tables if not present."""
        for table in ("trades", "research_reports", "analysis_results"):
            cols = [row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if "portfolio" not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN portfolio TEXT DEFAULT 'main'")

    def _migrate_trailing_stops(self, conn: sqlite3.Connection) -> None:
        """Add trailing stop and scale-out columns to trades table."""
        cols = [row[1] for row in conn.execute("PRAGMA table_info(trades)").fetchall()]
        migrations = {
            "trailing_stop_price": "REAL",
            "highest_price": "REAL",
            "trailing_stop_active": "INTEGER DEFAULT 0",
            "original_quantity": "INTEGER",
            "exit_reason": "TEXT",
            "edges_fired": "INTEGER",
            "edge_details": "TEXT",
            "risk_amount": "REAL",
        }
        for col, col_type in migrations.items():
            if col not in cols:
                conn.execute(f"ALTER TABLE trades ADD COLUMN {col} {col_type}")

    def _init_partial_exits_table(self, conn: sqlite3.Connection) -> None:
        """Create partial_exits table for scale-out tracking."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS partial_exits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                exit_price REAL NOT NULL,
                pnl REAL,
                reason TEXT,
                order_id TEXT,
                FOREIGN KEY (trade_id) REFERENCES trades(id)
            )
        """)

    def save_research(self, ticker: str, report: dict, portfolio: str = "main") -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO research_reports
                   (ticker, timestamp, news_impact_score, reddit_sentiment_score,
                    combined_catalyst_score, report_json, portfolio)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    ticker,
                    datetime.now().isoformat(),
                    report.get("news_impact_score", 0),
                    report.get("reddit_sentiment_score", 0),
                    report.get("combined_catalyst_score", 0),
                    json.dumps(report),
                    portfolio,
                ),
            )
            return cursor.lastrowid

    def save_analysis(self, analysis: dict, portfolio: str = "main") -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO analysis_results
                   (ticker, timestamp, action, conviction, position_size_pct,
                    stop_loss_pct, take_profit_pct, reasoning, analysis_json, portfolio)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    portfolio,
                ),
            )
            return cursor.lastrowid

    def save_trade(self, trade: dict, portfolio: str = "main") -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO trades
                   (ticker, timestamp, action, quantity, entry_price,
                    stop_loss_price, take_profit_price, conviction, order_id, reasoning, portfolio)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    portfolio,
                ),
            )
            return cursor.lastrowid

    def get_open_trades(self, portfolio: str | None = None) -> list[dict]:
        with self._get_conn() as conn:
            if portfolio:
                rows = conn.execute(
                    "SELECT * FROM trades WHERE status = 'OPEN' AND portfolio = ?",
                    (portfolio,),
                ).fetchall()
            else:
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

    def get_recent_trades(self, limit: int = 50, portfolio: str | None = None) -> list[dict]:
        with self._get_conn() as conn:
            if portfolio:
                rows = conn.execute(
                    "SELECT * FROM trades WHERE portfolio = ? ORDER BY timestamp DESC LIMIT ?",
                    (portfolio, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
                ).fetchall()
            return [dict(r) for r in rows]

    def get_recent_analyses(self, limit: int = 20, unique: bool = True, portfolio: str | None = None) -> list[dict]:
        with self._get_conn() as conn:
            pf_clause = "AND portfolio = ?" if portfolio else ""
            pf_params: tuple = (portfolio,) if portfolio else ()
            if unique:
                rows = conn.execute(
                    f"""SELECT * FROM analysis_results
                       WHERE id IN (
                           SELECT MAX(id) FROM analysis_results WHERE 1=1 {pf_clause} GROUP BY ticker
                       )
                       ORDER BY timestamp DESC LIMIT ?""",
                    pf_params + (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT * FROM analysis_results WHERE 1=1 {pf_clause} ORDER BY timestamp DESC LIMIT ?",
                    pf_params + (limit,),
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

    def close_trade(
        self, trade_id: int, exit_price: float, pnl: float, exit_reason: str = ""
    ) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE trades SET status = 'CLOSED', exit_price = ?,
                   exit_timestamp = ?, pnl = ?, exit_reason = ? WHERE id = ?""",
                (exit_price, datetime.now().isoformat(), pnl, exit_reason, trade_id),
            )

    def get_strategy_stats(self, portfolio: str = "main", days: int = 90) -> dict:
        """Compute win rate and payoff ratio from closed trades for Kelly sizing."""
        with self._get_conn() as conn:
            cutoff = datetime.now()
            from datetime import timedelta
            cutoff = (cutoff - timedelta(days=days)).isoformat()
            rows = conn.execute(
                """SELECT pnl FROM trades
                   WHERE status = 'CLOSED' AND portfolio = ? AND timestamp >= ? AND pnl IS NOT NULL""",
                (portfolio, cutoff),
            ).fetchall()

        if not rows:
            return {"trade_count": 0, "win_rate": 0, "avg_win": 0, "avg_loss": 0, "payoff_ratio": 0, "expectancy": 0}

        pnls = [r["pnl"] for r in rows]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        win_rate = len(wins) / len(pnls) if pnls else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = abs(sum(losses) / len(losses)) if losses else 0
        payoff_ratio = avg_win / avg_loss if avg_loss > 0 else 0
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        return {
            "trade_count": len(pnls),
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "payoff_ratio": payoff_ratio,
            "expectancy": expectancy,
            "profit_factor": sum(wins) / abs(sum(losses)) if losses and sum(losses) != 0 else 0,
        }

    def get_strategy_performance(self, portfolio: str = "main", days: int = 30) -> dict:
        """Detailed performance for post-trade learning. Returns win rate trend."""
        stats = self.get_strategy_stats(portfolio, days)
        baseline = self.get_strategy_stats(portfolio, days * 3)
        stats["baseline_win_rate"] = baseline["win_rate"]
        stats["win_rate_delta"] = stats["win_rate"] - baseline["win_rate"] if baseline["trade_count"] >= 20 else 0
        return stats

    def update_trailing_stop(
        self, trade_id: int, highest_price: float, trailing_stop_price: float, active: bool = True
    ) -> None:
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE trades SET highest_price = ?, trailing_stop_price = ?,
                   trailing_stop_active = ? WHERE id = ?""",
                (highest_price, trailing_stop_price, 1 if active else 0, trade_id),
            )

    def update_trade_quantity(self, trade_id: int, new_quantity: int) -> None:
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE trades SET quantity = ? WHERE id = ?",
                (new_quantity, trade_id),
            )

    def save_partial_exit(self, trade_id: int, quantity: int, exit_price: float, pnl: float, reason: str = "", order_id: str = "") -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO partial_exits (trade_id, timestamp, quantity, exit_price, pnl, reason, order_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (trade_id, datetime.now().isoformat(), quantity, exit_price, pnl, reason, order_id),
            )
            return cursor.lastrowid

    def get_peak_equity(self, days: int = 30) -> float:
        """Get peak equity from daily_pnl table over the last N days."""
        with self._get_conn() as conn:
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            rows = conn.execute(
                "SELECT realized_pnl FROM daily_pnl WHERE date >= ? ORDER BY date",
                (cutoff,),
            ).fetchall()
        if not rows:
            return 0
        # Accumulate P&L to find peak
        cumulative = 0
        peak = 0
        for r in rows:
            cumulative += r["realized_pnl"]
            if cumulative > peak:
                peak = cumulative
        return peak
