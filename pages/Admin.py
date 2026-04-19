"""Admin page — control which users can access the dashboard.

Visible only to role=admin users. Lists every row in the users table and
lets the admin toggle enabled / promote / demote / delete. All actions write
straight through to Postgres so the next page refresh reflects them.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime

import pandas as pd
import streamlit as st

from utils.database import Database
from utils.streamlit_auth import require_auth
from utils import iap_admin


DASHBOARD_URL = "https://trader.travelforge.ai"


def _mailto_url(email: str) -> str:
    """Build a mailto: URL with a pre-filled DeepThinkTrader welcome message."""
    subject = "You're in — DeepThinkTrader"
    body = (
        f"You now have access to DeepThinkTrader. Sign in with this Google "
        f"account at:\n\n{DASHBOARD_URL}\n\n"
        f"On first sign-in you'll see 'Account pending approval' — ping me "
        f"when you land there and I'll flip the toggle.\n\n"
        f"Onboarding guide: see the PDF attached to my separate email."
    )
    return f"mailto:{email}?subject={urllib.parse.quote(subject)}&body={urllib.parse.quote(body)}"


def _queue_notify(email: str) -> None:
    """Remember that this email needs a notification; rendered at top of page."""
    st.session_state.setdefault("pending_notifies", [])
    if email not in st.session_state["pending_notifies"]:
        st.session_state["pending_notifies"].append(email)


def _list_users() -> list[dict]:
    db = Database()
    with db._get_conn() as conn:
        rows = conn.execute(
            """SELECT id, email, name, role, enabled, created_at, last_login_at
               FROM users ORDER BY created_at DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


def _set_enabled(user_id: int, enabled: bool) -> None:
    db = Database()
    with db._get_conn() as conn:
        conn.execute("UPDATE users SET enabled = ? WHERE id = ?", (enabled, user_id))


def _set_role(user_id: int, role: str) -> None:
    if role not in ("admin", "user"):
        raise ValueError(f"Invalid role: {role}")
    db = Database()
    with db._get_conn() as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))


def _delete_user(user_id: int, email: str) -> None:
    db = Database()
    with db._get_conn() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    # Revoke their IAP access too so a deleted invitee can't sign back in
    # until re-invited. Swallow errors — the user row is already gone and
    # the admin can retry via a refresh.
    try:
        iap_admin.revoke(email)
    except Exception as exc:
        import streamlit as st
        st.warning(f"User deleted, but IAP revoke failed: {exc}")


def _invite(email: str, role: str) -> tuple[bool, str]:
    """Add to IAP allowlist + upsert users row (pre-approved).

    Returns (ok, message). On any exception, bails out before the users-table
    write so an IAP-API failure doesn't leave a stale enabled row.
    """
    email = email.strip().lower()
    if not email or "@" not in email:
        return False, "Enter a valid email."
    if role not in ("admin", "user"):
        return False, f"Invalid role: {role}"

    try:
        iap_admin.invite(email)
    except Exception as exc:
        return False, f"IAP invite failed: {exc}"

    db = Database()
    now = datetime.utcnow().isoformat()
    with db._get_conn() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET role = ?, enabled = true WHERE email = ?",
                (role, email),
            )
        else:
            conn.execute(
                """INSERT INTO users (email, role, enabled, created_at, last_login_at)
                   VALUES (?, ?, true, ?, ?)""",
                (email, role, now, None),
            )
    return True, f"Invited {email}. Share {DASHBOARD_URL}."


def _format_ts(raw) -> str:
    if not raw:
        return "—"
    if isinstance(raw, datetime):
        return raw.strftime("%Y-%m-%d %H:%M UTC")
    s = str(raw)
    # ISO strings from SQLite → trim microseconds / tz for readability
    return s.replace("T", " ").split(".")[0][:16] + " UTC"


# ── Access control ─────────────────────────────────────────────────

user = require_auth()
if user["role"] != "admin":
    from utils.brand import ICON_PATH as _IC
    st.set_page_config(page_title="Admin", page_icon=_IC)
    st.error("This page is admin-only.")
    st.stop()

from utils.brand import ICON_PATH as _ICON
from utils.theme import apply_theme
st.set_page_config(page_title="Admin", page_icon=_ICON, layout="wide")
apply_theme()
st.title("Admin — User Access")
st.caption(
    "Invite a friend/family member below — we'll grant them IAP access and "
    "pre-enable their account. Deleting a user removes their IAP access too, "
    "so they can't sign back in until re-invited. **Heads up:** granting IAP "
    "access does NOT email the user — click the mail link after inviting to "
    "notify them yourself."
)

# ── Pending notifications banner (IAP grant succeeded, now notify the human) ──
pending = st.session_state.get("pending_notifies", [])
if pending:
    with st.container(border=True):
        st.markdown("**📬 Send sign-in link to:**")
        cols = st.columns(len(pending) + 1)
        for i, em in enumerate(pending):
            with cols[i]:
                st.markdown(
                    f"<a href='{_mailto_url(em)}' target='_blank' "
                    f"style='display:block;padding:6px 12px;background:#00D084;"
                    f"color:#0B0E14;border-radius:6px;text-decoration:none;"
                    f"font-weight:600;text-align:center;font-size:0.85rem;'>"
                    f"✉ {em}</a>",
                    unsafe_allow_html=True,
                )
        with cols[-1]:
            if st.button("Dismiss all", use_container_width=True):
                st.session_state["pending_notifies"] = []
                st.rerun()

# ── Invite form ───────────────────────────────────────────────────
with st.expander("Invite a user", expanded=False):
    with st.form("invite_form", clear_on_submit=True):
        c_email, c_role, c_submit = st.columns([3, 1, 1])
        with c_email:
            invite_email = st.text_input(
                "Email",
                placeholder="friend@example.com",
                label_visibility="collapsed",
            )
        with c_role:
            invite_role = st.selectbox(
                "Role", ["user", "admin"], label_visibility="collapsed"
            )
        with c_submit:
            submitted = st.form_submit_button("Invite", use_container_width=True)
        if submitted:
            ok, msg = _invite(invite_email, invite_role)
            if ok:
                st.success(msg)
                st.code(DASHBOARD_URL, language=None)
                _queue_notify(invite_email.strip().lower())
            else:
                st.error(msg)

users = _list_users()

if not users:
    st.info("No users yet. Invite someone above, or sign in yourself.")
    st.stop()

# Summary counters at the top
total = len(users)
enabled_n = sum(1 for u in users if u["enabled"])
admin_n = sum(1 for u in users if u["role"] == "admin")
pending_n = total - enabled_n

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total users", total)
c2.metric("Enabled", enabled_n)
c3.metric("Pending", pending_n)
c4.metric("Admins", admin_n)

st.divider()

# Inline row controls — one container per user for a compact list
for u in users:
    with st.container(border=True):
        col_info, col_role, col_enabled, col_resend, col_danger = st.columns([3, 1.5, 1, 1, 1])

        with col_info:
            st.markdown(f"**{u['email']}**")
            meta = []
            if u.get("name"):
                meta.append(u["name"])
            meta.append(f"joined {_format_ts(u.get('created_at'))}")
            meta.append(f"last login {_format_ts(u.get('last_login_at'))}")
            st.caption(" · ".join(meta))

        with col_role:
            # Prevent admins from demoting themselves (would lock them out)
            is_self = u["email"].lower() == user["email"].lower()
            role_options = ["user", "admin"]
            new_role = st.selectbox(
                "Role",
                role_options,
                index=role_options.index(u["role"]),
                key=f"role_{u['id']}",
                disabled=is_self,
                label_visibility="collapsed",
            )
            if new_role != u["role"]:
                _set_role(u["id"], new_role)
                st.rerun()

        with col_enabled:
            is_self = u["email"].lower() == user["email"].lower()
            new_enabled = st.toggle(
                "Enabled",
                value=bool(u["enabled"]),
                key=f"enabled_{u['id']}",
                disabled=is_self,
                label_visibility="collapsed",
            )
            if new_enabled != bool(u["enabled"]):
                _set_enabled(u["id"], new_enabled)
                st.rerun()

        with col_resend:
            if st.button(
                "Resend",
                key=f"resend_{u['id']}",
                use_container_width=True,
                help="Re-add this user's email to the IAP allowlist. "
                     "Idempotent — safe to click if they already have access.",
            ):
                try:
                    iap_admin.invite(u["email"])
                    _queue_notify(u["email"])
                    st.toast(f"IAP access granted — now email them", icon="📩")
                except Exception as exc:
                    st.error(f"Resend failed: {exc}")

        with col_danger:
            is_self = u["email"].lower() == user["email"].lower()
            if st.button(
                "Delete",
                key=f"delete_{u['id']}",
                disabled=is_self,
                use_container_width=True,
            ):
                _delete_user(u["id"], u["email"])
                st.toast(f"Deleted {u['email']}", icon="🗑️")
                st.rerun()
