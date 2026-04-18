"""Dashboard access gate for cloud deployment.

Phase B: single shared password pulled from GCP Secret Manager. Guards the
Streamlit dashboard so only the operator can see live trade data. Phase D
replaces this with per-user Firebase Auth tokens.

Usage (in dashboard.py, before any other rendering):

    from utils.streamlit_auth import require_auth
    require_auth()

Opt in by setting env var DASHBOARD_AUTH_REQUIRED=1 on Cloud Run. On the Mac
dev dashboard (no env var set) this is a no-op — local access is trusted.
"""

from __future__ import annotations

import hmac
import logging
import os
from functools import lru_cache

logger = logging.getLogger(__name__)


def _auth_required() -> bool:
    return os.getenv("DASHBOARD_AUTH_REQUIRED") == "1"


@lru_cache(maxsize=1)
def _expected_password() -> str:
    """Fetch dashboard password from Secret Manager on first call."""
    from utils.gcp_secrets import get_secret

    pw = get_secret("DASHBOARD_PASSWORD", env_fallback="DASHBOARD_PASSWORD")
    if not pw:
        logger.error(
            "DASHBOARD_AUTH_REQUIRED=1 but DASHBOARD_PASSWORD secret not set — "
            "dashboard will refuse all access until resolved."
        )
    return pw or ""


def require_auth() -> None:
    """Block dashboard rendering until the user authenticates."""
    if not _auth_required():
        return

    import streamlit as st

    # Session-state gate — once authed, the rest of the app renders.
    if st.session_state.get("_auth_ok"):
        return

    # Narrow, centered login card
    st.set_page_config(page_title="DeepThinkTrader", page_icon="📈", layout="centered")
    st.markdown("### DeepThinkTrader")
    st.caption("Sign in to view trade history.")

    with st.form("login", clear_on_submit=False):
        pw = st.text_input("Password", type="password")
        submit = st.form_submit_button("Sign in")

    if submit:
        expected = _expected_password()
        if expected and hmac.compare_digest(pw, expected):
            st.session_state["_auth_ok"] = True
            st.rerun()
        else:
            st.error("Invalid password.")

    st.stop()
