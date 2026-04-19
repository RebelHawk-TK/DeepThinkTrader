"""Send the DeepThinkTrader welcome email with onboarding PDF attached.

Uses Gmail SMTP with an app password. The password lives in GCP Secret
Manager as ``trader-smtp-password``; the sending address is taken from the
``SMTP_USER`` env (also used as auth username). Both the dashboard and bot
service accounts have secretAccessor on the secret.

If credentials are missing or SMTP errors, ``send_invite`` returns
``(False, reason)`` so the caller can fall back to the mailto banner.
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from functools import lru_cache

logger = logging.getLogger(__name__)

_SECRET_NAME = os.getenv("SMTP_PASSWORD_SECRET", "trader-smtp-password")
_PROJECT = os.getenv("GCP_PROJECT", "travelforge-app")
_SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
_SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

DASHBOARD_URL = "https://trader.travelforge.ai"


@lru_cache(maxsize=1)
def _password() -> str | None:
    env = os.getenv("SMTP_PASSWORD")
    if env:
        return env
    try:
        from google.cloud import secretmanager
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{_PROJECT}/secrets/{_SECRET_NAME}/versions/latest"
        resp = client.access_secret_version(name=name)
        return resp.payload.data.decode()
    except Exception as exc:
        logger.warning("SMTP password unavailable: %s", exc)
        return None


def _compose(to_email: str, from_email: str, pdf_path: str | None) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = "You're in — DeepThinkTrader"
    msg["From"] = from_email
    msg["To"] = to_email
    msg.set_content(
        f"You now have access to DeepThinkTrader.\n\n"
        f"Sign in with this Google account at:\n{DASHBOARD_URL}\n\n"
        f"On first sign-in you'll see 'Account pending approval' — ping me "
        f"when you land there and I'll flip the toggle.\n\n"
        f"The onboarding guide is attached — it covers the Alpaca paper "
        f"account setup, API keys, and a tour of every dashboard page.\n\n"
        f"— Tom"
    )
    if pdf_path and os.path.exists(pdf_path):
        with open(pdf_path, "rb") as f:
            msg.add_attachment(
                f.read(),
                maintype="application",
                subtype="pdf",
                filename="DeepThinkTrader-onboarding.pdf",
            )
    return msg


def send_invite(to_email: str, pdf_path: str | None = None) -> tuple[bool, str]:
    """Send the welcome email. Returns (ok, message-or-error-reason)."""
    user = os.getenv("SMTP_USER", "").strip()
    from_addr = os.getenv("SMTP_FROM", user).strip()
    if not user:
        return False, "SMTP_USER not configured"
    pw = _password()
    if not pw:
        return False, f"secret {_SECRET_NAME} not readable"

    msg = _compose(to_email, from_addr, pdf_path)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT, timeout=20) as s:
            s.starttls(context=ctx)
            s.login(user, pw)
            s.send_message(msg)
        logger.info("invite email sent to %s", to_email)
        return True, f"Sent to {to_email}"
    except smtplib.SMTPAuthenticationError as exc:
        return False, f"Gmail auth rejected — check app password ({exc.smtp_code})"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
