# DeepThinkTrader

> Trade with conviction, not emotion.

A multi-agent autonomous trading system that enforces institutional-grade risk discipline on every trade. 13 pre-trade safety checks, Kelly-calibrated position sizing, and automated exit management — so you preserve capital first and only enter positions backed by multi-source research and chain-of-thought reasoning.

> **Strategy status (2026-06-03):** the main book (≥ $5) now trades a backtest-validated **quality-momentum factor** (above SMA-20 + revenue growth + profit margin + up-day). The conviction/multi-edge/LLM stack described below was found to have no out-of-sample edge and now drives the **penny** book only. See [`docs/status_2026-06-03.md`](docs/status_2026-06-03.md) for the current per-book logic and the `backtest/` validator suite.

> **WARNING:** DeepThinkTrader is experimental software for educational and research purposes only. It is NOT financial advice. Stock trading involves substantial risk of loss, including the possibility of losing your entire investment. Paper trading results do not reflect real market conditions. Past performance does not predict future results. Always start with paper trading and never risk capital you cannot afford to lose.

## Why DeepThinkTrader?

Most retail traders already know what they should do — cut losses early, size positions properly, research before buying. **They just don't do it.** DeepThinkTrader encodes those rules in code so discipline is enforced by the system, not by willpower.

- **Risk comes first.** 13 pre-trade checks, Kelly sizing, circuit breakers, and trailing stops protect your capital before any trade is placed.
- **Deep research, not hot tips.** Every trade is backed by news analysis, Reddit sentiment, technical signals, fundamental data, and AI-powered qualitative reasoning.
- **Your discipline, automated.** The rules you know you should follow — enforced by code, not willpower.
- **Transparent reasoning.** Every trade comes with a plain-English summary explaining exactly why the bot is buying and what would invalidate the thesis.

## Architecture

```
Scanner Agent → Research Agent → DeepThink Agent → Execution Agent
(60+ stocks,     (NewsAPI, Reddit,  (Multi-edge        (Alpaca bracket
 3-stage funnel)  Seeking Alpha,     validation,        orders, 13 risk
                  yfinance, Twelve   conviction score,  checks, trailing
                  Data)              Claude AI layer)   stops, exits)
```

**4-agent pipeline** — research, analysis, and execution are independent agents. No single point of failure.

## Features

### Risk-First Execution (13 Pre-Trade Checks)
- Kelly-calibrated position sizing with safety multiplier
- Max drawdown halt — stops trading when account draws down too far
- Risk-of-ruin probability check
- Liquidity guard (ADV minimum)
- Sector exposure cap
- Spread and gap risk adjustment
- Daily loss limit enforcement
- Duplicate position prevention
- Revenge trading detection (3+ consecutive losses)
- Market circuit breaker (SPY -2% blocks all new longs)
- Minimum conviction threshold
- Multi-edge validation (2/3 edges must align)
- Earnings proximity block (no entries within 2 days of earnings)

### Multi-Source Research
- NewsAPI real-time headlines
- Reddit sentiment via PRAW + VADER
- Seeking Alpha RSS feed
- yfinance fundamentals + technicals
- Twelve Data advanced indicators
- Claude AI qualitative analysis (optional)

### Automated Exit Management
- Trailing stops (activate at 2% profit, trail at 1.5%)
- Partial scale-out (33% at 1R, 33% at 2R)
- Time stops (15-day dead position exit)
- Earnings auto-exit (close within 2 days of earnings)
- 5-minute exit monitoring (independent of hourly research cycle)

### Strategy Health Monitoring
- Weekly post-trade learning loop
- Win rate delta tracking with auto-degradation warnings
- **Auto-pause** — halts trading on degraded portfolios, resumes on recovery
- Edge combo performance tracking

### Dashboard
- Real-time Streamlit dashboard with market ticker bar (DOW, S&P 500, NASDAQ, BTC)
- Portfolio equity curve
- Trade log with reasoning details
- Strategy health metrics
- Live log viewer

## Quick Start

### 1. Clone & Install

```bash
git clone https://github.com/YOUR_USERNAME/StockTrader.git
cd StockTrader
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure API Keys

```bash
cp .env.template .env
# Edit .env with your keys
```

You need (all free tiers):
- **Alpaca** (paper trading account): [alpaca.markets](https://alpaca.markets)
- **NewsAPI**: [newsapi.org](https://newsapi.org)
- **Reddit**: Create app at [reddit.com/prefs/apps](https://www.reddit.com/prefs/apps) (script type)
- **Anthropic** (optional, for Claude AI analysis layer): [anthropic.com](https://www.anthropic.com)

### 3. Run

```bash
# Scheduled loop (research every 60 min, exit checks every 5 min)
python main.py

# Single cycle
python main.py once

# Single ticker analysis
python main.py ticker NVDA
```

### 4. Dashboard

```bash
streamlit run dashboard.py
# Opens at http://localhost:8501
```

## Trade Modes

| Mode | Risk/Trade | Daily Limit | Min Conviction | R:R | Max Position |
|------|-----------|-------------|----------------|-----|-------------|
| Safe | 1% | 3% | 9.0/10 | 3:1 | 5% |
| Normal | 2% | 5% | 7.5/10 | 2:1 | 10% |
| Aggressive | 3% | 8% | 6.0/10 | 1.5:1 | 15% |

Set via `TRADE_MODE` in `.env` (default: `normal`).

## Project Structure

```
StockTrader/
├── main.py                  # Orchestrator — runs the pipeline loop
├── config.py                # 20+ configurable parameters
├── dashboard.py             # Streamlit real-time monitoring
├── agents/
│   ├── scanner_agent.py     # 3-stage stock scanner (60+ universe)
│   ├── research_agent.py    # News + Reddit + Seeking Alpha + technicals
│   ├── deepthink_agent.py   # Multi-edge analysis + conviction scoring
│   ├── ai_deepthink_agent.py # Claude AI qualitative analysis layer
│   └── execution_agent.py   # Alpaca trades + 13 risk guardrails
├── utils/
│   ├── database.py          # SQLite trade logging + analytics
│   ├── risk_manager.py      # Kelly sizing, drawdown, sector exposure
│   ├── market_clock.py      # Market hours validation
│   ├── alpaca_data.py       # Alpaca API wrapper
│   ├── claude_analyst.py    # Claude API integration
│   ├── yahoo_fundamentals.py # Yahoo Finance data
│   ├── seeking_alpha_rss.py # Seeking Alpha feed parser
│   └── twelve_data.py       # Twelve Data API wrapper
├── docs/                    # Project documentation
├── .env.template            # API key template
├── requirements.txt         # Dependencies
├── CONTRIBUTING.md          # Contribution guidelines
├── LICENSE                  # MIT License
└── CODE_OF_CONDUCT.md       # Community standards
```

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines. Check the Issues tab for `good first issue` and `help wanted` labels.

High-impact areas: new data edges, risk improvements, dashboard enhancements, documentation.

## License

MIT License. See [LICENSE](LICENSE).

---

> **Reminder:** This is experimental software. Paper trading only. Not financial advice. Past performance does not predict future results.
