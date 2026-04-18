from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime

from config import Config
from utils import db_engine

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = Config.DB_PATH):
        self.db_path = db_path

        if db_engine.is_sqlite():
            self._enable_wal()
            self._init_tables()
            # Security: restrict database file permissions to owner only
            try:
                import os
                os.chmod(self.db_path, 0o600)
            except OSError:
                pass
        else:
            # Postgres path — alembic owns the schema. Verify the expected
            # tables exist so a missing migration fails loud instead of
            # crashing mid-query.
            self._verify_pg_schema()

    def _enable_wal(self) -> None:
        """Enable Write-Ahead Logging for better concurrency and crash recovery."""
        try:
            conn = sqlite3.connect(self.db_path)
            mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
            conn.close()
            if mode.lower() == "wal":
                logger.info(f"SQLite WAL mode enabled for {self.db_path}")
        except Exception:
            pass

    def _verify_pg_schema(self) -> None:
        """Fail fast if core tables missing on Postgres (alembic not run yet)."""
        required = ("trades", "research_reports", "analysis_results")
        with self._get_conn() as conn:
            cur = conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public'"
            )
            existing = {r["table_name"] for r in cur.fetchall()}
        missing = [t for t in required if t not in existing]
        if missing:
            raise RuntimeError(
                f"Postgres schema missing tables: {missing}. "
                f"Run 'alembic upgrade head' before starting."
            )

    def _get_conn(self):
        """Return a connection that behaves like sqlite3.Connection.

        On SQLite this is a native sqlite3 connection. On Postgres it's a
        wrapper that translates SQL on the fly. Callers should use as a
        context manager to get commit-on-exit / rollback-on-error semantics.
        """
        return db_engine.get_conn(self.db_path)

    def health_check(self) -> dict:
        """Verify database is accessible and return table counts."""
        try:
            with self._get_conn() as conn:
                if db_engine.is_postgres():
                    rows = conn.execute(
                        "SELECT table_name AS name FROM information_schema.tables "
                        "WHERE table_schema = 'public'"
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()

                result: dict = {"status": "ok", "tables": {}}
                for row in rows:
                    name = row["name"]
                    # Quoting matches both dialects for simple table names
                    count = conn.execute(f'SELECT COUNT(*) AS n FROM "{name}"').fetchone()
                    result["tables"][name] = count["n"] if count else 0

                if db_engine.is_sqlite():
                    journal = conn.execute("PRAGMA journal_mode").fetchone()[0]
                    result["journal_mode"] = journal
                else:
                    result["dialect"] = "postgresql"
                return result
        except Exception as e:
            return {"status": "error", "error": str(e)}

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
            self._init_atr_history_table(conn)
            self._init_slippage_table(conn)
            self._init_edge_performance_table(conn)
            self._init_reflections_table(conn)
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
            # Indexes — dashboard queries filter heavily on these columns.
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_ticker ON trades(ticker)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_portfolio ON trades(portfolio)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_analysis_ticker ON analysis_results(ticker)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_research_ticker ON research_reports(ticker)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reflections_ticker ON reflections(ticker)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_reflections_created ON reflections(created_at)")

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
            "sector": "TEXT",
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

    def _init_atr_history_table(self, conn: sqlite3.Connection) -> None:
        """Create atr_history table for true median ATR calculation."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS atr_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                atr_value REAL NOT NULL,
                UNIQUE(ticker, date)
            )
        """)

    def save_atr(self, ticker: str, atr_value: float) -> None:
        """Store daily ATR value for a ticker."""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._get_conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO atr_history (ticker, date, atr_value)
                   VALUES (?, ?, ?)""",
                (ticker, today, atr_value),
            )

    def get_median_atr(self, ticker: str, days: int = 30) -> float:
        """Get median ATR from stored history. Seeds from yfinance if insufficient data."""
        with self._get_conn() as conn:
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            rows = conn.execute(
                """SELECT atr_value FROM atr_history
                   WHERE ticker = ? AND date >= ?
                   ORDER BY date""",
                (ticker, cutoff),
            ).fetchall()

        if len(rows) < 5:
            # Seed historical ATR from yfinance
            self._seed_atr_history(ticker)
            # Re-query after seeding
            with self._get_conn() as conn:
                rows = conn.execute(
                    """SELECT atr_value FROM atr_history
                       WHERE ticker = ? AND date >= ?
                       ORDER BY date""",
                    (ticker, cutoff),
                ).fetchall()

        if len(rows) < 5:
            return 0.0
        values = sorted(r["atr_value"] for r in rows)
        mid = len(values) // 2
        if len(values) % 2 == 0:
            return (values[mid - 1] + values[mid]) / 2
        return values[mid]

    def _seed_atr_history(self, ticker: str, period: str = "3mo") -> None:
        """Seed ATR history from yfinance for accurate median on first encounter."""
        try:
            import yfinance as yf
            import numpy as np

            hist = yf.Ticker(ticker).history(period=period)
            if hist.empty or len(hist) < 15:
                return

            high = hist["High"].values
            low = hist["Low"].values
            close = hist["Close"].values

            # True Range calculation
            tr = np.maximum(
                high[1:] - low[1:],
                np.maximum(
                    np.abs(high[1:] - close[:-1]),
                    np.abs(low[1:] - close[:-1]),
                ),
            )

            # 14-day ATR rolling average
            atr_period = 14
            if len(tr) < atr_period:
                return

            dates = hist.index[atr_period:]
            with self._get_conn() as conn:
                for i in range(atr_period, len(tr)):
                    atr_val = float(np.mean(tr[i - atr_period:i]))
                    date_str = dates[i - atr_period].strftime("%Y-%m-%d")
                    conn.execute(
                        """INSERT OR IGNORE INTO atr_history (ticker, date, atr_value)
                           VALUES (?, ?, ?)""",
                        (ticker, date_str, atr_val),
                    )
            logger.info(f"Seeded {len(dates)} ATR values for {ticker} from yfinance")
        except Exception as e:
            logger.warning(f"Failed to seed ATR history for {ticker}: {e}")

    def _init_slippage_table(self, conn: sqlite3.Connection) -> None:
        """Create slippage_records table for tracking fill quality."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS slippage_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                expected_price REAL NOT NULL,
                filled_price REAL NOT NULL,
                slippage_pct REAL NOT NULL,
                order_type TEXT NOT NULL,
                side TEXT NOT NULL,
                shares INTEGER,
                hour_of_day INTEGER,
                portfolio TEXT DEFAULT 'main'
            )
        """)

    def _init_edge_performance_table(self, conn: sqlite3.Connection) -> None:
        """Create edge_performance table for tracking which edge combos win."""
        conn.execute("""
            CREATE TABLE IF NOT EXISTS edge_performance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                edge_combo TEXT NOT NULL,
                edges_fired INTEGER NOT NULL,
                fund_passed INTEGER,
                tech_passed INTEGER,
                sent_passed INTEGER,
                conviction REAL,
                pnl REAL,
                won INTEGER,
                portfolio TEXT DEFAULT 'main',
                FOREIGN KEY (trade_id) REFERENCES trades(id)
            )
        """)

    def _init_reflections_table(self, conn: sqlite3.Connection) -> None:
        """Post-trade lesson memory — feeds retrieval-augmented prompting.

        Based on TradingAgents (arXiv:2412.20138) and FinMem (arXiv:2311.13743)
        — both show post-trade reflection written back into agent context
        materially improves Sharpe. Start simple: recency-based retrieval.
        Semantic retrieval (embeddings) is a future extension.
        """
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reflections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER NOT NULL,
                ticker TEXT NOT NULL,
                created_at TEXT NOT NULL,
                thesis TEXT NOT NULL,
                outcome_pnl REAL NOT NULL,
                outcome_label TEXT NOT NULL,
                lesson TEXT NOT NULL,
                FOREIGN KEY (trade_id) REFERENCES trades(id)
            )
        """)

    def save_reflection(
        self,
        trade_id: int,
        ticker: str,
        thesis: str,
        outcome_pnl: float,
        lesson: str,
    ) -> int:
        """Persist a post-trade lesson. Returns reflection id."""
        label = "win" if outcome_pnl > 0 else "loss" if outcome_pnl < 0 else "flat"
        with self._get_conn() as conn:
            cur = conn.execute(
                """INSERT INTO reflections
                   (trade_id, ticker, created_at, thesis, outcome_pnl, outcome_label, lesson)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (trade_id, ticker, datetime.now().isoformat(),
                 thesis[:2000], outcome_pnl, label, lesson[:2000]),
            )
            return cur.lastrowid or 0

    def get_reflections(
        self, ticker: str | None = None, limit: int = 5
    ) -> list[dict]:
        """Most recent reflections, optionally scoped to a ticker.

        Tickered reflections come first (when ticker given), then global
        recent lessons fill any remaining slots. This is the retrieval half
        of the memory loop — keep it simple until a vector store lands.
        """
        rows: list[dict] = []
        with self._get_conn() as conn:
            if ticker:
                tickered = conn.execute(
                    """SELECT * FROM reflections
                       WHERE ticker = ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (ticker, limit),
                ).fetchall()
                rows.extend(dict(r) for r in tickered)
            remaining = limit - len(rows)
            if remaining > 0:
                seen_ids = {r["id"] for r in rows}
                global_recent = conn.execute(
                    """SELECT * FROM reflections
                       ORDER BY created_at DESC LIMIT ?""",
                    (remaining + len(rows),),
                ).fetchall()
                for r in global_recent:
                    if r["id"] not in seen_ids and len(rows) < limit:
                        rows.append(dict(r))
        return rows

    # ── Phase 8a: Slippage Analytics ───────────────────────────

    def save_slippage(
        self, ticker: str, expected_price: float, filled_price: float,
        order_type: str, side: str, shares: int, portfolio: str = "main",
    ) -> None:
        """Record slippage for every filled order."""
        if expected_price <= 0 or filled_price <= 0:
            return
        slippage_pct = ((filled_price - expected_price) / expected_price) * 100
        hour = datetime.now().hour
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO slippage_records
                   (ticker, timestamp, expected_price, filled_price, slippage_pct,
                    order_type, side, shares, hour_of_day, portfolio)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ticker, datetime.now().isoformat(), expected_price, filled_price,
                 round(slippage_pct, 4), order_type, side, shares, hour, portfolio),
            )

    def get_slippage_analytics(self, days: int = 30) -> dict:
        """Aggregate slippage data for reporting and warnings.

        Returns by-ticker and by-hour breakdowns.
        """
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with self._get_conn() as conn:
            # By ticker: avg slippage, total cost
            ticker_rows = conn.execute(
                """SELECT ticker,
                          COUNT(*) as count,
                          AVG(slippage_pct) as avg_slippage,
                          SUM(ABS(slippage_pct) * shares * expected_price / 100) as total_cost
                   FROM slippage_records
                   WHERE timestamp >= ?
                   GROUP BY ticker
                   ORDER BY avg_slippage DESC""",
                (cutoff,),
            ).fetchall()

            # By hour of day
            hour_rows = conn.execute(
                """SELECT hour_of_day,
                          COUNT(*) as count,
                          AVG(slippage_pct) as avg_slippage
                   FROM slippage_records
                   WHERE timestamp >= ?
                   GROUP BY hour_of_day
                   ORDER BY hour_of_day""",
                (cutoff,),
            ).fetchall()

            # Overall
            overall = conn.execute(
                """SELECT COUNT(*) as count,
                          AVG(slippage_pct) as avg_slippage,
                          MAX(slippage_pct) as worst_slippage,
                          SUM(ABS(slippage_pct) * shares * expected_price / 100) as total_cost
                   FROM slippage_records WHERE timestamp >= ?""",
                (cutoff,),
            ).fetchone()

        return {
            "by_ticker": [dict(r) for r in ticker_rows],
            "by_hour": [dict(r) for r in hour_rows],
            "overall": dict(overall) if overall else {},
        }

    def get_ticker_slippage_avg(self, ticker: str, days: int = 30) -> float:
        """Get average slippage for a specific ticker. Used to warn before trading."""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT AVG(slippage_pct) as avg_slip
                   FROM slippage_records
                   WHERE ticker = ? AND timestamp >= ?""",
                (ticker, cutoff),
            ).fetchone()
        return float(row["avg_slip"]) if row and row["avg_slip"] is not None else 0.0

    # ── Phase 8b: Edge Performance Tracking ────────────────────

    def save_edge_performance(
        self, trade_id: int, ticker: str, edge_combo: str, edges_fired: int,
        fund_passed: bool, tech_passed: bool, sent_passed: bool,
        conviction: float, pnl: float, portfolio: str = "main",
    ) -> None:
        """Record edge combo and outcome when a trade closes."""
        with self._get_conn() as conn:
            conn.execute(
                """INSERT INTO edge_performance
                   (trade_id, ticker, timestamp, edge_combo, edges_fired,
                    fund_passed, tech_passed, sent_passed, conviction, pnl, won, portfolio)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (trade_id, ticker, datetime.now().isoformat(), edge_combo, edges_fired,
                 1 if fund_passed else 0, 1 if tech_passed else 0,
                 1 if sent_passed else 0, conviction, pnl, 1 if pnl > 0 else 0, portfolio),
            )

    def get_edge_combo_stats(self, min_trades: int = 5, days: int = 90) -> list[dict]:
        """Get win rate and avg P&L by edge combo. Used to boost/penalize conviction."""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT edge_combo,
                          COUNT(*) as trade_count,
                          SUM(won) as wins,
                          AVG(pnl) as avg_pnl,
                          SUM(pnl) as total_pnl,
                          ROUND(CAST(SUM(won) AS REAL) / COUNT(*) * 100, 1) as win_rate_pct
                   FROM edge_performance
                   WHERE timestamp >= ?
                   GROUP BY edge_combo
                   HAVING COUNT(*) >= ?
                   ORDER BY win_rate_pct DESC""",
                (cutoff, min_trades),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_edge_combo_win_rate(self, edge_combo: str, days: int = 90) -> float | None:
        """Get win rate for a specific edge combo. Returns None if insufficient data."""
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        with self._get_conn() as conn:
            row = conn.execute(
                """SELECT COUNT(*) as n, SUM(won) as w
                   FROM edge_performance
                   WHERE edge_combo = ? AND timestamp >= ?""",
                (edge_combo, cutoff),
            ).fetchone()
        if row and row["n"] >= 5:
            return row["w"] / row["n"]
        return None

    @staticmethod
    def _json_safe(obj):
        """Convert numpy types to native Python for JSON serialization."""
        import numpy as np
        if isinstance(obj, (np.bool_, np.integer)):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

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
                    json.dumps(report, default=self._json_safe),
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
        # Both writes happen on the SAME connection to avoid self-deadlock.
        # Nested connections here caused SQLITE_BUSY: outer conn held the write
        # lock for the UPDATE, second conn from save_edge_performance blocked
        # forever until busy_timeout expired.
        with self._get_conn() as conn:
            conn.execute(
                """UPDATE trades SET status = 'CLOSED', exit_price = ?,
                   exit_timestamp = ?, pnl = ?, exit_reason = ? WHERE id = ?""",
                (exit_price, datetime.now().isoformat(), pnl, exit_reason, trade_id),
            )

            # Phase 8b: Record edge performance for learning
            trade = conn.execute(
                "SELECT * FROM trades WHERE id = ?", (trade_id,)
            ).fetchone()
            if trade:
                edge_details_raw = trade["edge_details"] or "[]"
                try:
                    edges = json.loads(edge_details_raw)
                    fund = any(e.get("label") == "Fundamental" and e.get("passed") for e in edges)
                    tech = any(e.get("label") == "Technical" and e.get("passed") for e in edges)
                    sent = any(e.get("label") == "Sentiment" and e.get("passed") for e in edges)
                    combo_parts = []
                    if fund:
                        combo_parts.append("F")
                    if tech:
                        combo_parts.append("T")
                    if sent:
                        combo_parts.append("S")
                    edge_combo = "+".join(combo_parts) if combo_parts else "none"

                    # Inline the INSERT on the same conn — don't call save_edge_performance
                    conn.execute(
                        """INSERT INTO edge_performance
                           (trade_id, ticker, timestamp, edge_combo, edges_fired,
                            fund_passed, tech_passed, sent_passed, conviction, pnl, won, portfolio)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (trade_id, trade["ticker"], datetime.now().isoformat(), edge_combo,
                         trade["edges_fired"] or 0,
                         1 if fund else 0, 1 if tech else 0, 1 if sent else 0,
                         trade["conviction"] or 0, pnl, 1 if pnl > 0 else 0,
                         trade["portfolio"] or "main"),
                    )
                except (json.JSONDecodeError, TypeError):
                    pass

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
