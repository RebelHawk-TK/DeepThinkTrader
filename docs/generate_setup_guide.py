"""Generate PDF setup guide for DeepThinkTrader API keys and trading parameters."""

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
    table {{ border-collapse: collapse; width: 100%; margin: 15px 0; }}
    th, td {{ border: 1px solid #ddd; padding: 10px 15px; text-align: left; }}
    th {{ background: #1565c0; color: white; }}
    tr:nth-child(even) {{ background: #f5f5f5; }}
    code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
    pre {{ background: #263238; color: #aed581; padding: 15px; border-radius: 6px; overflow-x: auto; }}
    .step {{ background: #f5f5f5; padding: 15px; margin: 10px 0; border-radius: 6px; border-left: 3px solid #1565c0; }}
    .field {{ margin: 5px 0; }}
    .field label {{ font-weight: bold; display: inline-block; width: 200px; }}
    .field input {{ border: 1px solid #ccc; padding: 5px 10px; width: 300px; border-radius: 3px; }}
    .footer {{ margin-top: 40px; padding-top: 15px; border-top: 1px solid #ddd; color: #666; font-size: 0.9em; }}
    .page-break {{ page-break-before: always; }}
</style>
</head>
<body>

<h1>DeepThinkTrader Setup Guide</h1>
<p><strong>Version:</strong> 1.0 &nbsp;|&nbsp; <strong>Generated:</strong> {datetime.now().strftime('%B %d, %Y')}</p>

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

<table>
<tr><th>Variable</th><th>Description</th><th>Example</th></tr>
<tr><td><code>NEWSAPI_KEY</code></td><td>Your NewsAPI key</td><td><code>abc123def456...</code> (32 chars)</td></tr>
</table>

<h3>1.3 Reddit API (PRAW)</h3>
<div class="step">
<ol>
<li>Log into Reddit, go to <strong>reddit.com/prefs/apps</strong></li>
<li>Click <strong>"create another app..."</strong> at the bottom</li>
<li>Select <strong>"script"</strong> type</li>
<li>Name: <code>DeepThinkTrader</code></li>
<li>Redirect URI: <code>http://localhost:8080</code></li>
<li>Click <strong>Create app</strong></li>
<li>Note the <strong>client ID</strong> (under the app name) and <strong>secret</strong></li>
</ol>
</div>

<table>
<tr><th>Variable</th><th>Description</th><th>Example</th></tr>
<tr><td><code>REDDIT_CLIENT_ID</code></td><td>App client ID (under app name)</td><td><code>aBcDeFgHiJkLmN</code> (14 chars)</td></tr>
<tr><td><code>REDDIT_CLIENT_SECRET</code></td><td>App secret</td><td><code>xYzAbCdEfGhIjKlMnOpQrStUvWx</code> (27 chars)</td></tr>
<tr><td><code>REDDIT_USER_AGENT</code></td><td>Identifies your app to Reddit</td><td><code>DeepThinkTrader/1.0</code></td></tr>
</table>

<div class="page-break"></div>

<h2>2. Trading Parameters</h2>

<p>All configurable via <code>.env</code> file. Defaults are conservative for paper trading.</p>

<table>
<tr><th>Parameter</th><th>Variable</th><th>Default</th><th>Description</th><th>Recommended Range</th></tr>
<tr><td>Account Size</td><td><code>ACCOUNT_SIZE</code></td><td>$50,000</td><td>Starting paper balance</td><td>$10K - $100K</td></tr>
<tr><td>Watchlist</td><td><code>WATCHLIST</code></td><td>NVDA,TSLA,AAPL,AMD,SPY</td><td>Comma-separated tickers</td><td>3-10 tickers</td></tr>
<tr><td>Max Risk/Trade</td><td><code>MAX_RISK_PER_TRADE</code></td><td>0.02 (2%)</td><td>Max % of account risked per position</td><td>0.01 - 0.03</td></tr>
<tr><td>Max Daily Loss</td><td><code>MAX_DAILY_LOSS</code></td><td>0.05 (5%)</td><td>Hard stop — no more trades today</td><td>0.03 - 0.06</td></tr>
<tr><td>Min Conviction</td><td><code>MIN_CONVICTION</code></td><td>8</td><td>Score threshold to execute (1-10)</td><td>7 - 9</td></tr>
<tr><td>Research Interval</td><td><code>RESEARCH_INTERVAL_MINUTES</code></td><td>60</td><td>Minutes between research cycles</td><td>30 - 120</td></tr>
<tr><td>Min R:R Ratio</td><td><code>MIN_REWARD_RISK_RATIO</code></td><td>2.0</td><td>Take-profit must be 2x stop-loss</td><td>1.5 - 3.0</td></tr>
</table>

<h2>3. Risk Management Rules (Hardcoded)</h2>

<div class="info">
These safety checks run BEFORE every trade and cannot be overridden via configuration.
</div>

<table>
<tr><th>Rule</th><th>Description</th><th>Action if Triggered</th></tr>
<tr><td>Conviction Gate</td><td>Analysis conviction must be &ge; MIN_CONVICTION</td><td>HOLD — no trade</td></tr>
<tr><td>Position Risk Cap</td><td>Max loss per position &le; MAX_RISK_PER_TRADE</td><td>BLOCKED</td></tr>
<tr><td>R:R Minimum</td><td>Take-profit &ge; MIN_REWARD_RISK_RATIO &times; stop-loss</td><td>BLOCKED</td></tr>
<tr><td>Daily Loss Limit</td><td>Realized P&amp;L today must be within MAX_DAILY_LOSS</td><td>BLOCKED for rest of day</td></tr>
<tr><td>Max Open Positions</td><td>No more than 5 simultaneous positions</td><td>BLOCKED</td></tr>
<tr><td>No Duplicates</td><td>Cannot open second position in same ticker</td><td>BLOCKED</td></tr>
<tr><td>Market Hours</td><td>Must be within US market hours (9:30-4:00 ET)</td><td>BLOCKED</td></tr>
<tr><td>Revenge Trading</td><td>3+ consecutive losses triggers cooldown</td><td>BLOCKED + warning</td></tr>
</table>

<h2>4. Quick Setup Checklist</h2>

<table>
<tr><th>#</th><th>Step</th><th>Done?</th></tr>
<tr><td>1</td><td>Create Alpaca paper account and get API keys</td><td>☐</td></tr>
<tr><td>2</td><td>Get NewsAPI key (free tier)</td><td>☐</td></tr>
<tr><td>3</td><td>Create Reddit app and get PRAW credentials</td><td>☐</td></tr>
<tr><td>4</td><td>Copy <code>.env.template</code> to <code>.env</code> and fill in keys</td><td>☐</td></tr>
<tr><td>5</td><td>Create Python venv and install requirements</td><td>☐</td></tr>
<tr><td>6</td><td>Run <code>python main.py once</code> to test single cycle</td><td>☐</td></tr>
<tr><td>7</td><td>Run <code>streamlit run dashboard.py</code> to verify dashboard</td><td>☐</td></tr>
<tr><td>8</td><td>Start scheduled loop: <code>python main.py</code></td><td>☐</td></tr>
</table>

<h2>5. .env File Template</h2>

<pre>
# Alpaca API (Paper Trading)
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# NewsAPI
NEWSAPI_KEY=your_newsapi_key

# Reddit (PRAW)
REDDIT_CLIENT_ID=your_reddit_client_id
REDDIT_CLIENT_SECRET=your_reddit_client_secret
REDDIT_USER_AGENT=DeepThinkTrader/1.0

# Trading Parameters
ACCOUNT_SIZE=50000
WATCHLIST=NVDA,TSLA,AAPL,AMD,SPY
MAX_RISK_PER_TRADE=0.02
MAX_DAILY_LOSS=0.05
MIN_CONVICTION=8
RESEARCH_INTERVAL_MINUTES=60
MIN_REWARD_RISK_RATIO=2.0
</pre>

<div class="footer">
<p><strong>DeepThinkTrader v1.0</strong> &mdash; Paper Trading Mode Only</p>
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

    # Try wkhtmltopdf first, fall back to weasyprint, then cupsfilter
    converters = [
        ["wkhtmltopdf", "--enable-local-file-access", html_path, pdf_path],
        ["cupsfilter", html_path],
    ]

    converted = False
    for cmd in converters:
        try:
            if "cupsfilter" in cmd[0]:
                with open(pdf_path, "wb") as out:
                    subprocess.run(cmd, stdout=out, stderr=subprocess.DEVNULL, check=True)
            else:
                subprocess.run(cmd, check=True, capture_output=True)
            converted = True
            print(f"PDF generated: {pdf_path}")
            break
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue

    if not converted:
        # Fallback: try weasyprint Python package
        try:
            from weasyprint import HTML
            HTML(string=html_content).write_pdf(pdf_path)
            print(f"PDF generated (weasyprint): {pdf_path}")
        except ImportError:
            # Last resort: save as HTML
            final_html = pdf_path.replace(".pdf", ".html")
            with open(final_html, "w") as f:
                f.write(html_content)
            print(f"PDF tools not found. HTML saved: {final_html}")
            print("Install wkhtmltopdf (brew install wkhtmltopdf) or weasyprint (pip install weasyprint) for PDF.")
