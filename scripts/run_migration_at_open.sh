#!/bin/bash
# Launchd-fired wrapper: run the dedicated-bot-account migration at market open.
# Scheduled by com.deepthinktrader.migration for 2026-06-24 09:35 ET.
# Reads the new account keys from .migration_keys.env (gitignored, you fill it in),
# runs the fail-closed migration, restarts the bot, then cleans up the key file.
set -u

REPO="/Users/rebelhawk/Projects/StockTrader"
PY="/Users/rebelhawk/.venvs/deepthinktrader/bin/python3"
KEYS="$REPO/.migration_keys.env"
SENTINEL="$REPO/.migration_done"
LOG="/Users/rebelhawk/Library/Logs/DeepThinkTrader/migration.log"
cd "$REPO" || exit 1

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

if [ -f "$SENTINEL" ]; then
    log "SKIP: migration already completed ($SENTINEL exists)."
    exit 0
fi

if [ ! -f "$KEYS" ]; then
    log "ABORT: $KEYS missing — new account keys were never staged. Migration NOT run."
    exit 1
fi
# shellcheck disable=SC1090
source "$KEYS"
if [ -z "${NEW_ALPACA_KEY_ID:-}" ] || [ -z "${NEW_ALPACA_SECRET:-}" ] \
   || [ "${NEW_ALPACA_KEY_ID}" = "REPLACE_ME" ] || [ "${NEW_ALPACA_SECRET}" = "REPLACE_ME" ]; then
    log "ABORT: NEW_ALPACA_KEY_ID / NEW_ALPACA_SECRET not filled in $KEYS. Migration NOT run."
    exit 1
fi

log "Running migration (account split, $20k sleeve)..."
NEW_ALPACA_KEY_ID="$NEW_ALPACA_KEY_ID" NEW_ALPACA_SECRET="$NEW_ALPACA_SECRET" \
    "$PY" "$REPO/scripts/migrate_bot_account.py" >>"$LOG" 2>&1
rc=$?

if [ "$rc" -ne 0 ]; then
    log "MIGRATION FAILED (exit $rc) — keys NOT cleaned up, bot NOT restarted. See log above."
    exit "$rc"
fi

log "Migration OK. Restarting bot to load new keys..."
launchctl kickstart -k "gui/$(id -u)/com.deepthinktrader.bot" >>"$LOG" 2>&1
touch "$SENTINEL"
rm -f "$KEYS"
log "DONE: keys swapped, key file removed, bot restarted. Old account now ETF-only."
log "Cleanup: 'launchctl bootout gui/$(id -u)/com.deepthinktrader.migration' to unload this one-shot job."
exit 0
