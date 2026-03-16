#!/bin/bash
# DeepThinkTrader — Stop all processes

DIR="$(cd "$(dirname "$0")" && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
NC='\033[0m'

stopped=0

# Stop trading bot
if [ -f "$DIR/.trader.pid" ]; then
    PID=$(cat "$DIR/.trader.pid")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo -e "${GREEN}[DeepThinkTrader]${NC} Trading bot stopped (PID $PID)"
        stopped=1
    fi
    rm -f "$DIR/.trader.pid"
fi

# Stop dashboard
if [ -f "$DIR/.dashboard.pid" ]; then
    PID=$(cat "$DIR/.dashboard.pid")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID"
        echo -e "${GREEN}[DeepThinkTrader]${NC} Dashboard stopped (PID $PID)"
        stopped=1
    fi
    rm -f "$DIR/.dashboard.pid"
fi

# Also kill any orphaned streamlit processes for this project
pkill -f "streamlit run dashboard.py" 2>/dev/null || true

if [ $stopped -eq 0 ]; then
    echo -e "${RED}[DeepThinkTrader]${NC} Nothing was running"
else
    echo -e "${GREEN}[DeepThinkTrader]${NC} All processes stopped"
fi
