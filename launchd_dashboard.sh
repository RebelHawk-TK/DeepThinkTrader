#!/bin/bash
cd /Users/rebelhawk/Documents/Claude/StockTrader
exec /Users/rebelhawk/Documents/Claude/StockTrader/.venv/bin/streamlit run dashboard.py --server.port 8501 --server.headless true --browser.gatherUsageStats false
