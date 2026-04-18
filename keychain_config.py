"""Secure credential storage using macOS Keychain for DeepThinkTrader.

Stores API keys in macOS Keychain via the `security` CLI tool.
Falls back to .env if Keychain entry doesn't exist (for first-time migration).

Usage:
    from keychain_config import load_secrets, save_secrets, migrate_from_env

    secrets = load_secrets()
    # Returns dict: {"alpaca_api_key": "...", "alpaca_secret_key": "...", ...}

    # To manually store/update:
    save_secrets({"alpaca_api_key": "new_key", ...})

    # First-time migration from .env:
    migrate_from_env()
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger(__name__)

# Containers/Linux hosts skip Keychain entirely — they get secrets from env or GCP.
_KEYCHAIN_DISABLED = os.getenv("DISABLE_KEYCHAIN") == "1"

KEYCHAIN_SERVICE = "com.moderndesignconcept"
KEYCHAIN_ACCOUNT = f"{KEYCHAIN_SERVICE}.deepthinktrader"

# Keys we store in Keychain (map: keychain key -> .env variable name)
SECRET_KEYS = {
    "alpaca_api_key": "ALPACA_API_KEY",
    "alpaca_secret_key": "ALPACA_SECRET_KEY",
    "newsapi_key": "NEWSAPI_KEY",
    "reddit_client_id": "REDDIT_CLIENT_ID",
    "reddit_client_secret": "REDDIT_CLIENT_SECRET",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "rapidapi_key": "RAPIDAPI_KEY",
    # Additional news APIs
    "stocknewsapi_key": "STOCK_NEWS_API_KEY",
    "fmp_api_key": "FMP_API_KEY",
    "marketaux_api_key": "MARKETAUX_API_KEY",
    "alphavantage_api_key": "ALPHA_VANTAGE_API_KEY",
}


def save_secrets(data: dict) -> None:
    """Store secrets dict in macOS Keychain."""
    if _KEYCHAIN_DISABLED:
        raise RuntimeError("Keychain disabled (DISABLE_KEYCHAIN=1) — cannot save secrets here")
    json_str = json.dumps(data)

    # Delete existing entry (ignore errors if not found)
    subprocess.run(
        ["security", "delete-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT],
        capture_output=True,
    )

    result = subprocess.run(
        [
            "security", "add-generic-password",
            "-s", KEYCHAIN_SERVICE,
            "-a", KEYCHAIN_ACCOUNT,
            "-w", json_str,
            "-U",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        raise RuntimeError(f"Failed to save to Keychain: {result.stderr.strip()}")

    log.info("Saved DeepThinkTrader secrets to Keychain")


def load_secrets() -> dict | None:
    """Read secrets dict from macOS Keychain. Returns None if not found or disabled."""
    if _KEYCHAIN_DISABLED:
        return None

    result = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", KEYCHAIN_ACCOUNT, "-w"],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        return None

    try:
        return json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        log.error("Keychain entry contains invalid JSON")
        return None


def migrate_from_env() -> None:
    """Migrate secrets from .env file to Keychain."""
    from dotenv import dotenv_values

    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        print("No .env file found — nothing to migrate.")
        return

    env_values = dotenv_values(env_path)
    secrets = {}

    for keychain_key, env_var in SECRET_KEYS.items():
        value = env_values.get(env_var, "")
        if value and value not in ("your_reddit_client_id", "your_reddit_client_secret"):
            secrets[keychain_key] = value

    if not secrets:
        print("No secrets found in .env to migrate.")
        return

    save_secrets(secrets)
    print(f"Migrated {len(secrets)} secrets to Keychain:")
    for k in secrets:
        print(f"  ✓ {k}")

    print("\nNext steps:")
    print("  1. Rotate your API keys on each service dashboard")
    print("  2. Update Keychain with new keys: python3 keychain_config.py update")
    print("  3. Remove secrets from .env (keep only non-secret config)")


def update_secret(key: str, value: str) -> None:
    """Update a single secret in Keychain."""
    secrets = load_secrets() or {}
    secrets[key] = value
    save_secrets(secrets)
    print(f"Updated '{key}' in Keychain")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "update":
        # Interactive update mode
        secrets = load_secrets() or {}
        print("Current keys in Keychain:")
        for k in SECRET_KEYS:
            status = "✓ set" if secrets.get(k) else "✗ missing"
            print(f"  {k}: {status}")
        print("\nTo update a key: python3 keychain_config.py update <key> <value>")
        if len(sys.argv) == 4:
            update_secret(sys.argv[2], sys.argv[3])
    else:
        print("Migrating DeepThinkTrader secrets from .env to Keychain...")
        migrate_from_env()
