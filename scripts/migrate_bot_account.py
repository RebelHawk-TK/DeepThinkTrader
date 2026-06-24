#!/usr/bin/env python3
"""One-shot migration: move the bot to a dedicated Alpaca paper account.

Resume-gate #5 (see docs/status_2026-06-23.md): the bot must size off its own
~$20k sleeve, not the ~$92k account that also holds Tom's manual ETF allocation.
This closes the bot's open positions in the OLD account, then repoints the bot's
stored keys to the NEW (dedicated) account.

Run it AT/AFTER market open so the position close fills on a real trade, with the
new account's keys in the environment:

    cd ~/Projects/StockTrader
    NEW_ALPACA_KEY_ID=PK... NEW_ALPACA_SECRET=... .venv/bin/python scripts/migrate_bot_account.py

Order of operations (each step aborts the run on failure, before anything is swapped):
  1. Validate the NEW keys connect and resolve a DIFFERENT account than the old one.
  2. Require market open (so position closes fill for real). --force to override.
  3. Close every bot-managed open position in the OLD account (records real exits).
  4. Confirm the bot's DB has zero open trades.
  5. Swap stored keys to the NEW account (Fernet-encrypted into user_secrets).
  6. Re-verify the bot now reads the NEW account: equity, zero positions.
  7. Print the restart command.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.secrets_vault import get_alpaca_keys, set_alpaca_keys
from agents.execution_agent import ExecutionAgent
from alpaca.trading.client import TradingClient

USER_ID = 1
FORCE = "--force" in sys.argv


def die(msg: str) -> "None":
    print(f"\n❌ ABORT: {msg}")
    sys.exit(1)


def main() -> None:
    new_key = os.getenv("NEW_ALPACA_KEY_ID")
    new_secret = os.getenv("NEW_ALPACA_SECRET")
    if not new_key or not new_secret:
        die("set NEW_ALPACA_KEY_ID and NEW_ALPACA_SECRET in the environment.")

    old = get_alpaca_keys(USER_ID)
    if not old:
        die(f"no existing Alpaca keys for user {USER_ID}.")
    old_key, old_secret = old

    # 1. Validate NEW keys BEFORE touching anything — never clobber working keys with bad ones.
    print("1. Validating new account keys...")
    try:
        new_client = TradingClient(api_key=new_key, secret_key=new_secret, paper=True)
        new_acct = new_client.get_account()
    except Exception as e:
        die(f"new keys do not connect: {e}")
    old_client = TradingClient(api_key=old_key, secret_key=old_secret, paper=True)
    old_acct = old_client.get_account()
    if new_acct.account_number == old_acct.account_number:
        die(f"new keys resolve the SAME account ({old_acct.account_number}). "
            "Generate keys for a NEW paper account.")
    new_eq = float(new_acct.equity)
    new_pos = new_client.get_all_positions()
    print(f"   new account {new_acct.account_number}: equity ${new_eq:,.2f}, {len(new_pos)} positions")
    print(f"   old account {old_acct.account_number}: equity ${float(old_acct.equity):,.2f}")
    if new_eq > 50_000:
        print(f"   ⚠️  new account equity ${new_eq:,.0f} is high — was it funded to the intended "
              "sleeve (~$20k)? Re-creating the inflation defeats the purpose. Continuing.")

    # 2. Market-open guard — position closes must fill on a real trade.
    if not old_client.get_clock().is_open:
        if not FORCE:
            die("market is CLOSED. Run at/after 09:30 ET so the close fills real, "
                "or pass --force to queue it.")
        print("2. Market closed but --force given — close will queue for next open.")
    else:
        print("2. Market is open.")

    # 3. Close every bot-managed open position in the OLD account.
    ea = ExecutionAgent(USER_ID, old_key, old_secret)
    open_trades = ea.db.get_open_trades(USER_ID)
    print(f"3. Closing {len(open_trades)} bot-managed position(s) in the old account...")
    for t in open_trades:
        res = ea.manual_close(t["ticker"], portfolio=t.get("portfolio", "main"),
                              note="account migration 2026-06-24")
        status = res.get("status")
        print(f"   {t['ticker']}: {status} — {res.get('message', '')} "
              f"(exit ${res.get('exit_price', '?')}, P&L ${res.get('pnl', '?')})")
        if status != "OK":
            die(f"failed to close {t['ticker']} — not swapping keys. Resolve manually and rerun.")

    # 4. Confirm DB is flat.
    remaining = ea.db.get_open_trades(USER_ID)
    if remaining:
        die(f"{len(remaining)} open trade(s) still in DB after close: "
            f"{[t['ticker'] for t in remaining]}. Not swapping keys.")
    print("4. Bot DB confirmed flat (0 open trades).")

    # 5. Swap stored keys to the NEW account.
    set_alpaca_keys(USER_ID, new_key, new_secret)
    print(f"5. Stored keys swapped to new account (tail {new_key[-4:]}).")

    # 6. Re-verify the bot now reads the NEW account.
    rk = get_alpaca_keys(USER_ID)
    if not rk or rk[0] != new_key:
        die("post-swap read-back does not match new key — investigate user_secrets.")
    chk = TradingClient(api_key=rk[0], secret_key=rk[1], paper=True)
    a = chk.get_account()
    p = chk.get_all_positions()
    print(f"6. Bot now reads account {a.account_number}: equity ${float(a.equity):,.2f}, {len(p)} positions")

    print("\n✅ Migration complete. Restart the bot to load the new keys:")
    print(f"   launchctl kickstart -k gui/{os.getuid()}/com.deepthinktrader.bot")
    print("\n   The OLD account now holds only your manual ETF allocation, untouched.")


if __name__ == "__main__":
    main()
