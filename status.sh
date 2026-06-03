#!/bin/bash
# DeepThinkTrader — Status check

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo ""
echo -e "${CYAN}═══════════════════════════════════════${NC}"
echo -e "${CYAN}  DeepThinkTrader Status${NC}"
echo -e "${CYAN}═══════════════════════════════════════${NC}"
echo ""

# Trading bot status — check run.sh PID file first, then launchd as fallback.
BOT_PID=""; BOT_MGR=""
if [ -f "$DIR/.trader.pid" ] && kill -0 "$(cat "$DIR/.trader.pid")" 2>/dev/null; then
    BOT_PID=$(cat "$DIR/.trader.pid"); BOT_MGR="run.sh"
else
    LD_PID=$(launchctl list 2>/dev/null | awk '$3=="com.deepthinktrader.bot" && $1!="-" {print $1}')
    if [ -n "$LD_PID" ]; then
        BOT_PID="$LD_PID"; BOT_MGR="launchd"
    fi
fi
if [ -n "$BOT_PID" ]; then
    echo -e "  Trading Bot:   ${GREEN}RUNNING${NC} (PID $BOT_PID, $BOT_MGR)"
else
    echo -e "  Trading Bot:   ${RED}STOPPED${NC}"
fi

# Dashboard status — same two-source check.
DASH_PID=""; DASH_MGR=""
if [ -f "$DIR/.dashboard.pid" ] && kill -0 "$(cat "$DIR/.dashboard.pid")" 2>/dev/null; then
    DASH_PID=$(cat "$DIR/.dashboard.pid"); DASH_MGR="run.sh"
else
    LD_DASH=$(launchctl list 2>/dev/null | awk '$3=="com.deepthinktrader.dashboard" && $1!="-" {print $1}')
    if [ -n "$LD_DASH" ]; then
        DASH_PID="$LD_DASH"; DASH_MGR="launchd"
    fi
fi
if [ -n "$DASH_PID" ]; then
    echo -e "  Dashboard:     ${GREEN}RUNNING${NC} (PID $DASH_PID, $DASH_MGR) → http://localhost:8501"
else
    echo -e "  Dashboard:     ${RED}STOPPED${NC}"
fi

echo ""

# Database stats
if [ -f "$DIR/trades.db" ]; then
    RESEARCH=$(python3 -c "
import sqlite3
conn = sqlite3.connect('trades.db')
r = conn.execute('SELECT COUNT(*) FROM research_reports').fetchone()[0]
a = conn.execute('SELECT COUNT(*) FROM analysis_results').fetchone()[0]
t = conn.execute('SELECT COUNT(*) FROM trades').fetchone()[0]
o = conn.execute('SELECT COUNT(*) FROM trades WHERE status=\"OPEN\"').fetchone()[0]
req = conn.execute('SELECT COUNT(*) FROM alpaca_request_ids').fetchone()[0]
conn.close()
print(f'{r}|{a}|{t}|{o}|{req}')
" 2>/dev/null)

    IFS='|' read -r REPORTS ANALYSES TRADES OPEN REQUESTS <<< "$RESEARCH"

    echo -e "  ${CYAN}Database:${NC}"
    echo -e "    Research reports:  $REPORTS"
    echo -e "    Analyses:          $ANALYSES"
    echo -e "    Total trades:      $TRADES"
    echo -e "    Open positions:    $OPEN"
    echo -e "    API request IDs:   $REQUESTS"
else
    echo -e "  ${YELLOW}Database not initialized yet${NC}"
fi

echo ""

# Alpaca account — keys are per-user (encrypted in DB), read via secrets_vault.
# Must run under the bot's venv so the alpaca SDK + deps import.
VENV_PY="/Users/rebelhawk/.venvs/deepthinktrader/bin/python3"
[ -x "$VENV_PY" ] || VENV_PY="python3"
ACCOUNT=$("$VENV_PY" -c "
from utils.database import Database
from utils.secrets_vault import get_alpaca_keys
from brokers.alpaca import AlpacaBroker
try:
    uids = Database().get_active_user_ids()
    if not uids:
        print('NONE'); raise SystemExit
    uid = uids[0]
    keys = get_alpaca_keys(uid)
    if not keys:
        print('NOKEYS'); raise SystemExit
    key_id, secret = keys
    a = AlpacaBroker(api_key=key_id, secret_key=secret).get_account()
    print(f'OK|{a.equity}|{a.buying_power}|{a.cash}|{uid}')
except SystemExit:
    pass
except Exception as e:
    print(f'ERR|{type(e).__name__}')
" 2>/dev/null)

IFS='|' read -r STATUS EQUITY POWER CASH ACCT <<< "$ACCOUNT"

if [ "$STATUS" = "OK" ]; then
    echo -e "  ${CYAN}Alpaca Paper Account:${NC} user $ACCT"
    printf "    Equity:            \$%'.2f\n" "$EQUITY"
    printf "    Buying Power:      \$%'.2f\n" "$POWER"
    printf "    Cash:              \$%'.2f\n" "$CASH"
elif [ "$STATUS" = "NONE" ]; then
    echo -e "  ${YELLOW}Alpaca: no active users with keys on file${NC}"
elif [ "$STATUS" = "NOKEYS" ]; then
    echo -e "  ${YELLOW}Alpaca: active user has no keys on file${NC}"
else
    echo -e "  ${RED}Alpaca: Connection failed${NC} ($EQUITY)"
fi

echo ""

# Last log entries
if [ -f "$DIR/deepthinktrader.log" ]; then
    echo -e "  ${CYAN}Last 5 log entries:${NC}"
    tail -5 "$DIR/deepthinktrader.log" | sed 's/^/    /'
fi

echo ""
echo -e "${CYAN}═══════════════════════════════════════${NC}"
echo ""
