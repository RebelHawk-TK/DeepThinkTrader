# Product Marketing Context

## Product
- **Name:** DeepThinkTrader
- **Type:** Multi-agent autonomous stock trading bot (Python, local desktop application)
- **One-liner:** An AI-powered trading bot that researches, thinks deeply, and trades systematically — so you don't have to trade on emotion.
- **Description:** DeepThinkTrader is a multi-agent Python stock trading system that combines real-time news analysis, Reddit sentiment scanning, technical indicators, and chain-of-thought reasoning to make high-conviction trades via Alpaca Markets. It runs a four-stage pipeline — Scanner, Research, DeepThink Analysis, Execution — with a risk-first framework featuring 13 pre-trade safety checks, Kelly-based position sizing, trailing stops, partial scale-outs, and market circuit breakers. Currently operating in paper trading mode on a $50K Alpaca account.
- **Key features/offerings:**
  - 4-agent pipeline: Scanner (3-stage funnel) -> Research Agent (NewsAPI + Reddit VADER + Seeking Alpha + yfinance + Twelve Data) -> DeepThink Agent (rule-based + Claude AI qualitative analysis, multi-edge validation requiring 2/3 edges) -> Execution Agent (Alpaca bracket orders)
  - 3 trade modes: Safe (1% risk, 9/10 conviction, 3:1 R:R), Normal (2% risk, 7.5/10 conviction, 2:1 R:R), Aggressive (3% risk, 6/10 conviction, 1.5:1 R:R)
  - 13 pre-trade risk checks including Kelly position sizing, drawdown halt, risk-of-ruin check, liquidity guard, sector exposure cap, spread check, gap risk adjustment
  - Trailing stops (activate at 2% profit, trail at 1.5%), partial scale-out (33% at 1R, 33% at 2R), time stops (15-day dead position exit)
  - Market circuit breaker: SPY -2% blocks all new long entries
  - Earnings proximity awareness: auto-closes positions within 2 days of earnings
  - Penny stock portfolio ($1-$5 range) running alongside main portfolio
  - 5-minute exit monitoring (independent of hourly full-cycle analysis)
  - Weekly post-trade learning loop with strategy health checks and auto-degradation warnings
  - Claude AI qualitative layer for news interpretation, signal correlation, earnings quality, contrarian reasoning
  - Streamlit real-time dashboard with market ticker bar (DOW, S&P 500, NASDAQ, Gold, Silver, BTC), portfolio equity curve, trade log, strategy health metrics
  - Live log viewer page for real-time bot monitoring
  - Dynamic sector watchlist rebuilt daily from market movers
  - Limit orders with slippage tracking for penny stocks
  - Pre-trade plain-English transparency summaries
  - SQLite trade database with full audit trail and Alpaca X-Request-ID capture
  - Runs as a macOS launchd service (auto-start on boot)
  - Default watchlist: NVDA, TSLA, AAPL, AMD, SPY + 60+ popular large/mid-cap stocks in scanner universe
- **URL:** N/A (local desktop application, not a SaaS product — yet)
- **Price points:** N/A (personal project / open-source candidate). Requires free Alpaca paper account, free NewsAPI tier, free Reddit API, optional Anthropic API key for Claude analysis layer.

## Target Audience
- **Primary ICP:** Tech-savvy retail traders (25-45) who understand basic trading but lack the discipline or time for systematic research and execution. They have a software engineering or quantitative background and are comfortable running Python scripts locally.
- **Secondary ICP:** Algorithmic trading enthusiasts and hobbyist quants who want a framework they can customize and extend. Also: retail traders burned by emotional trading who want a rules-based system to enforce discipline.
- **Demographics:**
  - Age: 25-50
  - Gender: Predominantly male (80%+ based on retail trading demographics)
  - Income: $75K-$200K+ (enough disposable capital to trade)
  - Education: College-educated, often STEM background
  - Location: US-based (US equities only, Alpaca is US-focused)
- **Psychographics:**
  - Values data-driven decision making over gut instinct
  - Frustrated by emotional trading losses (revenge trading, FOMO, panic selling)
  - Interested in automation and AI applied to finance
  - Enjoys tinkering with open-source tools and customizing parameters
  - Risk-aware but willing to allocate capital to algorithmic strategies
  - Skeptical of "get rich quick" trading schemes — wants transparent logic
  - Reads r/wallstreetbets, r/stocks, r/algotrading, Seeking Alpha
- **Jobs to be done:**
  - Remove emotion from trade entry and exit decisions
  - Systematically research 50+ stocks per cycle without manual effort
  - Enforce strict risk management rules that I know I should follow but don't
  - Monitor positions continuously during market hours (trailing stops, exit checks every 5 min)
  - Discover trade candidates I wouldn't find scanning manually
  - Learn which trading edges actually work through post-trade analysis
  - Paper-test a strategy before risking real capital
- **Pain points:**
  - "I know I should cut losses early but I hold losers too long"
  - "I can't monitor my positions all day — I have a day job"
  - "I don't have time to research every stock in the news"
  - "I make impulsive trades after seeing Reddit hype and regret it"
  - "I want systematic trading but algo platforms are either too complex (QuantConnect) or too simple (roboadvisors)"
  - "I lose money from revenge trading after a bad loss"
  - "I don't know my actual win rate or expectancy — I just 'feel' like I'm doing okay"

## Positioning
- **Category:** AI-powered autonomous trading systems / algorithmic trading bots
- **Differentiator:** Risk-first architecture. Most retail trading bots focus on entry signals; DeepThinkTrader inverts this with 13 pre-trade risk checks, Kelly-calibrated sizing, and multiple exit strategies (trailing, partial, time, earnings, circuit breaker) before ever placing a trade. The multi-agent pipeline ensures no single point of failure — research, analysis, and execution are independent agents with distinct responsibilities.
- **Competitive alternatives:**
  - Manual trading with TradingView + broker (the status quo)
  - Alpaca example algos and community bots (simpler, fewer risk controls)
  - QuantConnect / Zipline (backtesting-focused frameworks, steeper learning curve)
  - Trade Ideas / TrendSpider (subscription SaaS scanners, no autonomous execution)
  - WealthSimple / Betterment (roboadvisors — no customization, no individual stock trading)
  - ChatGPT/Claude for ad-hoc stock analysis (no execution, no risk management, no persistence)
- **Unique value prop:** DeepThinkTrader is the only trading system that combines multi-source AI research (news + social sentiment + fundamentals + technicals + LLM qualitative analysis), a risk-first execution framework with 13 pre-trade guardrails, and a transparent chain-of-thought reasoning pipeline — all running autonomously with plain-English trade explanations.

## Messaging
- **Tagline:** "Trade with conviction, not emotion."
- **Key messages:**
  - **Risk comes first.** 13 pre-trade checks, Kelly sizing, circuit breakers, and trailing stops protect your capital before any trade is placed.
  - **Deep research, not hot tips.** Every trade is backed by news analysis, Reddit sentiment, technical signals, fundamental data, and AI-powered qualitative reasoning.
  - **Your discipline, automated.** The rules you know you should follow — cut losses early, size positions properly, avoid revenge trading — enforced by code, not willpower.
  - **Transparent reasoning.** Every trade comes with a plain-English summary explaining exactly why the bot is buying, what the thesis is, and what would invalidate it.
  - **Two portfolios, one system.** Run a conservative large-cap portfolio alongside an aggressive penny stock portfolio, each with independent risk parameters.
- **Tone/voice:**
  - Technical but accessible — assumes trading literacy, doesn't assume CS degree
  - Honest and cautious — never hype, always disclose risks prominently
  - Builder-oriented — speaks to people who like understanding how things work
  - Data-driven — leads with metrics (win rate, expectancy, drawdown) not promises
  - Slightly irreverent — respects the market's ability to humble anyone
- **Words we use:** conviction, risk-first, systematic, multi-agent, deep analysis, guardrails, discipline, transparency, edge validation, paper trading, position sizing, trailing stop, chain-of-thought
- **Words we avoid:** guaranteed, profit, easy money, passive income, get rich, foolproof, beat the market, AI trading genius, zero risk, set and forget

## Channels
- **Primary:**
  - GitHub (open-source repository with detailed README)
  - Reddit: r/algotrading, r/python, r/stocks, r/wallstreetbets (build-in-public posts)
  - Twitter/X (developer and trading communities)
- **Secondary:**
  - Hacker News (Show HN post)
  - YouTube (demo walkthrough, architecture explainer, dashboard tour)
  - Dev.to / Medium (technical blog posts on the multi-agent architecture)
  - Discord trading and algotrading communities
- **Content types:**
  - GitHub README + docs (primary acquisition driver)
  - Build-in-public thread showing real paper trading results with transparency
  - Architecture deep-dive blog post (multi-agent pipeline, risk framework)
  - Dashboard demo video (Streamlit dashboard walkthrough)
  - "What I learned paper trading with an AI bot for 3 months" retrospective
  - Weekly performance updates with real metrics (win rate, expectancy, P&L curve)
  - Technical tutorials: "How to add a custom edge to DeepThinkTrader"

## Business Model
- **Revenue model:** Currently none — personal project and educational tool. Potential future paths: (1) Open-source with premium features (live trading mode, additional data sources, cloud hosting), (2) SaaS dashboard-as-a-service for non-technical traders, (3) Marketplace for custom trading strategies/edges, (4) Educational course on building AI trading systems.
- **Key metrics:**
  - Paper trading performance: win rate, expectancy per trade, max drawdown, Sharpe ratio
  - System reliability: uptime, trades executed vs blocked, exit check coverage
  - Strategy health: win rate delta over time, profit factor trend
  - (If open-sourced) GitHub stars, forks, contributors, community engagement
- **Growth stage:** Pre-launch / internal paper trading validation. The bot is functionally complete (v2.0) with all P0 and P1 features implemented. Currently in the "prove the edge" phase — accumulating paper trading history to validate the strategy before considering live trading or public release.
