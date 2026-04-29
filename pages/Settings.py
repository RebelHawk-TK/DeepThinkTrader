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
from utils.brand import ICON_PATH as _ICON
from utils.theme import apply_theme
st.set_page_config(page_title="Settings", page_icon=_ICON, layout="centered")
apply_theme()
st.title("Settings — API Keys")
st.caption(
    "Two scopes: **per-user** Alpaca keys (encrypted in the database, used "
    "by the bot to trade on your account), and **system-wide** API keys "
    "(stored in the macOS Keychain on the bot host, shared across all users). "
    "All key fields use password-style inputs and never display the full value."
)

st.subheader("Per-user — Alpaca paper trading")

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
    from utils.brand import HERO_NO_KEYS
    st.image(HERO_NO_KEYS, use_container_width=True)
    st.info("No keys saved yet. Enter them below to connect your Alpaca paper account.")

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

st.divider()

# ─────────────────────────────────────────────────────────────────────
# System-wide API keys (stored in macOS Keychain)
# ─────────────────────────────────────────────────────────────────────

st.subheader("System-wide — research & AI APIs")
st.caption(
    "These keys live in the macOS Keychain on the bot host. Editing here "
    "updates Keychain immediately and the bot picks up new values on its "
    "next process restart. Leaving a field blank keeps the current value."
)

# Keychain access — module sits at repo root, importable when Streamlit
# adds the project dir to sys.path (same pattern as utils.* imports).
try:
    from keychain_config import load_secrets, update_secret
    _kc_available = True
except Exception as _kc_err:
    _kc_available = False
    st.warning(f"Keychain integration unavailable: {_kc_err}")

# (keychain_key, display_name, help_text, console_url)
_API_SPECS = [
    ("anthropic_api_key", "Anthropic Claude",
     "Powers per-ticker analyst + bull/bear debate. Haiku model.",
     "https://console.anthropic.com"),
    ("newsapi_key", "NewsAPI.org",
     "Free tier: 100 calls/day. General news fallback when aggregator quota lower-tier sources run out.",
     "https://newsapi.org"),
    ("stocknewsapi_key", "Stock News API",
     "Aggregates financial news; returns sentiment-tagged articles per ticker.",
     "https://stocknewsapi.com"),
    ("marketaux_api_key", "Marketaux",
     "Entity-level sentiment scores. Free tier: 100 calls/day — bot gates to top-3 priority tickers.",
     "https://marketaux.com"),
    ("alphavantage_api_key", "Alpha Vantage",
     "Time-series + news sentiment. Free tier: 25 calls/day, 5 calls/min.",
     "https://www.alphavantage.co"),
    ("fmp_api_key", "Financial Modeling Prep",
     "Currently disabled in config.py (free tier no longer includes news). Key kept in case you upgrade.",
     "https://financialmodelingprep.com"),
    ("rapidapi_key", "RapidAPI",
     "Generic key for any RapidAPI-routed services (e.g. Twelve Data via RapidAPI).",
     "https://rapidapi.com"),
    ("reddit_client_id", "Reddit Client ID",
     "OAuth client for PRAW — feeds the Reddit sentiment scanner. Pair with the secret below.",
     "https://www.reddit.com/prefs/apps"),
    ("reddit_client_secret", "Reddit Client Secret",
     "Pair with the Reddit Client ID above.",
     "https://www.reddit.com/prefs/apps"),
]

if _kc_available:
    _current = load_secrets() or {}
    for kc_key, label, help_text, console_url in _API_SPECS:
        cur_val = (_current.get(kc_key) or "").strip()
        if cur_val:
            tail = cur_val[-6:] if len(cur_val) >= 6 else cur_val
            status_label = f"Set (…{tail})"
            status_emoji = "🟢"
        else:
            status_label = "Not set"
            status_emoji = "⚪"

        with st.expander(f"{status_emoji}  **{label}** — {status_label}", expanded=False):
            st.caption(f"{help_text}  ·  [Console]({console_url})")
            with st.form(f"api_form_{kc_key}", clear_on_submit=True):
                new_val = st.text_input(
                    f"New value for {label}",
                    type="password",
                    key=f"api_input_{kc_key}",
                    placeholder="Paste new key (leave blank to keep current)",
                    label_visibility="collapsed",
                )
                cols = st.columns([3, 1])
                save_clicked = cols[0].form_submit_button(
                    "Save to Keychain", use_container_width=True
                )
                clear_clicked = cols[1].form_submit_button(
                    "Clear", use_container_width=True, type="secondary",
                )
            if save_clicked:
                if not new_val.strip():
                    st.warning("No value entered — kept current.")
                else:
                    try:
                        update_secret(kc_key, new_val.strip())
                        st.success(f"{label} updated. Restart the bot to pick up the new value.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Save failed: {exc}")
            elif clear_clicked:
                try:
                    update_secret(kc_key, "")
                    st.toast(f"{label} cleared.", icon="🗑️")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Clear failed: {exc}")

st.caption(
    "💡 The bot reads these on process startup. After updating any key, "
    "restart the bot (`launchctl unload && launchctl load "
    "~/Library/LaunchAgents/com.deepthinktrader.bot.plist`) for the "
    "new value to take effect."
)
