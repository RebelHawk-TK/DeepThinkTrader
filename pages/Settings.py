"""Settings — self-serve Alpaca paper API key entry.

Replaces the Phase-D placeholder "send Tom your keys over Signal" step. A
signed-in user pastes their Alpaca Key ID + Secret; we test them against the
paper endpoint, encrypt with Fernet, and write to user_secrets.

Decryption happens at bot-cycle time (Phase C wiring — not yet in place).
Until that lands, saved keys sit encrypted in the DB; Tom still reads them
out to run the bot, but the user never has to transmit them over a back
channel.
"""

from __future__ import annotations

import requests
import streamlit as st

from utils.database import Database
from utils.streamlit_auth import require_auth
from utils import secrets_vault

PAPER_BASE = "https://paper-api.alpaca.markets"


def _user_id(email: str) -> int | None:
    db = Database()
    with db._get_conn() as conn:
        row = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        return row["id"] if row else None


def _test_alpaca(key_id: str, secret: str) -> tuple[bool, str]:
    """Hit /v2/account on the paper endpoint. Returns (ok, message)."""
    try:
        r = requests.get(
            f"{PAPER_BASE}/v2/account",
            headers={
                "APCA-API-KEY-ID": key_id.strip(),
                "APCA-API-SECRET-KEY": secret.strip(),
            },
            timeout=10,
        )
    except Exception as exc:
        return False, f"Network error reaching Alpaca: {exc}"

    if r.status_code == 200:
        data = r.json()
        acct = data.get("account_number", "?")
        status = data.get("status", "?")
        cash = data.get("cash", "?")
        return True, f"Alpaca paper account {acct} — status {status}, cash ${cash}"
    if r.status_code in (401, 403):
        return False, "Alpaca rejected these keys. Double-check you copied both values and that they're from Paper mode."
    return False, f"Alpaca returned {r.status_code}: {r.text[:200]}"


user = require_auth()
st.set_page_config(page_title="Settings", page_icon="⚙️", layout="centered")
st.title("Settings — Alpaca API Keys")
st.caption(
    "Paste your Alpaca **paper** API credentials below. We test them against "
    "Alpaca before saving and store them encrypted at rest. You can rotate "
    "or delete them anytime."
)

uid = _user_id(user["email"])
if not uid:
    st.error("Couldn't resolve your user record. Ping Tom.")
    st.stop()

status = secrets_vault.get_status(uid)

if status:
    st.success(
        f"Keys on file — ending in **…{status['tail']}** "
        f"(saved {status['updated_at']})"
    )
else:
    st.info("No keys saved yet. Enter them below.")

with st.form("alpaca_keys_form", clear_on_submit=True):
    key_id = st.text_input(
        "Alpaca API Key ID",
        placeholder="PKXXXXXXXXXXXXXXXXXX",
        help="20 characters, starts with PK for paper accounts.",
    )
    secret = st.text_input(
        "Alpaca Secret Key",
        type="password",
        placeholder="(40-character secret)",
        help="Shown once by Alpaca at key-generation time. If you lost it, regenerate a new pair.",
    )
    submitted = st.form_submit_button("Test & save", use_container_width=True)

if submitted:
    if not key_id or not secret:
        st.error("Both fields are required.")
    else:
        with st.spinner("Testing against Alpaca paper endpoint…"):
            ok, msg = _test_alpaca(key_id, secret)
        if not ok:
            st.error(msg)
        else:
            try:
                secrets_vault.set_alpaca_keys(uid, key_id, secret)
            except Exception as exc:
                st.error(f"Keys validated, but saving failed: {exc}")
            else:
                st.success(f"Saved. {msg}")
                st.rerun()

st.divider()

if status:
    with st.expander("Danger zone"):
        st.write(
            "Delete removes your keys from our database. The bot will stop "
            "trading on your behalf at the next cycle. You can re-enter keys "
            "anytime."
        )
        if st.button("Delete keys", type="primary"):
            secrets_vault.delete_alpaca_keys(uid)
            st.toast("Keys deleted.", icon="🗑️")
            st.rerun()
