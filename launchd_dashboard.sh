#!/bin/bash
# Wrapper for launchd — logs what's happening before streamlit starts
cd /Users/rebelhawk/Projects/StockTrader
echo "[$(date)] launchd_dashboard.sh started, PWD=$(pwd), USER=$(whoami)" >> /Users/rebelhawk/Projects/StockTrader/dashboard.log
exec /Users/rebelhawk/.venvs/deepthinktrader/bin/python3 -m streamlit run dashboard.py --server.port 8501 --server.address 127.0.0.1 --server.headless true --browser.gatherUsageStats false
