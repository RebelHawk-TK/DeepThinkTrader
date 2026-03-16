# Vision — DeepThinkTrader

## What
A multi-agent Python stock trading bot that combines real-time news, Reddit sentiment analysis, and deep chain-of-thought reasoning to make high-conviction trades via Alpaca Markets.

## Why
Manual retail trading is emotional and inconsistent. A systematic bot with strict risk management, multi-source research, and skeptical deep analysis removes emotion and enforces discipline.

## Core Principles
1. **Safety first** — Paper trading until backtested 3+ months. Max 2% risk per trade.
2. **Deep thinking over speed** — Quality of analysis beats frequency of trades.
3. **Multi-source validation** — News + Reddit + technicals must align before execution.
4. **No revenge trading** — Daily loss limits are hard stops, not suggestions.

## Architecture
Three-agent pipeline:
- **Research Agent** — Gathers news (NewsAPI), Reddit sentiment (PRAW + VADER), and technicals (yfinance)
- **DeepThink Agent** — Chain-of-thought analysis with contrarian views, scenario modeling, conviction scoring
- **Execution Agent** — Alpaca bracket orders with strict risk guardrails

## Success Metrics
- Win rate > 55%
- Average R:R > 1:2
- Max drawdown < 10% of account
- Zero trades executed below conviction threshold (8/10)
