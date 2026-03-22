#!/bin/bash
# DeepThinkTrader — Local Application Launcher
# Starts the trading bot + Streamlit dashboard

set -e

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PIDFILE="$DIR/.trader.pid"
DASHBOARD_PIDFILE="$DIR/.dashboard.pid"
LOG="$DIR/deepthinktrader.log"
PYTHON="$DIR/.venv/bin/python3"
STREAMLIT="$DIR/.venv/bin/streamlit"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

print_status() {
    echo -e "${GREEN}[DeepThinkTrader]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[DeepThinkTrader]${NC} $1"
}

print_error() {
    echo -e "${RED}[DeepThinkTrader]${NC} $1"
}

# Check if already running
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    print_warn "Trading bot already running (PID $(cat "$PIDFILE"))"
else
    print_status "Starting trading bot..."
    nohup "$PYTHON" main.py >> "$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    chmod 600 "$PIDFILE" "$LOG" 2>/dev/null
    print_status "Trading bot started (PID $!)"
fi

# Start dashboard
if [ -f "$DASHBOARD_PIDFILE" ] && kill -0 "$(cat "$DASHBOARD_PIDFILE")" 2>/dev/null; then
    print_warn "Dashboard already running (PID $(cat "$DASHBOARD_PIDFILE"))"
else
    print_status "Starting Streamlit dashboard..."
    nohup "$STREAMLIT" run dashboard.py \
        --server.port 8501 \
        --server.headless true \
        --browser.gatherUsageStats false \
        >> "$DIR/dashboard.log" 2>&1 &
    echo $! > "$DASHBOARD_PIDFILE"
    chmod 600 "$DASHBOARD_PIDFILE" "$DIR/dashboard.log" 2>/dev/null
    print_status "Dashboard started (PID $!)"
fi

sleep 2

echo ""
print_status "========================================="
print_status "  DeepThinkTrader is running!"
print_status "========================================="
print_status "Dashboard:  http://localhost:8501"
print_status "Bot log:    $LOG"
print_status "Stop:       ./stop.sh"
print_status "Status:     ./status.sh"
echo ""

# Open dashboard in browser
open "http://localhost:8501" 2>/dev/null || true
