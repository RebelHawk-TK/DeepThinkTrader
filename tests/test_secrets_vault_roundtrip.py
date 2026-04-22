"""secrets_vault round-trip tests.

Encrypt → decrypt identity, status reporting, rotation, and delete.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet


@pytest.fixture
def _fernet_key(monkeypatch):
    """Provide a working Fernet key via the env var secrets_vault reads.

    secrets_vault caches the Fernet instance with lru_cache; clear it so
    each test gets a fresh key.
    """
    from utils import secrets_vault
    secrets_vault._fernet.cache_clear()
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("FERNET_KEY", key)
    yield key
    secrets_vault._fernet.cache_clear()


def test_set_then_get_returns_same_keys(db, test_user_id, _fernet_key):
    from utils import secrets_vault

    secrets_vault.set_alpaca_keys(test_user_id, "PKTEST1234ABCD", "secretABC123!")

    got = secrets_vault.get_alpaca_keys(test_user_id)
    assert got == ("PKTEST1234ABCD", "secretABC123!")


def test_status_exposes_tail_but_not_secret(db, test_user_id, _fernet_key):
    from utils import secrets_vault

    secrets_vault.set_alpaca_keys(test_user_id, "PKTEST1234ABCD", "secretABC123!")
    status = secrets_vault.get_status(test_user_id)

    assert status is not None
    assert status["tail"] == "ABCD"
    assert "updated_at" in status
    assert "secret" not in status  # plaintext must never appear in status


def test_rotate_overwrites_old_keys(db, test_user_id, _fernet_key):
    from utils import secrets_vault

    secrets_vault.set_alpaca_keys(test_user_id, "PKOLD111111111", "old-secret")
    secrets_vault.set_alpaca_keys(test_user_id, "PKNEW222222222", "new-secret")

    assert secrets_vault.get_alpaca_keys(test_user_id) == ("PKNEW222222222", "new-secret")
    assert secrets_vault.get_status(test_user_id)["tail"] == "2222"


def test_delete_removes_row(db, test_user_id, _fernet_key):
    from utils import secrets_vault

    secrets_vault.set_alpaca_keys(test_user_id, "PKTEST1234ABCD", "secret")
    secrets_vault.delete_alpaca_keys(test_user_id)

    assert secrets_vault.get_alpaca_keys(test_user_id) is None
    assert secrets_vault.get_status(test_user_id) is None


def test_get_alpaca_keys_missing_user_returns_none(db, _fernet_key):
    from utils import secrets_vault

    assert secrets_vault.get_alpaca_keys(9999) is None


def test_ciphertext_differs_from_plaintext_in_storage(db, test_user_id, _fernet_key):
    """Sanity check: the bytes in user_secrets must not equal the plaintext."""
    from utils import secrets_vault

    secrets_vault.set_alpaca_keys(test_user_id, "PKTEST1234ABCD", "supersecretvalue")

    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT alpaca_key_id_enc, alpaca_secret_enc FROM user_secrets WHERE user_id = ?",
            (test_user_id,),
        ).fetchone()

    assert row is not None
    assert b"PKTEST1234ABCD" not in bytes(row["alpaca_key_id_enc"])
    assert b"supersecretvalue" not in bytes(row["alpaca_secret_enc"])
