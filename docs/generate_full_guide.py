"""Generate comprehensive PDF guide for DeepThinkTrader v2.0."""

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

<h1>DeepThinkTrader v2.0 — Complete System Guide</h1>
<p><strong>Generated:</strong> {datetime.now().strftime('%B %d, %Y')} &nbsp;|&nbsp; <strong>Repository:</strong> github.com/RebelHawk-TK/DeepThinkTrader</p>

<div class="danger">
<strong>CRITICAL WARNING:</strong> This is a paper trading bot. Never use real money until backtested for 3+ months.
Trading bots can lose 100% of capital. This project is educational and experimental.
</div>

<h2>1. Architecture Overview</h2>

<div class="info">
<strong>Pipeline:</strong> Scanner &rarr; Research Agent &rarr; DeepThink Analysis (Rule-Based + Multi-Edge) &rarr; Risk Gate (13 checks) &rarr; Execution Agent &rarr; Alpaca Paper Trading
</div>

<table>
<tr><th>Component</th><th>Technology</th><th>Purpose</th></tr>
<tr><td>Scanner Agent</td><td>Alpaca Screener API</td><td>3-stage funnel: discovery, pre-screen, scoring — main + penny ($1-$5)</td></tr>
<tr><td>Research Agent</td><td>Alpaca + Twelve Data + NewsAPI + Yahoo Finance</td><td>Gathers technicals, fundamentals, news sentiment, analyst ratings, insider trades, earnings data</td></tr>
<tr><td>DeepThink Agent</td><td>Rule-based scoring + multi-edge validation</td><td>Conviction scoring, scenario modeling, 3-edge confirmation (Fund/Tech/Sentiment)</td></tr>
<tr><td>Risk Manager</td><td>Kelly criterion + portfolio guards</td><td>13 pre-trade checks: Kelly sizing, drawdown halt, circuit breaker, liquidity, earnings</td></tr>
<tr><td>Execution Agent</td><td>Alpaca Paper Trading API</td><td>Market/limit orders, trailing stops, partial scale-out, time stops, slippage tracking</td></tr>
<tr><td>Dashboard</td><td>Streamlit + Plotly</td><td>Real-time portfolio monitoring, trade history, strategy health</td></tr>
<tr><td>Database</td><td>SQLite</td><td>Trade logging, research reports, trailing stops, partial exits, API request IDs</td></tr>
</table>

<h2>2. Data Sources</h2>

<table>
<tr><th>Source</th><th>Data Provided</th><th>API Key Required</th><th>Free Tier</th></tr>
<tr><td>Alpaca Markets</td><td>Price, volume, SMA, RSI, trade execution, portfolio history, SPY snapshots</td><td>Yes (paper account)</td><td>Unlimited</td></tr>
<tr><td>Twelve Data (RapidAPI)</td><td>MACD, Bollinger Bands, EMA 9/21, Stochastic, ADX, ATR</td><td>Yes (RapidAPI key)</td><td>800 req/day</td></tr>
<tr><td>NewsAPI</td><td>News headlines + VADER sentiment scoring</td><td>Yes</td><td>500 req/day</td></tr>
<tr><td>Yahoo Finance</td><td>P/E, ROE, growth, debt/equity, earnings dates, insider trades, institutional holdings</td><td>No</td><td>Unlimited</td></tr>
<tr><td>Reddit (PRAW)</td><td>Sentiment from r/wallstreetbets, r/stocks, r/investing, r/pennystocks</td><td>Yes (optional)</td><td>60 req/min</td></tr>
</table>

<div class="page-break"></div>

<h2>3. Risk-First Framework (v2.0)</h2>

<div class="success">
<strong>Philosophy:</strong> Every trade must pass through a rigorous, emotion-proof checklist before execution.
No trade executes on conviction alone &mdash; it requires multi-edge confirmation and portfolio-level safety.
</div>

<h3>3.1 Position Sizing: Fractional Kelly</h3>
<table>
<tr><th>Condition</th><th>Method</th><th>Formula</th></tr>
<tr><td>20+ closed trades</td><td>Fractional Kelly</td><td>f* = (p - q) / b &times; 0.5 (half-Kelly)</td></tr>
<tr><td>&lt; 20 trades</td><td>Fixed Risk</td><td>1% of equity per trade</td></tr>
</table>
<p>Where p = win rate, q = 1 - p, b = avg win / avg loss (payoff ratio). Capped at MAX_POSITION_PCT.</p>

<h3>3.2 Pre-Trade Checks (13 gates)</h3>
<table>
<tr><th>#</th><th>Check</th><th>Action if Failed</th></tr>
<tr><td>1</td><td>Conviction meets threshold</td><td>HOLD</td></tr>
<tr><td>2</td><td>Risk within limit</td><td>BLOCKED</td></tr>
<tr><td>3</td><td>Reward:Risk ratio acceptable</td><td>BLOCKED</td></tr>
<tr><td>4</td><td>Daily loss limit OK</td><td>BLOCKED for rest of day</td></tr>
<tr><td>5</td><td>Open position count OK</td><td>BLOCKED</td></tr>
<tr><td>6</td><td>No duplicate position</td><td>BLOCKED</td></tr>
<tr><td>7</td><td>Market hours</td><td>BLOCKED</td></tr>
<tr><td>8</td><td>Drawdown from peak &lt; 8%</td><td>BLOCKED (all new entries)</td></tr>
<tr><td>9</td><td>Risk of ruin &lt; 1%</td><td>BLOCKED</td></tr>
<tr><td>10</td><td>Liquidity: shares &lt; ADV/5</td><td>Auto-reduce or BLOCKED</td></tr>
<tr><td>11</td><td>Multi-edge: 2/3 edges firing</td><td>HOLD</td></tr>
<tr><td>12</td><td>Market health: SPY not down &gt; 2%</td><td>BLOCKED (longs only)</td></tr>
<tr><td>13</td><td>No earnings within 2 days</td><td>Auto-close or BLOCKED</td></tr>
</table>

<h3>3.3 Volatility Adjustment</h3>
<p>If current ATR &gt; 3&times; median ATR (50-day), risk percentage is automatically cut in half.</p>

<h3>3.4 Revenge Trading Detector</h3>
<p>If last 3 trades are all losses, all new entries are blocked until a winning trade occurs.</p>

<div class="page-break"></div>

<h2>4. Multi-Edge Validation (v2.0)</h2>

<div class="warning">
<strong>Rule:</strong> A trade requires at least <strong>2 of 3 independent edges</strong> to execute. Conviction score alone is not enough.
</div>

<h3>4.1 Fundamental Edge</h3>
<p>Must pass at least 3 of 4 criteria:</p>
<table>
<tr><th>Criterion</th><th>Threshold</th></tr>
<tr><td>P/E ratio</td><td>&lt; 20 or forward P/E improving</td></tr>
<tr><td>Return on Equity</td><td>&gt; 15%</td></tr>
<tr><td>Earnings/Revenue Growth</td><td>&gt; 10% YoY</td></tr>
<tr><td>Debt/Equity</td><td>&lt; 100</td></tr>
</table>

<h3>4.2 Technical Edge</h3>
<p>Must pass at least 2 of 3 criteria:</p>
<table>
<tr><th>Criterion</th><th>Threshold</th></tr>
<tr><td>Price vs 200-day SMA</td><td>Above (for longs)</td></tr>
<tr><td>RSI(14)</td><td>&lt; 45 (neutral-bullish) or &lt; 30 (oversold)</td></tr>
<tr><td>Volume breakout</td><td>&gt; 1.5&times; 20-day average</td></tr>
</table>

<h3>4.3 Sentiment/Regime Edge</h3>
<p>Must pass at least 2 of 3 criteria:</p>
<table>
<tr><th>Criterion</th><th>Threshold</th></tr>
<tr><td>Combined catalyst score</td><td>&gt; 0.2</td></tr>
<tr><td>News sentiment</td><td>&gt; 2/10 (bullish)</td></tr>
<tr><td>Reddit sentiment</td><td>&gt; 0.3 (bullish)</td></tr>
</table>

<h2>5. Exit Management (v2.0)</h2>

<h3>5.1 Exit Check Frequency</h3>
<table>
<tr><th>Check Type</th><th>Frequency</th><th>What It Does</th></tr>
<tr><td>Fast exit check</td><td>Every 5 minutes</td><td>Price checks only — SL/TP/trailing/time stops</td></tr>
<tr><td>Full cycle</td><td>Every 60 minutes</td><td>Full scan + research + analysis + execution</td></tr>
</table>

<h3>5.2 Trailing Stops</h3>
<table>
<tr><th>Parameter</th><th>Main Portfolio</th><th>Penny Portfolio</th></tr>
<tr><td>Activation</td><td>2% profit</td><td>2% profit</td></tr>
<tr><td>Trail distance</td><td>1.5%</td><td>3.0%</td></tr>
</table>
<p>Once activated, trailing stop replaces static stop-loss. Static take-profit still applies.</p>

<h3>5.3 Partial Scale-Out</h3>
<table>
<tr><th>Profit Level</th><th>Action</th><th>Remaining</th></tr>
<tr><td>1R (1&times; risk amount)</td><td>Sell 33% of position</td><td>67%</td></tr>
<tr><td>2R (2&times; risk amount)</td><td>Sell another 33%</td><td>34%</td></tr>
<tr><td>3R+ or trailing stop</td><td>Remaining 34% rides with trail</td><td>0%</td></tr>
</table>

<h3>5.4 Time Stop</h3>
<p>If a position shows &lt; 2% movement after 15 trading days, it is automatically closed to free capital.</p>

<h3>5.5 Earnings Auto-Exit</h3>
<p>If earnings are within 2 trading days, position is automatically closed (configurable: close or tighten SL 50%).</p>

<div class="page-break"></div>

<h2>6. Smart Order Execution (v2.0)</h2>

<h3>6.1 Order Types</h3>
<table>
<tr><th>Portfolio</th><th>Order Type</th><th>Details</th></tr>
<tr><td>Main</td><td>Market order</td><td>Immediate fill, slippage tracked</td></tr>
<tr><td>Penny</td><td>Limit order</td><td>Current price + 0.5% slippage buffer, day TIF, auto-cancel after 30 min</td></tr>
</table>

<h3>6.2 Slippage Tracking</h3>
<p>After fill, actual price is compared to expected. Deviations &gt; 0.3% are logged as slippage alerts.</p>

<h3>6.3 Pre-Trade Transparency</h3>
<p>Every trade logs a plain-English summary before execution:</p>
<pre>
BUY 120 shares of XYZ @ $4.50
  Risk: $54 (0.1% of portfolio) | Edges: 2/3
  R:R = 2.4:1 | Stop: $4.05 | Target: $5.58
  Portfolio: penny | ADV: 500,000
</pre>

<h2>7. Market Circuit Breaker</h2>

<table>
<tr><th>Trigger</th><th>Action</th></tr>
<tr><td>SPY down &gt; 2% intraday</td><td>Block all new LONG entries (shorts still OK)</td></tr>
<tr><td>30-day drawdown &gt; 8%</td><td>Block ALL new entries (not exits)</td></tr>
<tr><td>Negative expectancy</td><td>Block trades (risk of ruin too high)</td></tr>
</table>

<h2>8. Post-Trade Learning (v2.0)</h2>

<h3>8.1 Strategy Health Metrics</h3>
<table>
<tr><th>Metric</th><th>Description</th></tr>
<tr><td>Win Rate (30d)</td><td>% of trades that were profitable</td></tr>
<tr><td>Expectancy</td><td>(win_rate &times; avg_win) - (loss_rate &times; avg_loss)</td></tr>
<tr><td>Profit Factor</td><td>Gross wins / gross losses</td></tr>
<tr><td>Payoff Ratio</td><td>Avg win / avg loss</td></tr>
<tr><td>WR vs Baseline</td><td>30-day win rate vs 90-day baseline</td></tr>
</table>

<h3>8.2 Kelly Feedback Loop</h3>
<p>Win rate and payoff ratio from closed trades feed directly into position sizing.
As strategy performs better, Kelly sizes up. As it degrades, sizing shrinks automatically.</p>

<h3>8.3 Weekly Health Check (Monday)</h3>
<p>If 30-day win rate drops &gt; 15% from 90-day baseline, a degradation warning is logged.</p>

<div class="page-break"></div>

<h2>9. Configuration</h2>

<h3>9.1 Trade Modes</h3>
<table>
<tr><th>Parameter</th><th>Safe</th><th>Normal</th><th>Aggressive</th></tr>
<tr><td>Max Risk/Trade</td><td>1%</td><td>2%</td><td>3%</td></tr>
<tr><td>Daily Loss Limit</td><td>3%</td><td>5%</td><td>8%</td></tr>
<tr><td>Min Conviction</td><td>9.0</td><td>7.5</td><td>6.0</td></tr>
<tr><td>Min R:R Ratio</td><td>3:1</td><td>2:1</td><td>1.5:1</td></tr>
<tr><td>Max Position %</td><td>5%</td><td>10%</td><td>15%</td></tr>
<tr><td>Max Positions</td><td>5</td><td>10</td><td>15</td></tr>
</table>

<h3>9.2 Risk-First Parameters (v2.0)</h3>
<pre>
# Risk Gate
RISK_PCT_PER_TRADE=0.01          # 1% default (Kelly fallback)
MAX_DRAWDOWN_HALT_PCT=0.08       # 8% drawdown halts trading
VOLATILITY_ATR_MULTIPLIER=3.0    # ATR > 3x median = cut risk 50%
MIN_ADV_RATIO=5                  # Shares must be < ADV/5
KELLY_SAFETY_MULTIPLIER=0.5      # Half-Kelly
MAX_RISK_OF_RUIN_PCT=0.01        # Block if RoR > 1%

# Exit Management
EXIT_CHECK_INTERVAL_MINUTES=5
TRAILING_STOP_ACTIVATION_PCT=2.0
TRAILING_STOP_DISTANCE_PCT=1.5
PENNY_TRAILING_STOP_DISTANCE_PCT=3.0
SCALE_OUT_ENABLED=true
SCALE_OUT_LEVELS=1.0,2.0         # R-multiples
TIME_STOP_DAYS=15

# Edge Validation
MIN_EDGES_REQUIRED=2             # 2 of 3 edges must fire

# Smart Orders
PENNY_LIMIT_SLIPPAGE_PCT=0.5
MAX_SLIPPAGE_PCT=0.3

# Market Awareness
CIRCUIT_BREAKER_SPY_DROP_PCT=-2.0
EARNINGS_EXIT_DAYS=2
EARNINGS_EXIT_MODE=close          # or "tighten"
</pre>

<h2>10. Quick Start</h2>

<pre>
git clone https://github.com/RebelHawk-TK/DeepThinkTrader.git
cd DeepThinkTrader
cp .env.template .env        # Fill in your API keys
pip install -r requirements.txt
python main.py once           # Test single cycle
python main.py scan           # Test scanner
python main.py penny scan    # Test penny scanner
python main.py ticker NVDA   # Test single ticker with edge validation
streamlit run dashboard.py    # Launch dashboard
./run.sh                      # Start bot + dashboard
./stop.sh                     # Stop everything
</pre>

<h2>11. Project Structure</h2>
<pre>
StockTrader/
├── main.py                    # Orchestrator (scheduled loop + 5-min exit checks)
├── config.py                  # Environment config (3 modes + 20 risk params)
├── dashboard.py               # Streamlit monitoring + strategy health
├── run.sh / stop.sh / status.sh  # Control scripts
├── agents/
│   ├── deepthink_agent.py     # Rule-based analysis + multi-edge validation
│   ├── execution_agent.py     # Alpaca trades + trailing stops + scale-out
│   ├── research_agent.py      # Multi-source data gathering
│   └── scanner_agent.py       # 3-stage discovery (main + penny)
├── utils/
│   ├── alpaca_data.py         # Alpaca market data + X-Request-ID
│   ├── database.py            # SQLite (trades, trailing stops, partial exits)
│   ├── risk_manager.py        # Kelly sizing + 13 pre-trade checks
│   ├── twelve_data.py         # MACD, Bollinger, EMA, Stochastic, ADX, ATR
│   └── yahoo_fundamentals.py  # Fundamentals, earnings calendar, edge scoring
├── .env.template              # API key template
├── requirements.txt           # Python dependencies
└── docs/                      # Documentation + PDF guides
</pre>

<div class="footer">
<p><strong>DeepThinkTrader v2.0</strong> &mdash; Risk-First Framework &mdash; Paper Trading Mode Only &mdash; github.com/RebelHawk-TK/DeepThinkTrader</p>
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
