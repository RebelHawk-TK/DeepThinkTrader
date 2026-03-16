# DeepThinkTrader

Multi-agent stock trading bot with deep research, chain-of-thought analysis, and automated execution via Alpaca Markets.

> **WARNING:** Start with paper trading only. Trading bots can lose 100% of capital. This is educational/experimental.

## Architecture

```
Research Agent → DeepThink Agent → Execution Agent
(News + Reddit    (Chain-of-thought    (Alpaca paper
 + Technicals)     + Conviction score)   + Risk guardrails)
```

## Quick Start

### 1. Clone & install

```bash
cd StockTrader
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure API keys

```bash
cp .env.template .env
# Edit .env with your keys
```

You need:
- **Alpaca** (free paper account): [alpaca.markets](https://alpaca.markets)
- **NewsAPI**: [newsapi.org](https://newsapi.org)
- **Reddit**: Create app at reddit.com/prefs/apps (script type)

### 3. Run

```bash
# Scheduled loop (every 60 min)
python main.py

# Single cycle
python main.py once

# Single ticker
python main.py ticker NVDA
```

### 4. Dashboard

```bash
streamlit run dashboard.py
```

## Trading Parameters (defaults)

| Parameter | Default | Description |
|-----------|---------|-------------|
| Account size | $50,000 | Paper trading balance |
| Watchlist | NVDA, TSLA, AAPL, AMD, SPY | Tickers to monitor |
| Max risk/trade | 2% | Max account % risked per trade |
| Max daily loss | 5% | Hard stop for the day |
| Min conviction | 8/10 | Minimum score to execute |
| Research interval | 60 min | How often to run cycle |
| Min R:R ratio | 1:2 | Minimum reward-to-risk |

## Safety Features

- Conviction threshold (8/10 minimum)
- Position sizing based on account risk %
- Daily loss limit enforcement
- Duplicate position prevention
- Revenge trading detection (3+ consecutive losses)
- Market hours check
- Full trade logging to SQLite

## Project Structure

```
StockTrader/
├── main.py              # Orchestrator
├── config.py            # Environment config
├── dashboard.py         # Streamlit monitoring
├── agents/
│   ├── research_agent.py    # News + Reddit + technicals
│   ├── deepthink_agent.py   # Analysis + conviction scoring
│   └── execution_agent.py   # Alpaca trades + risk checks
├── utils/
│   ├── database.py      # SQLite trade logging
│   └── risk_manager.py  # Position sizing + guardrails
├── .env.template        # API key template
├── requirements.txt     # Dependencies
└── docs/                # Project documentation
```
