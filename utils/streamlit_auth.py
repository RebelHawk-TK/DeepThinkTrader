"""Reads the authenticated user from Google Cloud IAP's signed header.

Phase B+: the dashboard sits behind an HTTPS Load Balancer with Identity-
Aware Proxy enabled. IAP handles Google OAuth at the edge and forwards
`X-Goog-Authenticated-User-Email` on every authenticated request. Cloud
Run ingress is restricted to internal + load-balancer traffic, so the
header cannot be set by anyone other than IAP.

Header value format: `accounts.google.com:user@example.com` — we strip the
prefix to get the bare email.

Mac dev: DASHBOARD_AUTH_REQUIRED unset → return a synthetic admin so the
local dashboard experience is unchanged.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

_IAP_EMAIL_HEADER = "X-Goog-Authenticated-User-Email"
# Hitting this URL clears the IAP session cookie and forces re-auth next visit.
# Reference: https://cloud.google.com/iap/docs/sessions-howto
_SIGNOUT_URL = "https://trader.travelforge.ai/?gcp-iap-mode=CLEAR_LOGIN_COOKIE"


def render_session_sidebar(user: dict) -> None:
    """Show signed-in email + sign-out link in the sidebar. Call after require_auth()."""
    import streamlit as st

    st.sidebar.markdown(
        f"""<div style='padding:12px 8px;border-top:1px solid #2A3446;
                         margin-top:12px;font-size:0.85rem;color:#7D8590;'>
            Signed in as<br>
            <span style='color:#E6EDF3;font-weight:600;'>{user['email']}</span><br>
            <a href='{_SIGNOUT_URL}' target='_self'
               style='color:#00D084;text-decoration:none;font-size:0.8rem;'>Sign out</a>
        </div>""",
        unsafe_allow_html=True,
    )


def _auth_required() -> bool:
    return os.getenv("DASHBOARD_AUTH_REQUIRED") == "1"


def _current_email_from_iap() -> str | None:
    import streamlit as st

    try:
        headers = st.context.headers  # type: ignore[attr-defined]
    except Exception:
        return None
    if not headers:
        return None

    raw = headers.get(_IAP_EMAIL_HEADER) or headers.get(_IAP_EMAIL_HEADER.lower())
    if not raw:
        return None
    # IAP format: "accounts.google.com:user@example.com"
    return raw.split(":", 1)[-1].strip().lower()


def _load_user(email: str) -> dict | None:
    from utils.database import Database

    db = Database()
    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT email, name, picture_url, role, enabled FROM users WHERE email = ?",
            (email.strip().lower(),),
        ).fetchone()
        if not row:
            return None
        return {
            "email": row["email"],
            "name": row["name"],
            "picture_url": row["picture_url"],
            "role": row["role"],
            "enabled": bool(row["enabled"]),
        }


def _upsert_from_iap(email: str) -> dict:
    """First sighting of an email via IAP → insert a row. Bootstrap admins via
    the ADMIN_EMAILS env var (auto-enabled, role=admin)."""
    from utils.database import Database

    db = Database()
    email_norm = email.strip().lower()
    admins = {e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()}
    is_admin = email_norm in admins

    with db._get_conn() as conn:
        row = conn.execute(
            "SELECT id, role, enabled FROM users WHERE email = ?",
            (email_norm,),
        ).fetchone()
        now = datetime.utcnow().isoformat()
        if row:
            conn.execute("UPDATE users SET last_login_at = ? WHERE email = ?", (now, email_norm))
            if is_admin and row["role"] != "admin":
                conn.execute(
                    "UPDATE users SET role = 'admin', enabled = true WHERE email = ?",
                    (email_norm,),
                )
                return {"email": email_norm, "name": None, "picture_url": None,
                        "role": "admin", "enabled": True}
            return {"email": email_norm, "name": None, "picture_url": None,
                    "role": row["role"], "enabled": bool(row["enabled"])}
        role = "admin" if is_admin else "user"
        enabled = is_admin
        conn.execute(
            """INSERT INTO users (email, role, enabled, created_at, last_login_at)
               VALUES (?, ?, ?, ?, ?)""",
            (email_norm, role, enabled, now, now),
        )
        logger.info("new user via IAP: %s role=%s enabled=%s", email_norm, role, enabled)
        return {"email": email_norm, "name": None, "picture_url": None,
                "role": role, "enabled": enabled}


def require_auth() -> dict:
    """Return the current user, or stop the app with a helpful message.

    On success also renders the signed-in email + Sign out link into the
    sidebar, so every page that calls require_auth() gets the session chrome
    for free.
    """
    if not _auth_required():
        user = {
            "email": "dev@localhost",
            "name": "Local Dev",
            "picture_url": None,
            "role": "admin",
            "enabled": True,
        }
        try:
            render_session_sidebar(user)
        except Exception:
            pass
        return user

    import streamlit as st

    email = _current_email_from_iap()
    if not email:
        st.error(
            "Not authenticated. This dashboard is only reachable through "
            "the IAP-protected URL (https://trader.travelforge.ai)."
        )
        st.stop()
        return {}

    user = _load_user(email) or _upsert_from_iap(email)

    if not user["enabled"]:
        from utils.brand import ICON_PATH, HERO_PENDING
        from utils.theme import apply_theme
        st.set_page_config(page_title="DeepThinkTrader", page_icon=ICON_PATH, layout="centered")
        apply_theme()
        st.image(HERO_PENDING, use_container_width=True)
        st.markdown("## Account pending approval")
        st.write(
            f"Hi **{user['email']}** — an admin needs to enable your account "
            "before the dashboard unlocks. This usually takes a few minutes."
        )
        st.caption("You'll see the dashboard as soon as the toggle flips. Try refreshing.")
        st.markdown(
            f"<div style='margin-top:24px;'><a href='{_SIGNOUT_URL}' "
            f"style='color:#00D084;text-decoration:none;font-size:0.9rem;'>"
            f"← Sign out and try a different account</a></div>",
            unsafe_allow_html=True,
        )
        st.stop()
        return {}

    render_session_sidebar(user)
    return user
