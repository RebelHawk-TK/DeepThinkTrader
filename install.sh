#!/bin/bash
# DeepThinkTrader — Full macOS Installation
# Sets up venv, installs deps, copies apps to /Applications

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${CYAN}═══════════════════════════════════════${NC}"
echo -e "${CYAN}  DeepThinkTrader v3.0 — Installer${NC}"
echo -e "${CYAN}═══════════════════════════════════════${NC}"
echo ""

# 1. Python venv
echo -e "${GREEN}[1/4]${NC} Setting up Python virtual environment..."
if [ ! -d "$DIR/.venv" ]; then
    python3 -m venv "$DIR/.venv"
    echo "  Created .venv"
else
    echo "  .venv already exists"
fi

echo -e "${GREEN}[2/4]${NC} Installing Python dependencies..."
"$DIR/.venv/bin/pip" install -q -r "$DIR/requirements.txt"
echo "  Dependencies installed"

# 3. Stop any running instances
echo -e "${GREEN}[3/4]${NC} Stopping existing instances..."
bash "$DIR/stop.sh" 2>/dev/null || true
echo "  Done"

# 4. Copy apps to /Applications
echo -e "${GREEN}[4/4]${NC} Installing macOS apps..."
if [ -d "$DIR/DeepThinkTrader.app" ]; then
    rm -rf "/Applications/DeepThinkTrader.app"
    cp -R "$DIR/DeepThinkTrader.app" "/Applications/"
    echo "  DeepThinkTrader.app → /Applications/"
fi
if [ -d "$DIR/DeepThinkTrader Stop.app" ]; then
    rm -rf "/Applications/DeepThinkTrader Stop.app"
    cp -R "$DIR/DeepThinkTrader Stop.app" "/Applications/"
    echo "  DeepThinkTrader Stop.app → /Applications/"
fi

echo ""
echo -e "${CYAN}═══════════════════════════════════════${NC}"
echo -e "${GREEN}  Installation complete!${NC}"
echo -e "${CYAN}═══════════════════════════════════════${NC}"
echo ""
echo "  How to use:"
echo "    Start:  Double-click 'DeepThinkTrader' in Applications/Launchpad"
echo "    Stop:   Double-click 'DeepThinkTrader Stop' in Applications/Launchpad"
echo "    Status: ./status.sh"
echo ""
echo "  Auto-start on login:"
echo "    System Settings → General → Login Items → add DeepThinkTrader.app"
echo ""
echo "  The bot runs in the background — no terminal or Claude session needed."
echo "  Dashboard: http://localhost:8501"
echo ""
