# Jobs-to-be-Done Analysis — DeepThinkTrader

## Context

- **Target customer segment:** Tech-savvy retail traders (25-50) with a software engineering or quantitative background who understand trading fundamentals but lack the discipline, time, or systematic infrastructure to trade consistently. Secondary: algorithmic trading enthusiasts and hobbyist quants who want a customizable framework.
- **Situation:** The job arises when a retail trader sits down to manage their portfolio — scanning for opportunities, researching candidates, deciding entry/exit points, sizing positions, and monitoring open trades — while also holding down a full-time non-trading job. The job intensifies after a string of emotional trading losses (revenge trades, FOMO buys, panic sells) or when the trader realizes they have no idea what their actual win rate or expectancy is.
- **Current solutions (what they "hire" today):**
  - Manual trading with TradingView charts + a retail broker (the default)
  - Alpaca community bots and example algos (simple signal-based, minimal risk controls)
  - QuantConnect / Zipline (backtesting-focused frameworks, steep learning curve)
  - Trade Ideas / TrendSpider (subscription SaaS scanners, no autonomous execution)
  - Roboadvisors like Wealthfront / Betterment (no customization, no individual stocks)
  - ChatGPT / Claude for ad-hoc stock analysis (no execution, no risk management, no persistence)
  - Spreadsheets and manual trade journals (labor-intensive, easily abandoned)
  - Doing nothing — holding index funds and avoiding active trading entirely

---

## 1. Customer Jobs

### Functional Jobs

1. **Research 50+ stock candidates per cycle without manual effort** — Aggregate news, social sentiment, technicals, and fundamentals across a broad universe of tickers on a regular schedule, not just when I remember to look.
2. **Enforce pre-trade risk management rules consistently** — Apply position sizing, drawdown limits, sector exposure caps, liquidity checks, and minimum conviction thresholds to every single trade without exception.
3. **Monitor open positions continuously during market hours** — Check trailing stops, partial exit targets, time stops, earnings proximity, and market circuit breakers every few minutes, not just when I glance at my phone.
4. **Execute trades with precise bracket orders automatically** — Place entry, stop-loss, and take-profit orders as a unit so that every trade has defined risk from the moment it opens.
5. **Evaluate trade quality through structured, multi-factor analysis** — Score each candidate against technical, sentiment, fundamental, and qualitative edges before committing capital, requiring alignment across multiple independent signals.
6. **Track actual trading performance with real metrics** — Record every trade with full audit trail and compute win rate, expectancy, profit factor, max drawdown, and Sharpe ratio from real data, not gut feeling.
7. **Discover trade candidates I would not find scanning manually** — Surface opportunities from dynamic sector movers, unusual sentiment spikes, and news catalysts across a broader universe than I can cover by hand.
8. **Paper-test a complete strategy before risking real capital** — Run the full pipeline (research, analysis, execution, exit management) against live market data in a paper account to validate the edge exists.
9. **Exit losing positions early and systematically** — Cut losses at predetermined stop levels, exit dead positions after a time limit, and close before earnings events without requiring a willpower-based decision.
10. **Scale out of winning positions at predefined targets** — Take partial profits at 1R and 2R while letting the remainder run with a trailing stop, removing the "should I sell now?" decision.

### Social Jobs

1. **Be seen as a disciplined, data-driven trader** — Among trading peers and communities (r/algotrading, r/stocks), be perceived as someone who trades with a system and metrics rather than hot tips and gut feelings.
2. **Demonstrate technical sophistication to peers** — Show the ability to build, configure, and operate a multi-agent trading system, signaling competence in both software engineering and quantitative finance.
3. **Earn credibility by sharing transparent, verifiable results** — Post real paper-trading performance with full trade logs, win rates, and P&L curves — not cherry-picked screenshots — to build reputation in trading communities.
4. **Avoid being seen as a gambling retail trader** — Distance from the "meme stock gambler" stereotype by having a systematic, risk-first approach with documented reasoning for every trade.

### Emotional Jobs

1. **Feel confident that my capital is protected by hard rules** — Know that no single trade can blow up the account because 13 pre-trade checks, Kelly sizing, and circuit breakers are enforced by code, not willpower.
2. **Eliminate the anxiety of watching positions all day** — Trust that the system is monitoring every 5 minutes and will execute exits according to plan, so I can focus on my day job.
3. **Avoid the regret and self-blame of emotional trading decisions** — Never again experience the shame spiral of a revenge trade, a FOMO buy at the top, or a panic sell at the bottom.
4. **Feel in control of my trading process even when I am not actively trading** — Have certainty that research is happening on schedule, positions are being managed, and the system is enforcing my rules while I sleep or work.
5. **Experience the satisfaction of a well-executed systematic process** — Derive enjoyment from building and refining a trading system rather than from the dopamine hit of individual winning trades.
6. **Avoid the dread of checking a portfolio after being away** — Trust that stops were honored and exits were executed, so opening the dashboard is informational, not terrifying.

---

## 2. Pains

### Challenges

1. **Emotion overrides rules at the moment of decision** — The trader knows they should cut a loss at -2%, but in the moment, they hold because "it might come back," violating their own plan.
2. **Cannot monitor markets during working hours** — Full-time employment makes it impossible to watch positions, check news, or execute exits in real time.
3. **Information is fragmented across many sources** — News on one site, Reddit sentiment on another, technicals on TradingView, fundamentals on another — synthesizing them manually is exhausting and error-prone.
4. **Existing algo platforms have a steep learning curve** — QuantConnect and Zipline require extensive backtesting infrastructure knowledge; most retail traders give up before building anything useful.
5. **No single tool combines research, analysis, risk management, and execution** — Current solutions handle one or two of these; the trader must stitch together a workflow from multiple disconnected tools.
6. **Revenge trading after losses is nearly impossible to resist without external enforcement** — After 3 consecutive losses, the impulse to "make it back" is overwhelming and leads to oversized, poorly researched trades.

### Costliness

1. **Manual stock research for 50+ tickers takes 4-8 hours per session** — Reading news, checking charts, scanning Reddit, reviewing financials — doing this properly for a broad watchlist is a part-time job.
2. **Subscription fatigue from multiple data and scanning tools** — TradingView Pro ($15-60/mo), Trade Ideas ($120+/mo), Seeking Alpha Premium ($240/yr), news terminals — costs add up fast for retail traders.
3. **Losses from poor position sizing compound over time** — Without Kelly-calibrated sizing, a few oversized losers can wipe out months of gains, and most retail traders size by "feel."
4. **Time spent maintaining a manual trade journal is rarely sustained** — Traders start journals, maintain them for a week, then abandon them — losing the ability to learn from their own history.
5. **Emotional recovery time after a bad trading day is non-trivial** — A blown stop or revenge trade can ruin focus for the rest of the day (or week), affecting both trading and primary employment.

### Common Mistakes

1. **Holding losing positions past the stop-loss level** — "It'll come back" is the most expensive sentence in retail trading; traders routinely turn small losses into portfolio-damaging ones.
2. **Oversizing positions based on conviction alone without calculating risk** — Putting 10% of the account into a "sure thing" without computing Kelly fraction or risk-of-ruin probability.
3. **Entering trades based on a single signal (news headline, Reddit hype, one technical indicator)** — Failing to require multi-source validation, leading to trades with weak or nonexistent edges.
4. **Ignoring earnings dates and getting blindsided by gaps** — Holding a position through earnings without realizing the date was approaching, resulting in a gap loss that blows through the stop.
5. **Failing to take partial profits and watching winners reverse into losers** — Greed prevents selling any shares while the trade is working, then the position reverses and the trader exits at breakeven or a loss.
6. **Trading during a broad market selloff** — Buying individual stocks while SPY is in freefall, fighting the macro trend.

### Unresolved Problems

1. **No accessible tool provides autonomous end-to-end trading with transparent reasoning** — Existing bots either execute without explaining why, or provide analysis without executing.
2. **Retail traders have no way to enforce their own rules programmatically** — They write rules in a journal but have no mechanism to make those rules binding at execution time.
3. **Post-trade learning is almost nonexistent for retail traders** — Without automated strategy health checks, win rate tracking, and edge degradation monitoring, traders repeat the same mistakes indefinitely.
4. **Dynamic watchlist construction is manual and biased** — Traders watch the same 5-10 stocks they "like" rather than systematically scanning the market for where the action is today.
5. **Plain-English trade rationale is never recorded** — Even if a trade is logged, the reasoning behind it is lost, making post-trade review superficial.

---

## 3. Gains

### Expectations

1. **Every trade comes with a plain-English explanation of the thesis, the edge, and the invalidation criteria** — Transparency that allows the trader to understand and learn from the system's reasoning.
2. **Research runs automatically on a fixed schedule without manual intervention** — The system scans the universe, gathers data, and scores candidates every 60 minutes during market hours.
3. **Positions are monitored and managed every 5 minutes with trailing stops, partial exits, and time stops** — Exit management runs independently of the research cycle.
4. **Risk controls are absolute and non-negotiable** — The system will refuse to trade if drawdown limits are hit, conviction is too low, liquidity is insufficient, or the market circuit breaker is triggered.
5. **Strategy health is tracked automatically with degradation warnings** — Weekly learning loops compute win rate trends, profit factor, and alert when edge may be decaying.
6. **Full trade audit trail in SQLite with Alpaca order IDs** — Every entry, exit, partial fill, and trailing stop adjustment is logged with timestamps and rationale.

### Savings

1. **Reduce daily research time from 4-8 hours to zero active hours** — The multi-agent pipeline handles scanning, research, analysis, and execution autonomously.
2. **Eliminate subscription costs for scanning tools** — Free-tier APIs (NewsAPI, Reddit, yfinance) plus optional Anthropic API replace $200+/month in subscription tools.
3. **Prevent outsized losses through automated position sizing and stop enforcement** — Kelly-calibrated sizing and hard stops eliminate the most expensive retail trading mistakes.
4. **Recover the cognitive bandwidth consumed by position monitoring during work hours** — Knowing the system is watching every 5 minutes frees mental energy for the primary job.
5. **Eliminate trade journal maintenance effort** — SQLite database with automated logging replaces a manual journal that would otherwise be abandoned within weeks.

### Adoption Factors

1. **Paper trading mode by default — zero financial risk to try** — The system runs on a $50K Alpaca paper account, so the trader can validate the approach without risking real capital.
2. **Simple setup: clone, install, add API keys, run** — Three free API keys (Alpaca, NewsAPI, Reddit) and a `pip install` gets the system running in under 15 minutes.
3. **Open-source and fully inspectable** — Every line of logic is readable; the trader can verify the risk rules, modify parameters, and add custom edges.
4. **Streamlit dashboard provides immediate visual feedback** — Real-time equity curve, trade log, strategy health metrics, and live market ticker bar make the system tangible from day one.
5. **Configurable trade modes (Safe / Normal / Aggressive)** — The trader can start conservative and dial up risk as confidence builds, rather than committing to a single risk profile.
6. **Runs as a macOS service (launchd) with auto-start on boot** — Set it up once and it runs in the background indefinitely without manual intervention.

### Life Improvement

1. **Trade with discipline without requiring personal discipline** — The system enforces the rules the trader already knows are correct but cannot consistently follow.
2. **Focus on the day job without anxiety about open positions** — Continuous monitoring and automated exit management remove the need to check a brokerage app every 15 minutes.
3. **Learn from actual performance data instead of feelings** — Real win rate, expectancy, and drawdown metrics replace "I think I'm doing okay" with objective truth.
4. **Experience trading as a systematic craft rather than a stressful gamble** — Shift the relationship with the market from emotional gambling to disciplined research and execution.
5. **Reclaim evenings and weekends previously spent on stock research** — Automated research cycles replace manual scanning sessions that consumed leisure time.
6. **Build a compounding knowledge base from post-trade analysis** — Each trade adds to a structured database that reveals which edges work, which decay, and how to improve.

---

## 4. Job Map

The job map traces the end-to-end workflow of the core functional job: "Systematically research and trade stocks with enforced risk management."

| Stage | Job Step | What the Customer Does Today | What DeepThinkTrader Does |
|-------|----------|------------------------------|---------------------------|
| **1. Define** | Decide which stocks to watch | Picks favorites, follows Reddit tips | Dynamic sector watchlist rebuilt daily from market movers + 60-stock scanner universe |
| **2. Locate** | Find relevant news and sentiment | Manually checks 3-5 news sites, scrolls Reddit | NewsAPI + Reddit VADER + Seeking Alpha aggregation per ticker |
| **3. Prepare** | Gather technical and fundamental data | Opens TradingView, reads yfinance, checks earnings calendar | yfinance + Twelve Data technical indicators + earnings proximity check |
| **4. Confirm** | Validate that multiple signals align | Mental checklist, often skipped under time pressure | Multi-edge validation requiring 2/3 edges (technical + sentiment + fundamental) |
| **5. Analyze** | Form a thesis with conviction level | Gut feeling, often biased by recency or anchoring | DeepThink Agent: rule-based scoring + Claude AI qualitative analysis with contrarian reasoning |
| **6. Size** | Determine position size | "I'll put $5K in" (arbitrary) | Kelly-calibrated position sizing with 13 pre-trade risk checks |
| **7. Execute** | Place the trade | Manual broker order, often market order | Alpaca bracket orders (entry + stop-loss + take-profit) with limit orders for penny stocks |
| **8. Monitor** | Watch the position | Checks phone intermittently, misses moves | 5-minute exit monitoring: trailing stops, partial scale-outs, time stops, earnings exits, circuit breaker |
| **9. Exit** | Close the position | Holds too long (losers) or sells too early (winners) | Automated: trailing stop at 1.5%, partial exits at 1R/2R, time stop at 15 days, earnings exit at T-2 |
| **10. Review** | Learn from the trade | Rarely done; no structured process | Weekly learning loop with strategy health check, win rate delta, and auto-degradation warnings |

---

## 5. Outcome Expectations

Outcome expectations define measurable success criteria for each major job, using the format: **Direction + Metric + Object of Control**.

| # | Outcome Statement | Priority |
|---|-------------------|----------|
| 1 | **Minimize** the time spent manually researching stock candidates per cycle | Critical |
| 2 | **Minimize** the number of trades that violate predefined risk rules | Critical |
| 3 | **Minimize** the frequency of holding losing positions past stop-loss levels | Critical |
| 4 | **Minimize** the occurrence of oversized positions relative to Kelly-optimal sizing | High |
| 5 | **Minimize** the time between a stop-loss trigger event and actual exit execution | High |
| 6 | **Maximize** the number of independent data sources confirming each trade thesis | High |
| 7 | **Maximize** the transparency and traceability of trade reasoning | High |
| 8 | **Minimize** the cognitive load of monitoring open positions during working hours | High |
| 9 | **Maximize** the accuracy of real-time strategy health assessment | Medium |
| 10 | **Minimize** the effort required to compute actual trading performance metrics | Medium |
| 11 | **Maximize** the percentage of winning positions where partial profits are captured | Medium |
| 12 | **Minimize** the likelihood of entering trades during broad market selloffs | Medium |
| 13 | **Minimize** the risk of holding through an earnings event unintentionally | Medium |
| 14 | **Maximize** the diversity of the scanned stock universe beyond personal bias | Low |
| 15 | **Minimize** the setup effort to go from zero to a running paper trading system | Low |

---

## 6. Hire and Fire Criteria

### Why a customer "hires" DeepThinkTrader

| Hire Trigger | Underlying Job |
|---|---|
| "I just revenge-traded after a losing streak and blew through my weekly loss limit" | Enforce risk rules programmatically so emotion cannot override discipline |
| "I missed a trailing stop because I was in a meeting and the stock reversed 8%" | Monitor positions continuously without requiring active attention |
| "I spent 6 hours on a Sunday researching stocks and still only looked at 12 tickers" | Automate multi-source research across 50+ tickers per cycle |
| "I have no idea what my actual win rate is — I just remember the big winners" | Track real performance metrics with full audit trail |
| "I want to algo-trade but QuantConnect is way too complex for what I need" | Provide a usable, inspectable trading system without requiring quant infrastructure expertise |
| "I keep buying stocks based on one Reddit post and getting burned" | Require multi-edge validation before any trade executes |

### Why a customer "fires" DeepThinkTrader

| Fire Trigger | Root Cause |
|---|---|
| "The bot made trades I don't understand and can't explain" | Lack of transparency — plain-English summaries must be clear and complete |
| "It missed an obvious trade that any human would have taken" | Conviction threshold or edge requirements too strict — system overly conservative |
| "Setup took me 2 hours and it still didn't work" | Friction in installation, API key configuration, or dependency management |
| "The paper trading results don't translate to anything meaningful" | No clear path from paper to live trading; system feels like a toy |
| "I can't customize the risk parameters or add my own signals" | Closed architecture; lack of extensibility for the tinkering audience |
| "It traded fine for a month, then the edge decayed and it kept losing" | Strategy health monitoring failed to detect and halt degraded performance |
| "I don't trust it enough to stop manually intervening" | Insufficient track record or transparency to build trust in autonomous decisions |

---

## 7. Pain Intensity Prioritization

| Rank | Pain | Intensity | Frequency | Impact |
|------|------|-----------|-----------|--------|
| 1 | Emotion overrides risk rules at the moment of decision | Acute | Every trading session | Portfolio-damaging losses |
| 2 | Cannot monitor positions during work hours | Acute | Daily | Missed exits, blown stops |
| 3 | Holding losers past stop-loss levels | Acute | Weekly | Largest single source of retail losses |
| 4 | No accessible tool combines research + analysis + execution + risk | Acute | Persistent | Forces manual multi-tool workflow |
| 5 | Manual research for 50+ tickers takes 4-8 hours | High | Weekly | Limits opportunity discovery |
| 6 | Revenge trading after consecutive losses | High | Monthly | Account drawdown acceleration |
| 7 | No actual performance tracking (win rate, expectancy) | Moderate | Persistent | Cannot learn or improve |
| 8 | Ignoring earnings dates leading to gap losses | Moderate | Quarterly | Preventable large losses |
| 9 | Oversizing positions without Kelly calculation | Moderate | Frequent | Accelerates drawdown |
| 10 | Subscription cost fatigue across scanning tools | Mild | Monthly | Budget drag |

---

## 8. Gain Priority (Must-Have vs. Nice-to-Have)

### Must-Have (Drive Adoption)

- Automated position monitoring with trailing stops and exit enforcement
- Pre-trade risk checks that cannot be bypassed
- Multi-source research running on a fixed schedule without manual effort
- Plain-English trade rationale for every entry and exit
- Paper trading mode with zero financial risk to validate the system

### Nice-to-Have (Delight, Don't Drive Switching)

- Streamlit dashboard with equity curves and live market ticker
- Configurable trade modes (Safe / Normal / Aggressive)
- Weekly strategy health reports with degradation warnings
- Penny stock portfolio running alongside main portfolio
- macOS launchd auto-start integration
- Dynamic watchlist rebuilt daily from market movers

---

*Analysis based on product-marketing-context.md, vision.md, prd.md, and README.md. Grounded in documented target audience research and pain points. Should be validated with real user interviews before informing major product decisions.*
