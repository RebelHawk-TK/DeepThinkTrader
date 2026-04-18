"""Thin wrapper around Google Secret Manager for system-wide secrets.

Used in cloud deploys (Cloud Run) where keychain isn't available. Falls back to
env vars so local Docker dev works without touching GCP. System secrets = those
shared by all users (e.g. Anthropic API key, news API keys). User-specific
secrets (Alpaca keys) come from Firestore, not here.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

log = logging.getLogger(__name__)

# Project ID is set by Cloud Run automatically; locally, read from env.
_PROJECT_ID = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT")


@lru_cache(maxsize=64)
def get_secret(name: str, env_fallback: str | None = None) -> str | None:
    """Load a secret by name from Secret Manager, falling back to env var.

    Args:
        name: Secret Manager secret ID (e.g. "ANTHROPIC_API_KEY")
        env_fallback: env var name to try if Secret Manager is unavailable.
            Defaults to `name` itself.

    Returns:
        Secret value or None if not found.
    """
    env_key = env_fallback or name
    env_val = os.getenv(env_key)

    if not _PROJECT_ID:
        return env_val or None

    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        path = f"projects/{_PROJECT_ID}/secrets/{name}/versions/latest"
        response = client.access_secret_version(request={"name": path})
        return response.payload.data.decode("utf-8")
    except Exception as e:
        log.debug("Secret Manager lookup failed for %s: %s — falling back to env", name, e)
        return env_val or None
