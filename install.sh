#!/bin/bash
# DeepThinkTrader — Install as background service (launchd)

DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}[DeepThinkTrader]${NC} Installing launchd services..."

# Copy plists
cp "$DIR/com.deepthinktrader.bot.plist" "$LAUNCH_DIR/"
cp "$DIR/com.deepthinktrader.dashboard.plist" "$LAUNCH_DIR/"

echo -e "${GREEN}[DeepThinkTrader]${NC} Plists installed to $LAUNCH_DIR"
echo ""
echo -e "${YELLOW}Services installed but NOT started.${NC}"
echo ""
echo "To start the trading bot as a background service:"
echo "  launchctl load ~/Library/LaunchAgents/com.deepthinktrader.bot.plist"
echo ""
echo "To start the dashboard as a background service:"
echo "  launchctl load ~/Library/LaunchAgents/com.deepthinktrader.dashboard.plist"
echo ""
echo "To stop:"
echo "  launchctl unload ~/Library/LaunchAgents/com.deepthinktrader.bot.plist"
echo "  launchctl unload ~/Library/LaunchAgents/com.deepthinktrader.dashboard.plist"
echo ""
echo "Or just use the simple scripts:"
echo "  ./run.sh     — Start both (foreground-managed)"
echo "  ./stop.sh    — Stop both"
echo "  ./status.sh  — Check status"
