"""IAP IAM policy mutations for the trader-backend backend service.

Used by pages/Admin.py to invite and uninvite users. The dashboard runs under
a dedicated service account (trader-dashboard-sa) with roles/iap.admin scoped
by IAM condition to `projects/*/iap_web/compute/services/trader-backend` ONLY,
so a compromised dashboard can't mutate IAP for other resources in the
project.

Uses Google's REST API directly via ADC + AuthorizedSession. No extra SDK.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_PROJECT_NUMBER = os.getenv("GCP_PROJECT_NUMBER", "999702382511")
_BACKEND = os.getenv("IAP_BACKEND_SERVICE", "trader-backend")
_ROLE = "roles/iap.httpsResourceAccessor"


def _iap_resource() -> str:
    return (
        f"https://iap.googleapis.com/v1/projects/{_PROJECT_NUMBER}"
        f"/iap_web/compute/services/{_BACKEND}"
    )


def _session():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return AuthorizedSession(creds)


def _get_policy() -> dict[str, Any]:
    sess = _session()
    resp = sess.post(f"{_iap_resource()}:getIamPolicy", json={})
    resp.raise_for_status()
    return resp.json()


def _set_policy(policy: dict[str, Any]) -> dict[str, Any]:
    sess = _session()
    resp = sess.post(f"{_iap_resource()}:setIamPolicy", json={"policy": policy})
    resp.raise_for_status()
    return resp.json()


def _member(email: str) -> str:
    return f"user:{email.strip().lower()}"


def invite(email: str) -> None:
    """Add `email` to the trader-backend IAP allowlist. Idempotent."""
    m = _member(email)
    policy = _get_policy()
    bindings = policy.setdefault("bindings", [])
    for b in bindings:
        if b.get("role") == _ROLE:
            members = b.setdefault("members", [])
            if m not in members:
                members.append(m)
            _set_policy(policy)
            logger.info("IAP invite: %s added to %s", m, _BACKEND)
            return
    # No existing binding for this role — append a fresh one
    bindings.append({"role": _ROLE, "members": [m]})
    _set_policy(policy)
    logger.info("IAP invite: %s added to %s (new binding)", m, _BACKEND)


def revoke(email: str) -> None:
    """Remove `email` from the trader-backend IAP allowlist. Idempotent."""
    m = _member(email)
    policy = _get_policy()
    bindings = policy.get("bindings", [])
    changed = False
    for b in list(bindings):
        if b.get("role") != _ROLE:
            continue
        if m in b.get("members", []):
            b["members"].remove(m)
            changed = True
        # Clean up an empty binding so the policy stays tidy.
        if not b.get("members"):
            bindings.remove(b)
            changed = True
    if changed:
        _set_policy(policy)
        logger.info("IAP revoke: %s removed from %s", m, _BACKEND)
    else:
        logger.debug("IAP revoke: %s was not bound — no change", m)


def list_invited() -> list[str]:
    """Return emails currently bound to roles/iap.httpsResourceAccessor."""
    policy = _get_policy()
    emails: list[str] = []
    for b in policy.get("bindings", []):
        if b.get("role") != _ROLE:
            continue
        for m in b.get("members", []):
            if m.startswith("user:"):
                emails.append(m[len("user:"):])
    return emails
