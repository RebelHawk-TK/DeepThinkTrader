"""Generate PDF setup guide for DeepThinkTrader v3.0 API keys and trading parameters."""

from datetime import datetime


def generate_html() -> str:
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body {{ font-family: 'Helvetica Neue', Arial, sans-serif; margin: 40px; color: #1a1a1a; line-height: 1.6; }}
    h1 {{ color: #0d47a1; border-bottom: 3px solid #0d47a1; padding-bottom: 10px; }}
    h2 {{ color: #1565c0; margin-top: 30px; border-bottom: 1px solid #e0e0e0; padding-bottom: 5px; }}
    h3 {{ color: #1976d2; }}
    .warning {{ background: #fff3e0; border-left: 4px solid #ff9800; padding: 15px; margin: 20px 0; border-radius: 4px; }}
    .info {{ background: #e3f2fd; border-left: 4px solid #2196f3; padding: 15px; margin: 20px 0; border-radius: 4px; }}
    .danger {{ background: #fce4ec; border-left: 4px solid #f44336; padding: 15px; margin: 20px 0; border-radius: 4px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 15px 0; font-size: 13px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
    th {{ background: #1565c0; color: white; }}
    tr:nth-child(even) {{ background: #f5f5f5; }}
    code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
    pre {{ background: #263238; color: #aed581; padding: 15px; border-radius: 6px; overflow-x: auto; font-size: 12px; }}
    .step {{ background: #f5f5f5; padding: 15px; margin: 10px 0; border-radius: 6px; border-left: 3px solid #1565c0; }}
    .footer {{ margin-top: 40px; padding-top: 15px; border-top: 1px solid #ddd; color: #666; font-size: 0.9em; }}
    .page-break {{ page-break-before: always; }}
</style>
</head>
<body>

<h1>DeepThinkTrader v3.0 Setup Guide</h1>
<p><strong>Version:</strong> 3.0 (Execution Intelligence) &nbsp;|&nbsp; <strong>Generated:</strong> {datetime.now().strftime('%B %d, %Y')}</p>

<div class="danger">
<strong>CRITICAL WARNING:</strong> Start with paper trading ONLY. Never use real money until you have backtested for 3+ months.
Trading bots can lose 100% of capital. This project is educational and experimental.
</div>

<h2>1. Required API Keys</h2>

<p>You need three free API accounts. All keys go in the <code>.env</code> file (never commit this file).</p>

<h3>1.1 Alpaca Markets (Paper Trading)</h3>
<div class="step">
<ol>
<li>Go to <strong>alpaca.markets</strong> and create a free account</li>
<li>Navigate to <strong>Paper Trading</strong> dashboard</li>
<li>Click <strong>API Keys</strong> &rarr; <strong>Generate New Key</strong></li>
<li>Copy both the <strong>API Key ID</strong> and <strong>Secret Key</strong> (secret shown only once!)</li>
</ol>
</div>

<table>
<tr><th>Variable</th><th>Description</th><th>Example</th></tr>
<tr><td><code>ALPACA_API_KEY</code></td><td>Your Alpaca API Key ID</td><td><code>PK...</code> (20 chars)</td></tr>
<tr><td><code>ALPACA_SECRET_KEY</code></td><td>Your Alpaca Secret Key</td><td><code>abc123...</code> (40 chars)</td></tr>
<tr><td><code>ALPACA_BASE_URL</code></td><td>Paper trading endpoint</td><td><code>https://paper-api.alpaca.markets</code></td></tr>
</table>

<h3>1.2 NewsAPI</h3>
<div class="step">
<ol>
<li>Go to <strong>newsapi.org</strong> and register for free</li>
<li>Copy your API key from the dashboard</li>
<li>Free tier: 500 requests/day (sufficient for hourly research on 5 tickers)</li>
</ol>
</div>

<h3>1.3 Reddit API (PRAW) — Optional</h3>
<div class="step">
<ol>
<li>Log into Reddit, go to <strong>reddit.com/prefs/apps</strong></li>
<li>Click <strong>"create another app..."</strong> at the bottom</li>
<li>Select <strong>"script"</strong> type, name: <code>DeepThinkTrader</code>, redirect: <code>http://localhost:8080</code></li>
<li>Note the <strong>client ID</strong> (under the app name) and <strong>secret</strong></li>
</ol>
</div>

<h3>1.4 RapidAPI (Twelve Data) — Optional</h3>
<div class="step">
<ol>
<li>Go to <strong>rapidapi.com</strong> and create a free account</li>
<li>Subscribe to <strong>Twelve Data</strong> API (free tier: 800 req/day)</li>
<li>Copy your RapidAPI key</li>
</ol>
</div>

<div class="page-break"></div>

<h2>2. Trading Parameters</h2>

<h3>2.1 Trade Modes</h3>
<p>Set <code>TRADE_MODE=safe|normal|aggressive</code> in <code>.env</code> or switch via dashboard.</p>

<table>
<tr><th>Parameter</th><th>Safe</th><th>Normal</th><th>Aggressive</th></tr>
<tr><td>Max Risk/Trade</td><td>1%</td><td>2%</td><td>3%</td></tr>
<tr><td>Daily Loss Limit</td><td>3%</td><td>5%</td><td>8%</td></tr>
<tr><td>Min Conviction</td><td>9.0</td><td>7.5</td><td>6.0</td></tr>
<tr><td>Min R:R Ratio</td><td>3:1</td><td>2:1</td><td>1.5:1</td></tr>
<tr><td>Max Position %</td><td>5%</td><td>10%</td><td>15%</td></tr>
<tr><td>Max Positions</td><td>5</td><td>10</td><td>15</td></tr>
</table>

<h3>2.2 Risk-First Parameters</h3>
<table>
<tr><th>Parameter</th><th>Variable</th><th>Default</th><th>Description</th></tr>
<tr><td>Kelly Safety</td><td><code>KELLY_SAFETY_MULTIPLIER</code></td><td>0.5</td><td>Half-Kelly for conservative sizing</td></tr>
<tr><td>Drawdown Halt</td><td><code>MAX_DRAWDOWN_HALT_PCT</code></td><td>0.08 (8%)</td><td>Block all entries if drawdown exceeds this</td></tr>
<tr><td>Volatility Mult</td><td><code>VOLATILITY_ATR_MULTIPLIER</code></td><td>3.0</td><td>Cut risk 50% if ATR > 3x median (real 30-day)</td></tr>
<tr><td>Min ADV Ratio</td><td><code>MIN_ADV_RATIO</code></td><td>5</td><td>Shares must be &lt; ADV/5</td></tr>
<tr><td>Max Risk of Ruin</td><td><code>MAX_RISK_OF_RUIN_PCT</code></td><td>0.01 (1%)</td><td>Block if RoR exceeds 1%</td></tr>
<tr><td>Min Edges</td><td><code>MIN_EDGES_REQUIRED</code></td><td>2</td><td>Require 2/3 edges (Fund+Tech+Sent)</td></tr>
<tr><td>SPY Circuit Breaker</td><td><code>CIRCUIT_BREAKER_SPY_DROP_PCT</code></td><td>-2.0</td><td>Block longs if SPY down > 2%</td></tr>
<tr><td>VIX Circuit Breaker</td><td><code>CIRCUIT_BREAKER_VIX_THRESHOLD</code></td><td>30</td><td>Block ALL entries when VIX &ge; 30</td></tr>
<tr><td>Earnings Exit</td><td><code>EARNINGS_EXIT_DAYS</code></td><td>2</td><td>Auto-close within 2 days / 12 hours of earnings</td></tr>
</table>

<h3>2.3 Execution Quality Parameters (v3.0)</h3>
<table>
<tr><th>Parameter</th><th>Variable</th><th>Default</th><th>Description</th></tr>
<tr><td>Max Spread</td><td><code>MAX_SPREAD_PCT</code></td><td>1.0%</td><td>Block market orders with wide spreads</td></tr>
<tr><td>Penny Max Spread</td><td><code>PENNY_MAX_SPREAD_PCT</code></td><td>2.0%</td><td>Higher spread tolerance for penny stocks</td></tr>
<tr><td>Sector Limit</td><td><code>MAX_SECTOR_EXPOSURE_PCT</code></td><td>25%</td><td>Max portfolio % per GICS sector</td></tr>
<tr><td>Gap Risk ATR</td><td><code>GAP_RISK_ATR_THRESHOLD</code></td><td>5.0%</td><td>ATR% triggering gap risk reduction</td></tr>
<tr><td>Gap Reduction</td><td><code>GAP_RISK_POSITION_REDUCTION</code></td><td>50%</td><td>Position size multiplier for high gap risk</td></tr>
<tr><td>Obsidian Vault</td><td><code>OBSIDIAN_VAULT_PATH</code></td><td>~/Documents/RHVault/RHVault</td><td>Path to Obsidian vault for SA emails</td></tr>
</table>

<h3>2.3 Exit Management Parameters</h3>
<table>
<tr><th>Parameter</th><th>Variable</th><th>Default</th><th>Description</th></tr>
<tr><td>Exit Check Interval</td><td><code>EXIT_CHECK_INTERVAL_MINUTES</code></td><td>5</td><td>Fast price checks every 5 min</td></tr>
<tr><td>Trail Activation</td><td><code>TRAILING_STOP_ACTIVATION_PCT</code></td><td>2.0%</td><td>Switch to trailing stop at 2% profit</td></tr>
<tr><td>Trail Distance (Main)</td><td><code>TRAILING_STOP_DISTANCE_PCT</code></td><td>1.5%</td><td>Trail distance for main portfolio</td></tr>
<tr><td>Trail Distance (Penny)</td><td><code>PENNY_TRAILING_STOP_DISTANCE_PCT</code></td><td>3.0%</td><td>Wider trail for volatile penny stocks</td></tr>
<tr><td>Scale-Out</td><td><code>SCALE_OUT_ENABLED</code></td><td>true</td><td>Sell 33% at 1R, 33% at 2R</td></tr>
<tr><td>Time Stop</td><td><code>TIME_STOP_DAYS</code></td><td>15</td><td>Auto-exit stale positions after 15 days</td></tr>
<tr><td>Penny Limit Slip</td><td><code>PENNY_LIMIT_SLIPPAGE_PCT</code></td><td>0.5%</td><td>Limit order buffer for penny stocks</td></tr>
</table>

<div class="page-break"></div>

<h2>3. Risk Management (16 Pre-Trade Checks)</h2>

<div class="info">
These safety checks run BEFORE every trade and cannot be overridden via configuration.
</div>

<table>
<tr><th>#</th><th>Check</th><th>Action if Failed</th></tr>
<tr><td>0</td><td>Warmup complete (200+ unique tickers analyzed)</td><td>BLOCKED until warmup done</td></tr>
<tr><td>1</td><td>Conviction meets threshold</td><td>HOLD</td></tr>
<tr><td>2</td><td>Risk within limit</td><td>BLOCKED</td></tr>
<tr><td>3</td><td>Reward:Risk ratio acceptable</td><td>BLOCKED</td></tr>
<tr><td>4</td><td>Daily loss limit OK</td><td>BLOCKED for rest of day</td></tr>
<tr><td>5</td><td>Open position count OK</td><td>BLOCKED</td></tr>
<tr><td>6</td><td>No duplicate position</td><td>BLOCKED</td></tr>
<tr><td>7</td><td>Market hours (9:30-4:00 ET)</td><td>BLOCKED</td></tr>
<tr><td>8</td><td>Drawdown from peak &lt; 8%</td><td>BLOCKED (all new entries)</td></tr>
<tr><td>9</td><td>Risk of ruin &lt; 1%</td><td>BLOCKED</td></tr>
<tr><td>10</td><td>Liquidity: shares &lt; ADV/5</td><td>Auto-reduce or BLOCKED</td></tr>
<tr><td>11</td><td>Multi-edge: 2/3 edges firing</td><td>HOLD</td></tr>
<tr><td>12</td><td>Market health: SPY &gt; 2% OR VIX &ge; 30</td><td>BLOCKED (SPY=longs, VIX=all)</td></tr>
<tr><td>13</td><td>No earnings within 2 days / 12 hours</td><td>Auto-close or BLOCKED</td></tr>
<tr><td>14</td><td>Bid-ask spread acceptable</td><td>BLOCKED</td></tr>
<tr><td>15</td><td>Sector concentration &lt; 25%</td><td>BLOCKED</td></tr>
</table>

<h2>4. Quick Setup Checklist</h2>

<table>
<tr><th>#</th><th>Step</th><th>Done?</th></tr>
<tr><td>1</td><td>Create Alpaca paper account and get API keys</td><td>&square;</td></tr>
<tr><td>2</td><td>Get NewsAPI key (free tier)</td><td>&square;</td></tr>
<tr><td>3</td><td>Create Reddit app and get PRAW credentials (optional)</td><td>&square;</td></tr>
<tr><td>4</td><td>Get RapidAPI key for Twelve Data (optional)</td><td>&square;</td></tr>
<tr><td>5</td><td>Copy <code>.env.template</code> to <code>.env</code> and fill in keys</td><td>&square;</td></tr>
<tr><td>6</td><td>Create Python venv and install requirements</td><td>&square;</td></tr>
<tr><td>7</td><td>Run <code>python main.py once</code> to test single cycle</td><td>&square;</td></tr>
<tr><td>8</td><td>Run <code>python main.py ticker NVDA</code> to test edge validation</td><td>&square;</td></tr>
<tr><td>9</td><td>Run <code>streamlit run dashboard.py</code> to verify dashboard</td><td>&square;</td></tr>
<tr><td>10</td><td>Start scheduled loop: <code>python main.py</code></td><td>&square;</td></tr>
</table>

<h2>5. .env File Template</h2>

<pre>
# Trade Mode: safe, normal, aggressive
TRADE_MODE=normal

# Alpaca API (Paper Trading)
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# NewsAPI
NEWSAPI_KEY=your_newsapi_key

# RapidAPI (Twelve Data — optional)
RAPIDAPI_KEY=your_rapidapi_key

# Reddit PRAW (optional)
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
REDDIT_USER_AGENT=DeepThinkTrader/1.0

# Penny Portfolio
PENNY_ENABLED=true

# Override defaults (optional)
# EXIT_CHECK_INTERVAL_MINUTES=5
# TRAILING_STOP_ACTIVATION_PCT=2.0
# MIN_EDGES_REQUIRED=2
# CIRCUIT_BREAKER_SPY_DROP_PCT=-2.0
# EARNINGS_EXIT_DAYS=2
</pre>

<div class="footer">
<p><strong>DeepThinkTrader v3.0</strong> &mdash; Execution Intelligence &mdash; Paper Trading Mode Only</p>
<p>Generated {datetime.now().strftime('%B %d, %Y')} | For educational/experimental use only</p>
</div>

</body>
</html>"""


if __name__ == "__main__":
    import subprocess
    import tempfile
    import os

    html_content = generate_html()
    html_path = os.path.join(tempfile.gettempdir(), "setup_guide.html")
    pdf_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docs", "DeepThinkTrader-Setup-Guide.pdf")

    with open(html_path, "w") as f:
        f.write(html_content)

    # Try Chrome headless first (most reliable)
    try:
        subprocess.run([
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "--headless", "--disable-gpu", "--no-sandbox",
            f"--print-to-pdf={os.path.abspath(pdf_path)}",
            f"file://{html_path}"
        ], check=True, capture_output=True)
        print(f"PDF generated: {pdf_path}")
    except (FileNotFoundError, subprocess.CalledProcessError):
        # Fallback: save as HTML
        final_html = pdf_path.replace(".pdf", ".html")
        with open(final_html, "w") as f:
            f.write(html_content)
        print(f"Chrome not found. HTML saved: {final_html}")
