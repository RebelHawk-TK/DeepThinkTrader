"""End-to-end orchestrator tests — the multi-tenant dispatch contract.

Exercises BotOrchestrator._guarded_cycle with a real DB and stubbed
externals. Validates the cross-cutting guarantees the refactor promised:

- Every enabled user with keys gets their OWN DeepThinkTrader built with
  their OWN user_id and keys (no cross-pollination).
- Orphan users (keys present, users row missing) are skipped BEFORE a
  trader is constructed — guards against FK violations on downstream saves.
- Enabled users without keys are skipped with a log, not crashed on.
- Market-closed cycles don't construct any trader at all.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ────────────────────────────────────────────────────────────


class _RecordingTrader:
    """Stand-in for DeepThinkTrader that records construction + cycle calls
    without touching Alpaca, yfinance, or the real agent pipeline.
    """

    instances: list["_RecordingTrader"] = []

    def __init__(self, user_id, api_key, secret_key, state,
                 dynamic_watchlist=None, last_scan_date=None):
        self.user_id = user_id
        self.api_key = api_key
        self.secret_key = secret_key
        self.cycles: list[str] = []
        self.health_checked = False
        self._dynamic_watchlist = None
        self._last_scan_date = last_scan_date or ""
        _RecordingTrader.instances.append(self)

    def run_cycle(self, portfolio: str = "main") -> None:
        self.cycles.append(portfolio)

    def _check_strategy_health(self) -> None:
        self.health_checked = True

    def _check_exits_only(self) -> None:
        self.cycles.append("exits")


@pytest.fixture
def recording_trader(monkeypatch):
    """Swap main.DeepThinkTrader for the recording stub for the test's lifetime."""
    _RecordingTrader.instances = []
    import main as main_mod
    monkeypatch.setattr(main_mod, "DeepThinkTrader", _RecordingTrader)
    return _RecordingTrader


@pytest.fixture
def market_open(monkeypatch):
    """Force the market-clock singleton to report 'open' regardless of UTC time."""
    import main as main_mod

    fake_clock = MagicMock()
    fake_clock.is_market_open.return_value = True
    fake_clock.minutes_until_open.return_value = None
    fake_clock.log_status.return_value = None
    monkeypatch.setattr(main_mod, "get_market_clock", lambda *a, **kw: fake_clock)
    return fake_clock


@pytest.fixture
def market_closed(monkeypatch):
    import main as main_mod

    fake_clock = MagicMock()
    fake_clock.is_market_open.return_value = False
    fake_clock.minutes_until_open.return_value = 60
    fake_clock.log_status.return_value = None
    monkeypatch.setattr(main_mod, "get_market_clock", lambda *a, **kw: fake_clock)
    return fake_clock


@pytest.fixture
def keys_by_user(monkeypatch):
    """Patch secrets_vault.get_alpaca_keys to a dict-backed fake.

    Tests mutate the returned dict; callers of get_alpaca_keys see the
    current mapping. Missing keys return None (matches real semantics).
    """
    store: dict[int, tuple[str, str]] = {}

    def fake_get(user_id: int):
        return store.get(user_id)

    monkeypatch.setattr("utils.secrets_vault.get_alpaca_keys", fake_get)
    return store


@pytest.fixture
def orchestrator_with_db(db, monkeypatch):
    """BotOrchestrator bound to the test DB.

    The orchestrator constructs its own Database() internally; we point it
    at the tmp fixture DB by patching Config.DB_PATH (already done by the
    db fixture) and then rebuild the orchestrator so its db handle uses
    the same path.
    """
    from config import Config
    import main as main_mod

    # Orchestrator's __init__ calls Database() with no args → picks up
    # Config.DB_PATH which the db fixture already pointed at tmp.
    orch = main_mod.BotOrchestrator()
    # Belt-and-suspenders: swap in the fixture's db instance so we share
    # the same connection-pool settings the fixture set up.
    orch.db = db
    return orch


def _seed_user(db, email: str, enabled: int = 1, role: str = "user") -> int:
    with db._get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO users (email, role, enabled) VALUES (?, ?, ?)",
            (email, role, enabled),
        )
        return cur.lastrowid


def _seed_user_secret(db, user_id: int) -> None:
    """Insert a user_secrets row directly — bypasses Fernet + GCP.

    The orchestrator checks for *existence* of this row via
    get_active_user_ids' JOIN, not the cleartext secret content, so
    opaque bytes are fine here.
    """
    with db._get_conn() as conn:
        conn.execute(
            """INSERT INTO user_secrets
               (user_id, alpaca_key_id_enc, alpaca_secret_enc, alpaca_key_id_tail)
               VALUES (?, ?, ?, ?)""",
            (user_id, b"enc-key-id", b"enc-secret", "XXXX"),
        )


# ── Tests ───────────────────────────────────────────────────────────────


def test_orchestrator_dispatches_per_user_with_isolated_credentials(
    orchestrator_with_db, recording_trader, keys_by_user, market_open,
):
    """Two enabled users with keys → two traders, each bound to its own user_id + keys."""
    alice = _seed_user(orchestrator_with_db.db, "alice@example.com")
    bob = _seed_user(orchestrator_with_db.db, "bob@example.com")
    _seed_user_secret(orchestrator_with_db.db, alice)
    _seed_user_secret(orchestrator_with_db.db, bob)
    keys_by_user[alice] = ("ALICE-KEY", "alice-secret")
    keys_by_user[bob] = ("BOB-KEY", "bob-secret")

    orchestrator_with_db._guarded_cycle()

    # One trader per user; each one received ITS user's keys, not the other's.
    built = {t.user_id: t for t in recording_trader.instances}
    assert set(built) == {alice, bob}
    assert built[alice].api_key == "ALICE-KEY"
    assert built[alice].secret_key == "alice-secret"
    assert built[bob].api_key == "BOB-KEY"
    assert built[bob].secret_key == "bob-secret"

    # Both traders ran the same portfolio set — whatever PENNY_ENABLED
    # resolved to, it applied identically per user.
    assert built[alice].cycles == built[bob].cycles
    assert "main" in built[alice].cycles


def test_orchestrator_skips_user_without_alpaca_keys(
    orchestrator_with_db, recording_trader, keys_by_user, market_open,
):
    """User enabled + has user_secrets row + get_alpaca_keys returns None
    (e.g. Fernet failure) → log + skip, don't crash the cycle for other users.
    """
    alice = _seed_user(orchestrator_with_db.db, "alice@example.com")
    bob = _seed_user(orchestrator_with_db.db, "bob@example.com")
    _seed_user_secret(orchestrator_with_db.db, alice)
    _seed_user_secret(orchestrator_with_db.db, bob)
    keys_by_user[alice] = ("ALICE-KEY", "alice-secret")
    # bob has a secrets row but get_alpaca_keys returns None (decrypt failed)

    orchestrator_with_db._guarded_cycle()

    built = {t.user_id for t in recording_trader.instances}
    assert built == {alice}, "bob should have been skipped when keys unresolvable"


def test_orchestrator_skips_orphan_user_id_before_trader_construction(
    orchestrator_with_db, recording_trader, keys_by_user, market_open,
):
    """Orphan scenario: user_secrets row exists for user_id=999 but no users row.

    get_active_user_ids' INNER JOIN wouldn't normally return this, but if
    something hands us a stale uid, user_exists() must reject it BEFORE
    we try to construct a trader whose downstream saves would FK-violate.
    """
    alice = _seed_user(orchestrator_with_db.db, "alice@example.com")
    _seed_user_secret(orchestrator_with_db.db, alice)
    keys_by_user[alice] = ("ALICE-KEY", "alice-secret")
    # Inject an orphan uid by forging get_active_user_ids — simulates a race
    # between users-row deletion and active-uid enumeration.
    orig_get_active = orchestrator_with_db.db.get_active_user_ids
    orchestrator_with_db.db.get_active_user_ids = lambda: [*orig_get_active(), 999]
    keys_by_user[999] = ("ORPHAN-KEY", "orphan-secret")

    orchestrator_with_db._guarded_cycle()

    built = {t.user_id for t in recording_trader.instances}
    assert 999 not in built, "orphan uid 999 must be rejected by user_exists guard"
    assert built == {alice}


def test_orchestrator_skips_cycle_when_market_closed(
    orchestrator_with_db, recording_trader, keys_by_user, market_closed,
):
    """No trader constructed when the market is closed — saves per-user
    Alpaca API quota and guarantees no spurious cycles during weekends.
    """
    alice = _seed_user(orchestrator_with_db.db, "alice@example.com")
    _seed_user_secret(orchestrator_with_db.db, alice)
    keys_by_user[alice] = ("ALICE-KEY", "alice-secret")

    orchestrator_with_db._guarded_cycle()

    assert recording_trader.instances == [], (
        "market-closed cycles must not construct any per-user trader"
    )


def test_orchestrator_no_active_users_is_a_noop(
    orchestrator_with_db, recording_trader, keys_by_user, market_open,
):
    """Zero active users → early-out before even checking the market clock.

    This matches production behavior on a fresh deploy where no users
    have added Alpaca keys yet — the bot sleeps without error.
    """
    orchestrator_with_db._guarded_cycle()
    assert recording_trader.instances == []
