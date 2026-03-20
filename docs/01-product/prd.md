# PRD — DeepThinkTrader

## Problem
Retail traders make emotional, poorly-researched decisions. No accessible tool combines real-time multi-source research with structured deep analysis and automated execution with strict risk controls.

## Solution
An autonomous trading bot with three specialized agents that research, analyze, and execute trades systematically — now with a professional risk-first framework.

## Features

### P0 (Must Have) — ✅ Complete
- Research Agent: NewsAPI + Reddit sentiment + technical data
- DeepThink Agent: Rule-based analysis with multi-edge validation (2/3 edges required)
- Execution Agent: Alpaca paper trading with 13 risk guardrails
- Risk management: Kelly sizing, drawdown halt, circuit breaker, liquidity check
- SQLite trade logging with trailing stop and partial exit tracking
- Streamlit monitoring dashboard with strategy health

### P1 (Should Have) — ✅ Complete
- Scheduled research loop + 5-minute exit monitoring
- Trailing stops (activate at 2%, trail at 1.5%/3%)
- Partial scale-out (33% at 1R, 33% at 2R)
- Time stops (15-day dead position exit)
- Market circuit breaker (SPY -2% blocks longs)
- Earnings proximity awareness (auto-close within 2 days)
- Post-trade learning loop (weekly strategy health check)
- Limit orders for penny stocks with slippage tracking
- Trade transparency (pre-trade plain-English summary)
- Performance analytics (win rate, P&L, drawdown, expectancy)

### P2 (Nice to Have)
- Live trading mode toggle
- VIX/breadth data for sentiment edge
- Strategy auto-pause (currently logs warning only)
- Options trading support
- Crypto support

## Default Parameters
- Account size: $50,000 (paper)
- Watchlist: NVDA, TSLA, AAPL, AMD, SPY
- Max risk per trade: 1% (Kelly-adjusted)
- Max daily loss: 5%
- Min conviction to trade: 7.5/10 (normal mode)
- Min edges to trade: 2/3
- Research interval: 60 minutes
- Exit check interval: 5 minutes
- Min R:R ratio: 2:1
- Trailing stop activation: 2% profit
- Time stop: 15 trading days
- Circuit breaker: SPY -2%
- Earnings exit: 2 trading days
