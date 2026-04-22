"""Database connection engine — routes to SQLite (Mac dev) or Postgres (cloud).

Critical contract: on the SQLite path we return a native sqlite3.Connection so
the existing database.py code runs unchanged. On the Postgres path we return
a wrapper that emulates the sqlite3 cursor API (fetchone/fetchall/lastrowid)
and translates SQLite-specific SQL on the fly (? → %s, INSERT OR REPLACE →
ON CONFLICT, etc.). Schema DDL is skipped on Postgres — alembic owns the
schema there.
"""

from __future__ import annotations

import logging
import os
import re
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Mode detection
# ─────────────────────────────────────────────────────────────────

_DATABASE_URL = os.getenv("DATABASE_URL", "").strip()


def is_postgres() -> bool:
    return _DATABASE_URL.startswith(("postgres://", "postgresql://", "postgresql+"))


def is_sqlite() -> bool:
    return not is_postgres()


# ─────────────────────────────────────────────────────────────────
# SQLite path — return native connection, no translation
# ─────────────────────────────────────────────────────────────────


def _sqlite_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ─────────────────────────────────────────────────────────────────
# Postgres path — psycopg3 connection wrapped for sqlite3-like API
# ─────────────────────────────────────────────────────────────────

# Tables with UNIQUE constraints need explicit conflict targets for
# INSERT OR REPLACE / INSERT OR IGNORE translation to Postgres.
_CONFLICT_TARGETS: dict[str, str] = {
    "atr_history": "(ticker, date)",
    "daily_pnl": "(date)",
}


def _translate_ddl(sql: str) -> str:
    """Make CREATE TABLE statements Postgres-compatible."""
    # INTEGER PRIMARY KEY AUTOINCREMENT → SERIAL PRIMARY KEY
    sql = re.sub(
        r"INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT",
        "SERIAL PRIMARY KEY",
        sql,
        flags=re.IGNORECASE,
    )
    return sql


def _translate_dml(sql: str) -> str:
    """Translate SQLite-specific DML to Postgres.

    Handles:
        INSERT OR REPLACE INTO t (cols) VALUES (...)
            → INSERT INTO t (cols) VALUES (...)
              ON CONFLICT (target) DO UPDATE SET col = EXCLUDED.col, ...
        INSERT OR IGNORE INTO t ...
            → INSERT INTO t ... ON CONFLICT DO NOTHING
    """
    upper = sql.upper()

    if "INSERT OR REPLACE" in upper:
        m = re.match(
            r"\s*INSERT\s+OR\s+REPLACE\s+INTO\s+(\w+)\s*\(([^)]+)\)\s*VALUES",
            sql,
            re.IGNORECASE,
        )
        if m:
            table = m.group(1)
            cols_str = m.group(2)
            cols = [c.strip() for c in cols_str.split(",")]
            target = _CONFLICT_TARGETS.get(table, "")
            sql = re.sub(
                r"INSERT\s+OR\s+REPLACE",
                "INSERT",
                sql,
                count=1,
                flags=re.IGNORECASE,
            )
            if target:
                # Build DO UPDATE SET clause excluding the conflict-target columns
                target_cols = {c.strip() for c in target.strip("()").split(",")}
                updates = ", ".join(
                    f"{c} = EXCLUDED.{c}" for c in cols if c not in target_cols and c != "id"
                )
                if updates:
                    sql = (
                        sql.rstrip().rstrip(";")
                        + f" ON CONFLICT {target} DO UPDATE SET {updates}"
                    )
                else:
                    sql = sql.rstrip().rstrip(";") + f" ON CONFLICT {target} DO NOTHING"

    elif "INSERT OR IGNORE" in upper:
        m = re.match(r"\s*INSERT\s+OR\s+IGNORE\s+INTO\s+(\w+)", sql, re.IGNORECASE)
        if m:
            table = m.group(1)
            target = _CONFLICT_TARGETS.get(table, "")
            sql = re.sub(
                r"INSERT\s+OR\s+IGNORE",
                "INSERT",
                sql,
                count=1,
                flags=re.IGNORECASE,
            )
            suffix = f" ON CONFLICT {target} DO NOTHING" if target else " ON CONFLICT DO NOTHING"
            sql = sql.rstrip().rstrip(";") + suffix

    return sql


def _first_keyword(sql: str) -> str:
    stripped = sql.strip()
    if not stripped:
        return ""
    return stripped.split(maxsplit=1)[0].upper()


class _PGCursorProxy:
    """psycopg3 cursor wrapped to look like sqlite3.Cursor."""

    def __init__(self, cur, lastrowid: int | None = None):
        self._cur = cur
        self._lastrowid = lastrowid

    @property
    def lastrowid(self) -> int | None:
        return self._lastrowid

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)


class _PGConnProxy:
    """psycopg3 connection wrapped to look like sqlite3.Connection.

    Translates SQL dialect at execute() time. Use as a context manager (commits
    on clean exit, rolls back on exception) to match sqlite3 semantics.
    """

    def __init__(self, pg_conn):
        self._c = pg_conn

    # ── sqlite3.Connection surface ──

    def execute(self, sql: str, params: tuple | list | None = None) -> _PGCursorProxy:
        params = tuple(params) if params is not None else ()
        kw = _first_keyword(sql)

        # PRAGMAs are no-ops on Postgres; return an empty proxy
        if kw == "PRAGMA":
            return _PGCursorProxy(_EmptyCursor())

        # DDL (CREATE, ALTER) — translate AUTOINCREMENT, run, don't expect rows.
        # We also swallow "already exists" ALTER errors silently since _migrate_*
        # helpers are idempotent-by-design on SQLite but noisy on PG.
        if kw in ("CREATE", "ALTER"):
            pg_sql = _translate_ddl(sql)
            cur = self._c.cursor()
            try:
                cur.execute(pg_sql, params)
            except Exception as e:
                msg = str(e).lower()
                if kw == "ALTER" and ("already exists" in msg or "duplicate column" in msg):
                    # Column/constraint already present — matches SQLite idempotent behavior
                    self._c.rollback()
                else:
                    raise
            finally:
                cur.close()
            return _PGCursorProxy(_EmptyCursor())

        # DML: INSERT / UPDATE / DELETE / SELECT / WITH
        pg_sql = _translate_dml(sql)

        # sqlite uses ? placeholders; psycopg uses %s
        if "?" in pg_sql:
            pg_sql = pg_sql.replace("?", "%s")

        # For INSERT without RETURNING, append RETURNING id so we can populate
        # lastrowid (matches sqlite3.Cursor behavior). Skip if the query already
        # has RETURNING, or if the insert target lacks an 'id' column.
        is_insert = kw == "INSERT"
        # Tables whose PK is something other than `id` — appending RETURNING id
        # would fail with "column id does not exist". Extend this set when new
        # id-less tables are added.
        _TABLES_WITHOUT_ID = {"user_secrets"}
        _target = ""
        if is_insert:
            import re as _re
            m = _re.search(r"INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_]*)", pg_sql, _re.IGNORECASE)
            if m:
                _target = m.group(1).lower()
        want_returning = (
            is_insert
            and _target not in _TABLES_WITHOUT_ID
            and "RETURNING" not in pg_sql.upper()
            and "DO NOTHING" not in pg_sql.upper()
            and "DO UPDATE" not in pg_sql.upper()
        )
        if want_returning:
            pg_sql = pg_sql.rstrip().rstrip(";") + " RETURNING id"

        cur = self._c.cursor()
        try:
            cur.execute(pg_sql, params)
        except Exception:
            cur.close()
            raise

        lastrowid: int | None = None
        if is_insert and cur.description:
            try:
                row = cur.fetchone()
                if row:
                    # dict_row factory — RETURNING id column comes back as dict
                    lastrowid = row.get("id") if isinstance(row, dict) else row[0]
            except Exception:
                lastrowid = None

        return _PGCursorProxy(cur, lastrowid=lastrowid)

    def executemany(self, sql, seq_of_params):
        for params in seq_of_params:
            self.execute(sql, params)

    def commit(self):
        self._c.commit()

    def rollback(self):
        self._c.rollback()

    def close(self):
        self._c.close()

    # ── Context manager (sqlite3 commits on success, rolls back on failure) ──

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            if exc_type is None:
                self._c.commit()
            else:
                self._c.rollback()
        finally:
            self._c.close()
        return False


class _EmptyCursor:
    """Returned for PRAGMA / DDL — has the attributes callers might check."""

    description = None

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __iter__(self):
        return iter([])


def _psycopg_url() -> str:
    """Strip SQLAlchemy's '+driver' suffix so psycopg3 can parse the URL.

    SA URLs look like 'postgresql+psycopg://...' while libpq wants plain
    'postgresql://...'. Alembic keeps the SA form; our wrapper uses raw psycopg.
    """
    url = _DATABASE_URL
    if url.startswith("postgresql+"):
        # postgresql+psycopg:// → postgresql://
        _, rest = url.split("+", 1)
        _, remainder = rest.split("://", 1)
        return "postgresql://" + remainder
    if url.startswith("postgres+"):
        _, rest = url.split("+", 1)
        _, remainder = rest.split("://", 1)
        return "postgres://" + remainder
    return url


def _postgres_conn() -> _PGConnProxy:
    import psycopg
    from psycopg.rows import dict_row

    raw = psycopg.connect(_psycopg_url(), row_factory=dict_row)
    return _PGConnProxy(raw)


# ─────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────


def get_conn(db_path: str):
    """Return a connection that behaves like sqlite3.Connection.

    On SQLite (default) this IS a sqlite3.Connection. On Postgres this is a
    wrapper that translates SQLite-flavor SQL on the fly.
    """
    if is_postgres():
        return _postgres_conn()
    return _sqlite_conn(db_path)
