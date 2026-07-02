#!/bin/bash
# Sync StockTrader documentation (docs/) into the Obsidian vault so it's
# searchable and Syncthing-synced — WITHOUT moving code into the vault.
# Code, trades.db, and the launchd services stay in ~/Projects/StockTrader
# per the 2026-06-17 vault policy (live SQLite + sync engines don't mix).
#
# One-way: repo docs/ is the source of truth; vault copy is a mirror.
# The vault's digests/ folder is written by the bot directly and is NOT
# touched by this script.
#
# Run manually or from a scheduler. Idempotent.
set -euo pipefail

SRC="$(cd "$(dirname "$0")/.." && pwd)/docs/"
DEST="${HOME}/Documents/TKSabrinaIncVault.nosync/02-Projects/StockTrader/docs/"

mkdir -p "$DEST"
rsync -a --delete "$SRC" "$DEST"
echo "Synced $(find "$DEST" -type f | wc -l | tr -d ' ') files: repo docs/ -> vault 02-Projects/StockTrader/docs/"
