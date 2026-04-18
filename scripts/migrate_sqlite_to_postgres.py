#!/usr/bin/env python3
"""Copy trade data from the live SQLite trades.db into a Postgres database.

Used once at the Phase B cutover — point this at the Cloud SQL instance (or
the local docker compose Postgres) after `alembic upgrade head` has created
the schema, and all historical trades / research / state get copied over.

Usage:
    export DATABASE_URL='postgresql+psycopg://user:pass@host:port/db'
    python scripts/migrate_sqlite_to_postgres.py /path/to/trades.db

By default reads SQLite from the project root. Idempotent — re-runs skip rows
that already exist (matched by primary key).
"""

from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("migrate")

# Project tables to copy, in FK-safe order (parents before children).
_TABLES_IN_ORDER = [
    "trades",
    "research_reports",
    "analysis_results",
    "daily_pnl",
    "partial_exits",
    "atr_history",
    "alpaca_request_ids",
    "slippage_records",
    "edge_performance",
    "reflections",
]


def _connect_pg():
    import psycopg
    from psycopg.rows import dict_row

    url = os.getenv("DATABASE_URL", "")
    if url.startswith("postgresql+"):
        _, rest = url.split("+", 1)
        _, remainder = rest.split("://", 1)
        url = "postgresql://" + remainder
    if not url:
        log.error("DATABASE_URL env var required")
        sys.exit(1)
    return psycopg.connect(url, row_factory=dict_row)


def _copy_table(sqlite_conn: sqlite3.Connection, pg_conn, table: str) -> int:
    rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()
    if not rows:
        log.info("  %s: 0 rows", table)
        return 0

    cols = [k for k in rows[0].keys()]
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(cols)

    sql = (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT (id) DO NOTHING"
    )

    with pg_conn.cursor() as cur:
        inserted = 0
        for r in rows:
            try:
                cur.execute(sql, tuple(r[c] for c in cols))
                inserted += cur.rowcount or 0
            except Exception as e:
                log.warning("  %s id=%s failed: %s", table, r.get("id"), e)
        pg_conn.commit()

    # Postgres keeps SERIAL sequences independent of manual id inserts — reset.
    with pg_conn.cursor() as cur:
        try:
            cur.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table}), 1))"
            )
            pg_conn.commit()
        except Exception as e:
            log.debug("  %s sequence reset skipped: %s", table, e)

    log.info("  %s: %d rows (inserted %d)", table, len(rows), inserted)
    return inserted


def main() -> int:
    default_sqlite = Path(__file__).resolve().parent.parent / "trades.db"
    ap = argparse.ArgumentParser()
    ap.add_argument("sqlite_path", nargs="?", default=str(default_sqlite))
    args = ap.parse_args()

    if not Path(args.sqlite_path).exists():
        log.error("SQLite file not found: %s", args.sqlite_path)
        return 1

    sqlite_conn = sqlite3.connect(args.sqlite_path)
    sqlite_conn.row_factory = sqlite3.Row

    pg_conn = _connect_pg()

    log.info("Copying %s → %s", args.sqlite_path, os.getenv("DATABASE_URL"))
    total = 0
    for table in _TABLES_IN_ORDER:
        # Skip tables that don't exist in the source (older SQLite DBs)
        try:
            sqlite_conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone()
        except sqlite3.OperationalError:
            log.info("  %s: table not in source — skipped", table)
            continue
        total += _copy_table(sqlite_conn, pg_conn, table)

    log.info("Done. %d total rows inserted.", total)
    pg_conn.close()
    sqlite_conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
