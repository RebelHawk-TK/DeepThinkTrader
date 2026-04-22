"""Shared pytest fixtures.

Every test gets a fresh SQLite file in tmp_path so live `trades.db` is never
touched. Anthropic / Alpaca / Reddit / NewsAPI credentials are stubbed so
nothing reaches real APIs during unit tests (use `responses` per-test when
we need to assert HTTP behavior).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make the project root importable when pytest runs from repo root.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """Stub all API keys and point persistent paths at tmp_path."""
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")
    monkeypatch.setenv("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic")
    monkeypatch.setenv("NEWSAPI_KEY", "test-newsapi")
    monkeypatch.setenv("REDDIT_CLIENT_ID", "test-reddit-id")
    monkeypatch.setenv("REDDIT_CLIENT_SECRET", "test-reddit-secret")
    monkeypatch.setenv("TRADE_MODE", "normal")
    # Redirect any default DB or state path into tmp.
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def db(tmp_path):
    """Fresh Database instance backed by a tmp_path SQLite file."""
    from config import Config
    from utils.database import Database

    db_path = tmp_path / "trades_test.db"
    # Config reads DB_PATH once at import; patch the class attr.
    original = Config.DB_PATH
    Config.DB_PATH = str(db_path)
    try:
        yield Database(db_path=str(db_path))
    finally:
        Config.DB_PATH = original


@pytest.fixture
def test_user_id(db):
    """Seed a test user and return its id.

    Post-0004 migration, every tenant-owned row needs a user_id FK, so tests
    that write trades / analyses / reflections need a users row to reference.
    """
    with db._get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, role, enabled) VALUES (?, 'admin', 1)",
            ("test@example.com",),
        )
        return cur.lastrowid


@pytest.fixture
def risk_manager(db, test_user_id):
    from utils.risk_manager import RiskManager

    return RiskManager(
        user_id=test_user_id, api_key="test-key", secret_key="test-secret", db=db,
    )
