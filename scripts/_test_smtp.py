"""Quick end-to-end SMTP test — sends a one-line email from Tom's Gmail
using the Keychain-stored app password. No attachment, just verifies auth."""

from __future__ import annotations

import smtplib
import ssl
import subprocess
import sys


def main(to_addr: str):
    pw = subprocess.run(
        ["security", "find-generic-password", "-s", "dtt-smtp-password", "-w"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    user = "tom@brigitteandtom.com"

    from email.message import EmailMessage
    msg = EmailMessage()
    msg["Subject"] = "SMTP test — DeepThinkTrader"
    msg["From"] = user
    msg["To"] = to_addr
    msg.set_content("If you received this, Gmail SMTP works end-to-end.")

    ctx = ssl.create_default_context()
    print(f"length: {len(pw)}, connecting to smtp.gmail.com:587…")
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
        s.set_debuglevel(1)
        s.starttls(context=ctx)
        s.login(user, pw)
        s.send_message(msg)
    print(f"sent to {to_addr}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "tom@brigitteandtom.com")
