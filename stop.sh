#!/bin/bash
# DeepThinkTrader — Stop
#
# Unloads both launchd jobs (bot + dashboard). The previous version of this
# script only killed PIDs tracked in `.trader.pid` / `.dashboard.pid`, which
# missed the launchd-managed copies and let two bots race on the same DB
# (see Sprint 1-4 notes). This version is the single source of truth.

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

BOT_PLIST="$HOME/Library/LaunchAgents/com.deepthinktrader.bot.plist"
DASH_PLIST="$HOME/Library/LaunchAgents/com.deepthinktrader.dashboard.plist"

unload_if_loaded() {
    local label="$1"
    local plist="$2"
    if [ ! -f "$plist" ]; then
        echo -e "${YELLOW}[DeepThinkTrader]${NC} $label: plist not installed at $plist"
        return 0
    fi
    if launchctl list "$label" >/dev/null 2>&1; then
        launchctl unload "$plist" 2>/dev/null || true
        echo -e "${GREEN}[DeepThinkTrader]${NC} $label: unloaded"
    else
        echo -e "${YELLOW}[DeepThinkTrader]${NC} $label: already stopped"
    fi
}

unload_if_loaded "com.deepthinktrader.bot"       "$BOT_PLIST"
unload_if_loaded "com.deepthinktrader.dashboard" "$DASH_PLIST"

# Clean up stale PID files from the old run.sh-managed model.
rm -f "$DIR/.trader.pid" "$DIR/.dashboard.pid" 2>/dev/null || true

# Belt-and-suspenders: warn on stray manually-launched processes.
STRAGGLERS=$(pgrep -fl "$DIR/(main\.py|dashboard\.py)" 2>/dev/null || true)
if [ -n "$STRAGGLERS" ]; then
    echo -e "${RED}[DeepThinkTrader]${NC} WARNING: stray processes still running:"
    echo "$STRAGGLERS" | sed 's/^/    /'
    echo -e "  Launched outside launchd. Kill manually or re-run stop.sh."
fi

echo -e "${GREEN}[DeepThinkTrader]${NC} Stop complete."
