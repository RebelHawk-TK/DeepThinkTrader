"""One-shot: flatten Alpaca paper positions for a given user_id.

Pulls Fernet key from Secret Manager, connects to Cloud SQL via local proxy
(127.0.0.1:5433 — start `cloud-sql-proxy travelforge-app:us-central1:trader-db
--port 5433` beforehand), reads the encrypted Alpaca keys from user_secrets,
then calls Alpaca's DELETE /v2/positions to close everything.

Usage:
    python scripts/liquidate_stale.py <user_id>
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request

import psycopg
from cryptography.fernet import Fernet
from google.cloud import secretmanager

PROJECT = "travelforge-app"
DB_PASSWORD = "XiUlKeX7OBNPd62GBCvEAiZDvidO75n1"
DB_DSN = f"host=127.0.0.1 port=5433 user=trader password={DB_PASSWORD} dbname=trader"
ALPACA_BASE = "https://paper-api.alpaca.markets"


def fernet() -> Fernet:
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{PROJECT}/secrets/trader-fernet-key/versions/latest"
    resp = client.access_secret_version(name=name)
    return Fernet(resp.payload.data)


def load_keys(user_id: int) -> tuple[str, str]:
    f = fernet()
    with psycopg.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT alpaca_key_id_enc, alpaca_secret_enc FROM user_secrets WHERE user_id=%s",
            (user_id,),
        )
        row = cur.fetchone()
    if not row:
        raise SystemExit(f"no user_secrets row for user_id={user_id}")
    key = f.decrypt(row[0].encode() if isinstance(row[0], str) else bytes(row[0])).decode()
    secret = f.decrypt(row[1].encode() if isinstance(row[1], str) else bytes(row[1])).decode()
    return key, secret


def alpaca(method: str, path: str, key: str, secret: str) -> tuple[int, str]:
    req = urllib.request.Request(
        f"{ALPACA_BASE}{path}",
        method=method,
        headers={"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def main() -> int:
    uid = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    key, secret = load_keys(uid)
    print(f"keys loaded for user_id={uid} (ending …{key[-4:]})")

    # Snapshot before
    code, body = alpaca("GET", "/v2/positions", key, secret)
    positions = json.loads(body) if code == 200 else []
    print(f"open positions before: {len(positions)}")
    for p in positions:
        print(f"  {p['symbol']:6} qty={p['qty']:>8}  mkt=${float(p['market_value']):>10,.2f}  pnl=${float(p['unrealized_pl']):>8,.2f}")

    if not positions:
        print("nothing to liquidate. done.")
        return 0

    # Cancel open orders first so they don't race with position closes
    code, body = alpaca("DELETE", "/v2/orders", key, secret)
    print(f"cancel-all-orders → HTTP {code}")

    # Close all positions
    code, body = alpaca("DELETE", "/v2/positions?cancel_orders=true", key, secret)
    print(f"close-all-positions → HTTP {code}")
    print(body[:400])

    # Verify
    import time
    time.sleep(3)
    code, body = alpaca("GET", "/v2/positions", key, secret)
    remaining = json.loads(body) if code == 200 else []
    print(f"open positions after: {len(remaining)}")
    return 0 if not remaining else 1


if __name__ == "__main__":
    sys.exit(main())
