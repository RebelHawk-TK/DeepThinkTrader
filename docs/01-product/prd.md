# PRD — DeepThinkTrader

## Problem
Retail traders make emotional, poorly-researched decisions. No accessible tool combines real-time multi-source research with structured deep analysis and automated execution with strict risk controls.

## Solution
An autonomous trading bot with three specialized agents that research, analyze, and execute trades systematically.

## Features

### P0 (Must Have)
- Research Agent: NewsAPI + Reddit sentiment + technical data
- DeepThink Agent: Chain-of-thought analysis with conviction scoring
- Execution Agent: Alpaca paper trading with bracket orders
- Risk management: 2% per trade, daily loss limits, position sizing
- SQLite trade logging
- Streamlit monitoring dashboard

### P1 (Should Have)
- Scheduled hourly research loop
- Email/SMS alerts on trade execution
- Performance analytics (win rate, P&L, drawdown)

### P2 (Nice to Have)
- Live trading mode toggle
- Options trading support
- Crypto support
- Second opinion via xAI/Grok API
- Google Sheets logging

## Default Parameters
- Account size: $50,000 (paper)
- Watchlist: NVDA, TSLA, AAPL, AMD, SPY
- Max risk per trade: 2%
- Max daily loss: 5%
- Min conviction to trade: 8/10
- Research interval: 60 minutes
- Min R:R ratio: 1:2
