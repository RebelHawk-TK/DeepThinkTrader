#!/bin/bash
# DeepThinkTrader — Start (idempotent)
#
# Loads both launchd jobs (bot + dashboard). Replaces the old model where
# this script spawned its own nohup'd processes alongside launchd-managed
# ones, which led to two bots racing on the same DB. Everything is now
# managed by launchd; this script is a convenience wrapper.

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

BOT_PLIST="$HOME/Library/LaunchAgents/com.deepthinktrader.bot.plist"
DASH_PLIST="$HOME/Library/LaunchAgents/com.deepthinktrader.dashboard.plist"
LOG="$DIR/deepthinktrader.log"

reload() {
    local label="$1"
    local plist="$2"
    if [ ! -f "$plist" ]; then
        echo -e "${RED}[DeepThinkTrader]${NC} $label: plist missing at $plist"
        echo -e "  Copy it from the project dir: cp $DIR/${label}.plist $plist"
        return 1
    fi
    # If already loaded, unload first so `load -w` is a true reload.
    if launchctl list "$label" >/dev/null 2>&1; then
        launchctl unload "$plist" 2>/dev/null || true
        echo -e "${YELLOW}[DeepThinkTrader]${NC} $label: was running, reloading"
    fi
    launchctl load -w "$plist"
    echo -e "${GREEN}[DeepThinkTrader]${NC} $label: loaded"
}

reload "com.deepthinktrader.bot"       "$BOT_PLIST"
reload "com.deepthinktrader.dashboard" "$DASH_PLIST"

# Give launchd a beat to spawn, then confirm.
sleep 2

BOT_PID=$(launchctl list 2>/dev/null | awk '$3=="com.deepthinktrader.bot" && $1!="-" {print $1}')
DASH_PID=$(launchctl list 2>/dev/null | awk '$3=="com.deepthinktrader.dashboard" && $1!="-" {print $1}')

echo ""
echo -e "${GREEN}[DeepThinkTrader]${NC} ========================================="
echo -e "${GREEN}[DeepThinkTrader]${NC}   DeepThinkTrader is running!"
echo -e "${GREEN}[DeepThinkTrader]${NC} ========================================="
echo -e "${GREEN}[DeepThinkTrader]${NC} Bot:        PID ${BOT_PID:-?} (launchd, KeepAlive)"
echo -e "${GREEN}[DeepThinkTrader]${NC} Dashboard:  PID ${DASH_PID:-?} → http://localhost:8501"
echo -e "${GREEN}[DeepThinkTrader]${NC} Bot log:    $LOG"
echo -e "${GREEN}[DeepThinkTrader]${NC} Stop:       ./stop.sh"
echo -e "${GREEN}[DeepThinkTrader]${NC} Status:     ./status.sh"
echo ""

open "http://localhost:8501" 2>/dev/null || true
