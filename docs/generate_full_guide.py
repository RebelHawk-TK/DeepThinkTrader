"""Generate comprehensive PDF guide for DeepThinkTrader v1.0."""

from datetime import datetime


def generate_html() -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body {{ font-family: 'Helvetica Neue', Arial, sans-serif; margin: 40px; color: #1a1a1a; line-height: 1.6; font-size: 13px; }}
    h1 {{ color: #0d47a1; border-bottom: 3px solid #0d47a1; padding-bottom: 10px; font-size: 24px; }}
    h2 {{ color: #1565c0; margin-top: 30px; border-bottom: 1px solid #e0e0e0; padding-bottom: 5px; font-size: 18px; }}
    h3 {{ color: #1976d2; font-size: 15px; }}
    .warning {{ background: #fff3e0; border-left: 4px solid #ff9800; padding: 12px; margin: 15px 0; border-radius: 4px; }}
    .info {{ background: #e3f2fd; border-left: 4px solid #2196f3; padding: 12px; margin: 15px 0; border-radius: 4px; }}
    .danger {{ background: #fce4ec; border-left: 4px solid #f44336; padding: 12px; margin: 15px 0; border-radius: 4px; }}
    .success {{ background: #e8f5e9; border-left: 4px solid #4caf50; padding: 12px; margin: 15px 0; border-radius: 4px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 12px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
    th {{ background: #1565c0; color: white; }}
    tr:nth-child(even) {{ background: #f5f5f5; }}
    code {{ background: #f5f5f5; padding: 2px 5px; border-radius: 3px; font-size: 0.9em; }}
    pre {{ background: #263238; color: #aed581; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 12px; }}
    .page-break {{ page-break-before: always; }}
    .footer {{ margin-top: 30px; padding-top: 10px; border-top: 1px solid #ddd; color: #666; font-size: 0.85em; }}
    .two-col {{ display: flex; gap: 20px; }}
    .two-col > div {{ flex: 1; }}
</style>
</head>
<body>

<h1>DeepThinkTrader v1.0 — Complete System Guide</h1>
<p><strong>Generated:</strong> {datetime.now().strftime('%B %d, %Y')} &nbsp;|&nbsp; <strong>Repository:</strong> github.com/RebelHawk-TK/DeepThinkTrader</p>

<div class="danger">
<strong>CRITICAL WARNING:</strong> This is a paper trading bot. Never use real money until backtested for 3+ months.
Trading bots can lose 100% of capital. This project is educational and experimental.
</div>

<h2>1. Architecture Overview</h2>

<div class="info">
<strong>Pipeline:</strong> Scanner &rarr; Research Agent &rarr; AI DeepThink (Claude) &rarr; Execution Agent &rarr; Alpaca Paper Trading
</div>

<table>
<tr><th>Component</th><th>Technology</th><th>Purpose</th></tr>
<tr><td>Scanner Agent</td><td>Alpaca Screener API</td><td>Discovers 100 stocks/day from most active, top movers, news trending, popular large-caps</td></tr>
<tr><td>Research Agent</td><td>Alpaca + Twelve Data + NewsAPI + Yahoo Finance</td><td>Gathers technicals, fundamentals, news sentiment, analyst ratings, insider trades, earnings data</td></tr>
<tr><td>AI DeepThink Agent</td><td>Claude Haiku 4.5 (Anthropic API)</td><td>Chain-of-thought analysis using 5 institutional frameworks</td></tr>
<tr><td>Execution Agent</td><td>Alpaca Paper Trading API</td><td>Places trades with 8 risk guardrails, captures X-Request-ID</td></tr>
<tr><td>Dashboard</td><td>Streamlit + Plotly</td><td>Real-time portfolio monitoring, trade history, analyses</td></tr>
<tr><td>Database</td><td>SQLite</td><td>Trade logging, research reports, API request IDs</td></tr>
</table>

<h2>2. Data Sources</h2>

<table>
<tr><th>Source</th><th>Data Provided</th><th>API Key Required</th><th>Free Tier</th></tr>
<tr><td>Alpaca Markets</td><td>Price, volume, SMA, RSI, trade execution, portfolio history</td><td>Yes (paper account)</td><td>Unlimited</td></tr>
<tr><td>Twelve Data (RapidAPI)</td><td>MACD, Bollinger Bands, EMA 9/21, Stochastic, ADX, ATR</td><td>Yes (RapidAPI key)</td><td>800 req/day</td></tr>
<tr><td>NewsAPI</td><td>News headlines + VADER sentiment scoring</td><td>Yes</td><td>500 req/day</td></tr>
<tr><td>Yahoo Finance</td><td>P/E, revenue growth, margins, analyst targets, earnings dates, insider trades, institutional holdings</td><td>No</td><td>Unlimited</td></tr>
<tr><td>Anthropic Claude</td><td>AI chain-of-thought analysis</td><td>Yes</td><td>Pay per token (~$0.20/cycle)</td></tr>
<tr><td>Reddit (PRAW)</td><td>Sentiment from r/wallstreetbets, r/stocks, r/investing</td><td>Yes (optional)</td><td>60 req/min</td></tr>
</table>

<div class="page-break"></div>

<h2>3. AI Analysis Frameworks</h2>

<p>Every stock is analyzed by Claude through <strong>5 institutional-grade frameworks</strong>:</p>

<h3>3.1 Citadel Technical Analysis (25%)</h3>
<table>
<tr><th>Signal</th><th>BUY</th><th>SELL</th></tr>
<tr><td>MACD</td><td>Bullish crossover + histogram positive</td><td>Bearish crossover + histogram negative</td></tr>
<tr><td>RSI</td><td>30-50 recovering from oversold</td><td>&gt; 70 with bearish divergence</td></tr>
<tr><td>Stochastic</td><td>Bullish cross in oversold zone (K &lt; 20)</td><td>Bearish cross in overbought zone (K &gt; 80)</td></tr>
<tr><td>Bollinger</td><td>Bounce off lower band / squeeze breakout</td><td>Break below middle band, expanding bandwidth</td></tr>
<tr><td>ADX</td><td>&gt; 25 confirming uptrend</td><td>&gt; 25 confirming downtrend</td></tr>
<tr><td>Volume</td><td>&gt; 1.5x average (accumulation)</td><td>Declining on advances</td></tr>
</table>

<h3>3.2 Goldman Sachs Fundamental Analysis (25%)</h3>
<ul>
<li>Analyst consensus BUY with &gt; 15% upside to target</li>
<li>Revenue growth &gt; 10% with improving margins</li>
<li>P/E below sector average OR PEG &lt; 1.5</li>
<li>Insider net buying in last 30 days</li>
<li>Earnings beat rate &gt; 75% last 4 quarters</li>
</ul>

<h3>3.3 Catalyst Scoring (20%)</h3>
<ul>
<li>Positive news (new product, partnership, upgrade) with impact &gt; 5/10</li>
<li>Social sentiment turning positive</li>
<li>Sector tailwinds</li>
<li><strong>No catalyst = no trade</strong> (most important rule)</li>
</ul>

<h3>3.4 Renaissance Technologies Pattern Detection (15%)</h3>
<div class="two-col">
<div>
<strong>Seasonal Patterns:</strong>
<ul>
<li>Monday weakness, Friday drift up</li>
<li>Month-end institutional rebalancing</li>
<li>January small-cap effect</li>
<li>"Sell in May" seasonal weakness</li>
</ul>
<strong>Institutional Signals:</strong>
<ul>
<li>Ownership &gt; 70% = follow smart money</li>
<li>Increasing ownership = accumulation (bullish)</li>
<li>Decreasing ownership = distribution (bearish)</li>
</ul>
</div>
<div>
<strong>Insider Patterns:</strong>
<ul>
<li>Cluster buying (3+ insiders) = very strong bullish</li>
<li>CEO/CFO buying with personal money = strongest signal</li>
<li>Sudden large sales outside pattern = red flag</li>
</ul>
<strong>Price Anomalies:</strong>
<ul>
<li>Post-earnings drift (60 days)</li>
<li>Mean reversion (&gt; 2 std dev from 50-day)</li>
<li>Short interest &gt; 15% = squeeze potential</li>
<li>Volume spike + flat price = accumulation before move</li>
</ul>
</div>
</div>

<h3>3.5 Bridgewater Risk Management (15%)</h3>
<table>
<tr><th>Check</th><th>Rule</th><th>Action</th></tr>
<tr><td>Sector Concentration</td><td>Same sector &gt; 30% of portfolio</td><td>Reduce size 50% or HOLD</td></tr>
<tr><td>Correlation</td><td>Highly correlated with existing position</td><td>Flag in risks, prefer uncorrelated</td></tr>
<tr><td>Stress Test</td><td>5% market drop would cause &gt; 8% portfolio drawdown</td><td>HOLD — don't add risk</td></tr>
<tr><td>Liquidity</td><td>Avg volume &lt; 1M shares/day</td><td>Flag as low liquidity</td></tr>
<tr><td>Single Position</td><td>Position &gt; 10% of account</td><td>Reduce size</td></tr>
<tr><td>Beta Adjustment</td><td>Beta &gt; 1.5</td><td>Reduce size 30%</td></tr>
</table>

<div class="page-break"></div>

<h2>4. JPMorgan Earnings Framework</h2>

<table>
<tr><th>Days to Earnings</th><th>Action</th></tr>
<tr><td>&gt; 14 days</td><td>Trade normally</td></tr>
<tr><td>7-14 days</td><td>Reduce position size 30%</td></tr>
<tr><td>3-7 days</td><td>HOLD (unless explicit earnings play with conviction 9+)</td></tr>
<tr><td>&lt; 3 days</td><td>AUTOMATIC HOLD — binary event risk</td></tr>
</table>

<p><strong>Earnings Play Criteria</strong> (ALL must be met, conviction 9+):</p>
<ul>
<li>Beat rate &gt; 75% last 4 quarters</li>
<li>Revenue growth accelerating QoQ</li>
<li>Estimates recently revised upward</li>
<li>Historical post-earnings reaction positive</li>
<li>Options implied move &lt; historical average (market underpricing)</li>
</ul>

<h2>5. Risk Guardrails (Execution Agent)</h2>

<table>
<tr><th>#</th><th>Rule</th><th>Action if Triggered</th></tr>
<tr><td>1</td><td>Conviction &lt; 8/10</td><td>HOLD</td></tr>
<tr><td>2</td><td>Max loss per position &gt; 2% of account</td><td>BLOCKED</td></tr>
<tr><td>3</td><td>Take-profit &lt; 2x stop-loss</td><td>BLOCKED</td></tr>
<tr><td>4</td><td>Daily realized loss &gt; 5% of account</td><td>BLOCKED for rest of day</td></tr>
<tr><td>5</td><td>Already 5 open positions</td><td>BLOCKED</td></tr>
<tr><td>6</td><td>Duplicate position in same ticker</td><td>BLOCKED</td></tr>
<tr><td>7</td><td>Outside US market hours</td><td>BLOCKED</td></tr>
<tr><td>8</td><td>3+ consecutive losses (revenge trading)</td><td>BLOCKED + cooldown</td></tr>
</table>

<h2>6. Configuration (.env)</h2>

<pre>
# Alpaca API (Paper Trading)
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# Anthropic (Claude API)
ANTHROPIC_API_KEY=your_key

# RapidAPI (Twelve Data)
RAPIDAPI_KEY=your_key

# NewsAPI
NEWSAPI_KEY=your_key

# Reddit (Optional)
REDDIT_CLIENT_ID=your_id
REDDIT_CLIENT_SECRET=your_secret
REDDIT_USER_AGENT=DeepThinkTrader/1.0

# Trading Parameters
ACCOUNT_SIZE=100000
WATCHLIST=NVDA,TSLA,AAPL,AMD,SPY
MAX_RISK_PER_TRADE=0.02
MAX_DAILY_LOSS=0.05
MIN_CONVICTION=8
RESEARCH_INTERVAL_MINUTES=60
MIN_REWARD_RISK_RATIO=2.0
</pre>

<div class="page-break"></div>

<h2>7. Quick Start</h2>

<pre>
git clone https://github.com/RebelHawk-TK/DeepThinkTrader.git
cd DeepThinkTrader
cp .env.template .env        # Fill in your API keys
pip install -r requirements.txt
python main.py once           # Test single cycle
python main.py scan           # Test scanner
streamlit run dashboard.py    # Launch dashboard
./run.sh                      # Start bot + dashboard
./stop.sh                     # Stop everything
./status.sh                   # Check status
./install.sh                  # Install as macOS background service
</pre>

<h2>8. Estimated Costs</h2>

<table>
<tr><th>Service</th><th>Cost/Cycle (100 stocks)</th><th>Cost/Day (~7 cycles)</th><th>Cost/Month</th></tr>
<tr><td>Claude Haiku 4.5</td><td>~$0.20</td><td>~$1.40</td><td>~$42</td></tr>
<tr><td>Alpaca</td><td>Free</td><td>Free</td><td>Free</td></tr>
<tr><td>Twelve Data</td><td>Free (800 req/day)</td><td>Free</td><td>Free</td></tr>
<tr><td>NewsAPI</td><td>Free (500 req/day)</td><td>Free</td><td>Free</td></tr>
<tr><td>Yahoo Finance</td><td>Free</td><td>Free</td><td>Free</td></tr>
<tr><td><strong>Total</strong></td><td></td><td></td><td><strong>~$42/month</strong></td></tr>
</table>

<h2>9. Project Structure</h2>
<pre>
StockTrader/
├── main.py                    # Orchestrator (scheduled loop)
├── config.py                  # Environment config
├── dashboard.py               # Streamlit monitoring
├── run.sh / stop.sh / status.sh  # Control scripts
├── install.sh                 # macOS launchd installer
├── agents/
│   ├── ai_deepthink_agent.py  # Claude AI analysis (5 frameworks)
│   ├── deepthink_agent.py     # Rule-based fallback
│   ├── execution_agent.py     # Alpaca trades + risk guardrails
│   ├── research_agent.py      # Multi-source data gathering
│   └── scanner_agent.py       # 100-stock daily discovery
├── utils/
│   ├── alpaca_data.py         # Alpaca market data + X-Request-ID
│   ├── database.py            # SQLite trade logging
│   ├── risk_manager.py        # Position sizing + daily limits
│   ├── twelve_data.py         # MACD, Bollinger, EMA, Stochastic, ADX, ATR
│   └── yahoo_fundamentals.py  # P/E, earnings, analysts, insiders
├── .env.template              # API key template
├── requirements.txt           # Python dependencies
└── docs/                      # Documentation + setup guide PDF
</pre>

<div class="footer">
<p><strong>DeepThinkTrader v1.0</strong> &mdash; Paper Trading Mode Only &mdash; github.com/RebelHawk-TK/DeepThinkTrader</p>
<p>Generated {datetime.now().strftime('%B %d, %Y')} | For educational/experimental use only</p>
</div>

</body>
</html>"""


if __name__ == "__main__":
    import subprocess
    import tempfile
    import os

    html_content = generate_html()
    html_path = os.path.join(tempfile.gettempdir(), "full_guide.html")
    pdf_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "DeepThinkTrader-Full-Guide.pdf")

    with open(html_path, "w") as f:
        f.write(html_content)

    subprocess.run([
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "--headless", "--disable-gpu", "--no-sandbox",
        f"--print-to-pdf={os.path.abspath(pdf_path)}",
        f"file://{html_path}"
    ], check=True, capture_output=True)
    print(f"PDF generated: {pdf_path}")
