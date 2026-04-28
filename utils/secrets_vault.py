"""Encrypt/decrypt per-user Alpaca API credentials.

The Fernet key lives in GCP Secret Manager as `trader-fernet-key`. Both the
dashboard and bot service accounts have `secretAccessor` on it. We cache the
Fernet instance for the life of the process — rotating the key requires a
restart.

Phase D form writes via `set_alpaca_keys`. Phase C bot will read via
`get_alpaca_keys` on each cycle (TODO: not yet wired).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from functools import lru_cache

logger = logging.getLogger(__name__)

_SECRET_NAME = os.getenv("FERNET_KEY_SECRET", "trader-fernet-key")
_PROJECT = os.getenv("GCP_PROJECT", "travelforge-app")


@lru_cache(maxsize=1)
def _fernet():
    """Load the Fernet key. Lookup order:
      1. macOS Keychain (com.deepthinktrader / fernet-key) — local single-user
      2. FERNET_KEY env var — backward compat + Cloud Run / Docker
      3. GCP Secret Manager — multi-tenant cloud (currently unused)
    """
    from cryptography.fernet import Fernet

    # 1. Keychain (preferred for local Mac install)
    if os.getenv("DISABLE_KEYCHAIN") != "1":
        try:
            import subprocess
            result = subprocess.run(
                ["security", "find-generic-password", "-s", "com.deepthinktrader",
                 "-a", "fernet-key", "-w"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return Fernet(result.stdout.strip().encode())
        except Exception as e:
            logger.debug(f"Keychain Fernet lookup failed: {e}")

    # 2. Env var fallback
    env_key = os.getenv("FERNET_KEY")
    if env_key:
        return Fernet(env_key.encode())

    # 3. GCP Secret Manager (cloud only)
    from google.cloud import secretmanager
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{_PROJECT}/secrets/{_SECRET_NAME}/versions/latest"
    resp = client.access_secret_version(name=name)
    return Fernet(resp.payload.data)


def set_alpaca_keys(user_id: int, key_id: str, secret_key: str) -> None:
    """Encrypt + upsert a user's Alpaca paper credentials."""
    from utils.database import Database

    key_id = key_id.strip()
    secret_key = secret_key.strip()
    if not key_id or not secret_key:
        raise ValueError("key_id and secret_key must be non-empty")

    f = _fernet()
    key_enc = f.encrypt(key_id.encode())
    sec_enc = f.encrypt(secret_key.encode())
    tail = key_id[-4:] if len(key_id) >= 4 else key_id

    db = Database()
    now = datetime.utcnow().isoformat()
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT user_id FROM user_secrets WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row:
            conn.execute(
                """UPDATE user_secrets
                   SET alpaca_key_id_enc = ?, alpaca_secret_enc = ?,
                       alpaca_key_id_tail = ?, updated_at = ?
                   WHERE user_id = ?""",
                (key_enc, sec_enc, tail, now, user_id),
            )
        else:
            conn.execute(
                """INSERT INTO user_secrets
                   (user_id, alpaca_key_id_enc, alpaca_secret_enc,
                    alpaca_key_id_tail, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (user_id, key_enc, sec_enc, tail, now),
            )
    logger.info("alpaca keys saved for user_id=%s tail=%s", user_id, tail)


def get_alpaca_keys(user_id: int) -> tuple[str, str] | None:
    """Return decrypted (key_id, secret) or None if no row stored."""
    from utils.database import Database

    db = Database()
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT alpaca_key_id_enc, alpaca_secret_enc FROM user_secrets WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    f = _fernet()
    return (
        f.decrypt(bytes(row["alpaca_key_id_enc"])).decode(),
        f.decrypt(bytes(row["alpaca_secret_enc"])).decode(),
    )


def get_status(user_id: int) -> dict | None:
    """Return {'tail': '...XYZ', 'updated_at': '...'} or None."""
    from utils.database import Database

    db = Database()
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT alpaca_key_id_tail, updated_at FROM user_secrets WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    return {"tail": row["alpaca_key_id_tail"], "updated_at": row["updated_at"]}


def delete_alpaca_keys(user_id: int) -> None:
    from utils.database import Database

    db = Database()
    with db._get_conn() as conn:
        conn.execute("DELETE FROM user_secrets WHERE user_id = ?", (user_id,))
    logger.info("alpaca keys deleted for user_id=%s", user_id)


def user_id_for_email(email: str) -> int | None:
    """Resolve a user row id by email. Convenience for dashboard code paths
    that only have the signed-in user's email from IAP headers.
    """
    from utils.database import Database

    db = Database()
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT id FROM users WHERE email = ?", (email.strip().lower(),)
        ).fetchone()
    return row["id"] if row else None
