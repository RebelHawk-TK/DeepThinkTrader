"""Generate the branded DeepThinkTrader overview PDF.

Output: docs/DeepThinkTrader-Overview.pdf
Engine: HTML + Chrome headless --print-to-pdf.

Layout philosophy: let content drive page count. The cover is the only
element with a fixed page footprint. Section headers use page-break-before:
always so each section starts on a fresh page; everything else flows.
"""

from __future__ import annotations

import base64
import os
import subprocess
import sys
import tempfile
from datetime import datetime

_DOCS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_DOCS_DIR)
_BRAND_DIR = os.path.join(_REPO, "static", "brand")


def _b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def generate_html() -> str:
    banner_b64 = _b64(os.path.join(_BRAND_DIR, "banner.png"))
    mark_b64 = _b64(os.path.join(_BRAND_DIR, "mark-tile-192.png"))
    today = datetime.now().strftime("%B %d, %Y")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>DeepThinkTrader — Overview</title>
<style>
  /* Letter, no browser-injected margins; we control padding ourselves. */
  @page {{ margin: 0; size: letter; }}

  :root {{
    --bg: #0a1628;
    --bg-card: #15294d;
    --bg-elevated: #1a2f56;
    --ink: #e8eef9;
    --ink-soft: #a8b5cc;
    --ink-mute: #6b7a99;
    --teal: #2dd4bf;
    --gold: #f59e0b;
    --red: #ef4444;
    --rule: rgba(255,255,255,0.08);
  }}

  * {{ box-sizing: border-box; }}

  html, body {{
    margin: 0;
    padding: 0;
    background: var(--bg);
    color: var(--ink);
    font-family: 'Helvetica Neue', 'Inter', -apple-system, sans-serif;
    font-size: 10.5pt;
    line-height: 1.5;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}

  /* ─── Cover ─── */
  .cover {{
    width: 8.5in;
    height: 11in;
    padding: 0.85in 0.75in 0.7in;
    background:
      radial-gradient(ellipse at 80% 0%, rgba(45,212,191,0.18) 0%, transparent 55%),
      radial-gradient(ellipse at 0% 100%, rgba(245,158,11,0.10) 0%, transparent 50%),
      linear-gradient(180deg, #050d1c 0%, #0a1628 100%);
    page-break-after: always;
    display: flex;
    flex-direction: column;
  }}
  .cover .banner {{
    width: 100%;
    max-height: 3.4in;
    object-fit: contain;
    border-radius: 12px;
    box-shadow: 0 6px 30px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.06);
  }}
  .cover .title-block {{
    margin-top: auto;          /* push title group to vertical mid-bottom */
    padding-bottom: 0.4in;
  }}
  .cover h1 {{
    font-size: 44pt;
    font-weight: 200;
    letter-spacing: -0.02em;
    margin: 0 0 0.14in;
    line-height: 1.05;
  }}
  .cover h1 .accent {{ color: var(--teal); font-weight: 400; }}
  .cover .tagline {{
    font-size: 14pt;
    color: var(--ink-soft);
    font-weight: 300;
    margin: 0;
    max-width: 5.8in;
    line-height: 1.4;
  }}
  .cover .meta {{
    margin-top: auto;          /* anchor to bottom */
    color: var(--ink-mute);
    font-size: 9pt;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    border-top: 1px solid var(--rule);
    padding-top: 0.18in;
    display: flex;
    justify-content: space-between;
  }}

  /* ─── Section pages ─── */
  .section {{
    padding: 0.45in 0.6in 0.35in;
    page-break-before: always;
  }}
  .section:first-of-type {{ page-break-before: always; }} /* still after cover */

  .section-head {{
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 0.25in;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--rule);
  }}
  .section-head img {{
    width: 36px; height: 36px;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.4);
  }}
  .section-head .num {{
    color: var(--teal);
    font-size: 8.5pt;
    font-weight: 600;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    margin-bottom: 2px;
  }}
  .section-head h2 {{
    margin: 0;
    font-size: 22pt;
    font-weight: 300;
    letter-spacing: -0.01em;
  }}

  h3 {{
    color: var(--teal);
    font-size: 11pt;
    font-weight: 600;
    margin: 18px 0 8px;
    letter-spacing: 0.02em;
  }}

  p {{ margin: 0 0 9px; color: var(--ink-soft); }}
  strong {{ color: var(--ink); font-weight: 600; }}

  /* ─── Pipeline (4 cards in 1 row, no arrows) ─── */
  .pipeline {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin: 6px 0 14px;
    page-break-inside: avoid;
  }}
  .pipeline .stage {{
    background: var(--bg-card);
    border: 1px solid var(--rule);
    border-radius: 10px;
    padding: 12px 12px 12px 14px;
    border-left: 3px solid var(--teal);
  }}
  .pipeline .stage .num {{
    color: var(--teal);
    font-size: 10pt;
    font-weight: 700;
    letter-spacing: 0.05em;
    margin-bottom: 1px;
  }}
  .pipeline .stage .name {{
    color: var(--ink);
    font-size: 11pt;
    font-weight: 600;
    margin-bottom: 6px;
  }}
  .pipeline .stage .body {{
    color: var(--ink-soft);
    font-size: 9pt;
    line-height: 1.45;
  }}

  /* ─── Stat row ─── */
  .stat-row {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
    margin: 4px 0 16px;
    page-break-inside: avoid;
  }}
  .stat {{
    background: linear-gradient(180deg, var(--bg-card) 0%, var(--bg-elevated) 100%);
    border: 1px solid var(--rule);
    border-radius: 8px;
    padding: 10px 8px;
    text-align: center;
  }}
  .stat .value {{
    font-size: 18pt;
    font-weight: 200;
    color: var(--teal);
    line-height: 1.1;
    letter-spacing: -0.02em;
  }}
  .stat .label {{
    font-size: 8pt;
    color: var(--ink-mute);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-top: 4px;
  }}

  /* ─── Card grid (2 or 3 wide) ─── */
  .grid-2, .grid-3 {{
    display: grid;
    gap: 10px;
    margin: 6px 0 14px;
    page-break-inside: avoid;
  }}
  .grid-2 {{ grid-template-columns: 1fr 1fr; }}
  .grid-3 {{ grid-template-columns: 1fr 1fr 1fr; }}

  .card {{
    background: var(--bg-card);
    border: 1px solid var(--rule);
    border-radius: 10px;
    padding: 12px 14px;
    page-break-inside: avoid;
  }}
  .card h4 {{
    margin: 0 0 6px;
    color: var(--ink);
    font-size: 10.5pt;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .card h4 .dot {{
    width: 7px; height: 7px;
    border-radius: 50%;
    background: var(--teal);
    box-shadow: 0 0 8px var(--teal);
    flex-shrink: 0;
  }}
  .card p {{ font-size: 9.5pt; margin: 0; }}
  .card .tags {{ margin-top: 6px; }}

  /* ─── Numbered steps (single consistent style) ─── */
  ol.steps {{
    list-style: none;
    counter-reset: step;
    padding: 0;
    margin: 4px 0 14px;
  }}
  ol.steps li {{
    counter-increment: step;
    position: relative;
    padding: 7px 0 7px 36px;
    border-bottom: 1px solid var(--rule);
    page-break-inside: avoid;
  }}
  ol.steps li:last-child {{ border-bottom: none; }}
  ol.steps li::before {{
    content: counter(step);
    position: absolute;
    left: 0;
    top: 9px;
    width: 24px; height: 24px;
    border-radius: 50%;
    background: var(--teal);
    color: var(--bg);
    text-align: center;
    line-height: 24px;
    font-weight: 700;
    font-size: 10pt;
  }}
  ol.steps li strong {{ display: block; margin-bottom: 2px; color: var(--ink); }}
  ol.steps li span {{ color: var(--ink-soft); font-size: 9.5pt; }}

  /* ─── Disclaimer ─── */
  .disclaimer {{
    background: rgba(239,68,68,0.08);
    border: 1px solid rgba(239,68,68,0.35);
    border-left: 3px solid var(--red);
    border-radius: 8px;
    padding: 12px 14px;
    margin-top: 16px;
    page-break-inside: avoid;
  }}
  .disclaimer h4 {{
    color: var(--red);
    margin: 0 0 4px;
    font-size: 9.5pt;
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }}
  .disclaimer p {{ font-size: 9pt; color: var(--ink-soft); margin: 0; }}

  .footer {{
    margin-top: 22px;
    padding-top: 12px;
    border-top: 1px solid var(--rule);
    color: var(--ink-mute);
    font-size: 8.5pt;
    display: flex;
    justify-content: space-between;
  }}

  /* ─── Tags ─── */
  .tag {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 8pt;
    font-weight: 600;
    letter-spacing: 0.05em;
    margin-right: 4px;
  }}
  .tag.teal {{ background: rgba(45,212,191,0.15); color: var(--teal); }}
  .tag.gold {{ background: rgba(245,158,11,0.15); color: var(--gold); }}
  .tag.green {{ background: rgba(16,185,129,0.18); color: #10b981; }}
</style>
</head>
<body>

<!-- ─── COVER ─── -->
<div class="cover">
  <img src="data:image/png;base64,{banner_b64}" class="banner" alt="DeepThinkTrader">
  <div class="title-block">
    <h1>Deep<span class="accent">Think</span> Trader</h1>
    <p class="tagline">A machine-learning, self-improving paper-trading system that researches, debates, and trades equities with institutional-grade risk discipline.</p>
  </div>
  <div class="meta">
    <span>Overview · Version 3.0</span>
    <span>{today}</span>
  </div>
</div>

<!-- ─── SECTION 1 ─── -->
<div class="section">
  <div class="section-head">
    <img src="data:image/png;base64,{mark_b64}" alt="">
    <div>
      <div class="num">Section 01</div>
      <h2>What DeepThinkTrader does</h2>
    </div>
  </div>

  <p>DeepThinkTrader is a fully autonomous trading system that runs continuously during United States market hours. It scans the equity universe, researches candidate tickers from multiple data sources, weighs each through a language-model debate, and places paper trades through a hardened risk gate.</p>

  <p>It is built around a four-agent pipeline. Each stage is independently testable, observably logged, and can be paused without bringing the system down.</p>

  <h3>The pipeline</h3>
  <div class="pipeline">
    <div class="stage">
      <div class="num">01</div>
      <div class="name">Scanner</div>
      <div class="body">Three-stage funnel from a sixty-plus ticker universe. Momentum-scored, volume-filtered, sector-rotated.</div>
    </div>
    <div class="stage">
      <div class="num">02</div>
      <div class="name">Research</div>
      <div class="body">Aggregates five news data feeds, Reddit, Seeking Alpha emails, fundamentals, and advanced market technicals.</div>
    </div>
    <div class="stage">
      <div class="num">03</div>
      <div class="name">DeepThink</div>
      <div class="body">Multi-edge validation, conviction scoring, and a bull-versus-bear language-model debate powered by Claude.</div>
    </div>
    <div class="stage">
      <div class="num">04</div>
      <div class="name">Execution</div>
      <div class="body">Thirteen pre-trade risk checks, Kelly-calibrated sizing, bracket orders to the Alpaca brokerage with trailing stops.</div>
    </div>
  </div>

  <div class="stat-row">
    <div class="stat"><div class="value">4</div><div class="label">Agents</div></div>
    <div class="stat"><div class="value">5</div><div class="label">News sources</div></div>
    <div class="stat"><div class="value">13</div><div class="label">Risk checks</div></div>
    <div class="stat"><div class="value">15m</div><div class="label">Cycle cadence</div></div>
  </div>

  <h3>Operational properties</h3>
  <div class="grid-2">
    <div class="card">
      <h4><span class="dot"></span>Autonomous by default</h4>
      <p>Boots on system start via the macOS launch agent, runs research cycles every fifteen minutes during market hours, monitors exits every five minutes, refreshes news feeds hourly.</p>
    </div>
    <div class="card">
      <h4><span class="dot"></span>Fail-safe execution</h4>
      <p>Every cycle is wrapped in a watchdog that force-restarts on stalls. Startup reconciles ghost positions and stale limit orders against the broker.</p>
    </div>
    <div class="card">
      <h4><span class="dot"></span>Observable</h4>
      <p>Heartbeat file, structured log files, Streamlit dashboard. Every language-model call, parameter change, and trade decision is recorded.</p>
    </div>
    <div class="card">
      <h4><span class="dot"></span>Safety-first</h4>
      <p>Paper trading only. Strategy auto-pauses if the win rate falls fifteen percent from baseline. A market circuit breaker halts new entries when the S&amp;P 500 index drops two percent in a session.</p>
    </div>
  </div>

  <div class="footer"><span>DeepThinkTrader · Section One</span><span>github.com/RebelHawk-TK/DeepThinkTrader</span></div>
</div>

<!-- ─── SECTION 2 ─── -->
<div class="section">
  <div class="section-head">
    <img src="data:image/png;base64,{mark_b64}" alt="">
    <div>
      <div class="num">Section 02</div>
      <h2>How the bot determines trades</h2>
    </div>
  </div>

  <p>Every trade decision passes through five sequential checkpoints. A trade enters only when each one passes its threshold; if any fails, the bot holds and the ticker is reconsidered next cycle.</p>

  <ol class="steps">
    <li>
      <strong>Multi-edge validation</strong>
      <span>Three independent edges — technical (a basket of momentum, trend, volatility, and directional strength indicators), fundamental (earnings momentum, analyst revisions, valuation), and news sentiment (relevance-weighted across five sources). At least two of the three must align.</span>
    </li>
    <li>
      <strong>Bull / bear debate</strong>
      <span>Two language-model personas argue from the same evidence packet for two rounds. A judge model weighs both and emits a winning side, a conviction score from one to ten, and the single most decisive piece of evidence. The losing side's strongest counter becomes the trade's invalidation condition.</span>
    </li>
    <li>
      <strong>Conviction gate</strong>
      <span>Combined score from rule edges and the language-model debate must exceed the active trade mode's threshold (Aggressive 6.0, Normal 7.5, Safe 9.0). Below threshold, the bot holds.</span>
    </li>
    <li>
      <strong>Risk gate (thirteen checks)</strong>
      <span>Kelly-sized position with safety multiplier. Sector exposure cap. Spread guard. Gap risk. Liquidity floor based on average daily volume. Daily loss limit. Drawdown halt. Earnings proximity. Duplicate prevention. Revenge-trade detection. Market circuit breaker. Multi-edge confirmation. Risk-of-ruin probability.</span>
    </li>
    <li>
      <strong>Execution and exit management</strong>
      <span>Bracket order to the Alpaca brokerage with calculated stop-loss and take-profit. Trailing stop activates at two percent profit, trails at one-and-a-half percent. Partial scale-out at one and two risk-units of profit. Time stop at fifteen days. Automatic exit within two days of earnings.</span>
    </li>
  </ol>

  <h3>What's in every prompt</h3>
  <div class="grid-2">
    <div class="card">
      <h4><span class="dot"></span>Structured evidence packet</h4>
      <p>Price action, technical indicators, options flow, fundamentals, earnings calendar, news sentiment per source, Seeking Alpha mention count, Reddit signal.</p>
    </div>
    <div class="card">
      <h4><span class="dot"></span>Cached for cost</h4>
      <p>System prompts use the Anthropic ephemeral prompt cache. A twenty-five-minute expiry-based cache reuses ticker analyses if the same ticker is revisited mid-cycle.</p>
    </div>
  </div>

  <h3>Transparent reasoning</h3>
  <p>Every executed trade carries a plain-English thesis ("why this trade") and an invalidation condition ("what would prove me wrong"). Both are logged to the trade record and surfaced in the dashboard, so every position can be audited after the fact.</p>

  <div class="footer"><span>DeepThinkTrader · Section Two</span><span>Powered by Claude Haiku · Alpaca paper trading</span></div>
</div>

<!-- ─── SECTION 3 ─── -->
<div class="section">
  <div class="section-head">
    <img src="data:image/png;base64,{mark_b64}" alt="">
    <div>
      <div class="num">Section 03</div>
      <h2>Learning from historical activity</h2>
    </div>
  </div>

  <p>DeepThinkTrader is designed to improve over time without manual retuning. Three feedback loops compound: continuous performance measurement, parameter recommendations grounded in trailing metrics, and a captured dataset of every reasoning step the language model has taken.</p>

  <h3>Three learning loops</h3>
  <div class="grid-3">
    <div class="card">
      <h4><span class="dot"></span>Strategy snapshots</h4>
      <p>A daily structured record captures the active parameter set alongside trailing thirty-day Sharpe ratio, Sortino ratio, win rate, maximum drawdown, and average return-per-unit-of-risk. Builds the time series the bot uses to detect drift.</p>
      <div class="tags"><span class="tag teal">Phase 0</span><span class="tag green">Live</span></div>
    </div>
    <div class="card">
      <h4><span class="dot"></span>Parameter recommender</h4>
      <p>A rule engine reads recent snapshots and proposes parameter changes — raising the Kelly fraction when edge is strong, tightening conviction when win rate slips, widening trailing stops when premature exits are observed.</p>
      <div class="tags"><span class="tag teal">Phase 2</span><span class="tag gold">Thirty-day warm-up</span></div>
    </div>
    <div class="card">
      <h4><span class="dot"></span>Language-model call dataset</h4>
      <p>Every Claude prompt and response is logged to a structured file with token usage, latency, and cache-hit metrics. The accumulated corpus is the training set for a future locally-fine-tuned model.</p>
      <div class="tags"><span class="tag teal">Phase 5 prep</span><span class="tag green">Live</span></div>
    </div>
  </div>

  <h3>Closed-loop adaptation</h3>
  <p>Recommendations surface in a daily digest. A human operator reviews them and applies any that look sound. Once a rule has accumulated a track record, it can be flipped to auto-apply via an environment variable. Each automated change is audited; if post-change performance degrades, the change auto-reverts and the rule pauses for thirty days.</p>

  <h3>Auto-pause and recovery</h3>
  <p>A weekly health check compares the trailing thirty-day win rate to a rolling ninety-day baseline. If the win rate drops more than fifteen percentage points, the bot halts new entries (exit monitoring continues) until reviewed. When performance recovers, the bot auto-resumes. This prevents a degraded strategy from compounding losses.</p>

  <h3>Reflection writer</h3>
  <p>After each closed trade, a structured reflection captures whether the thesis played out, which edges were predictive, and whether the exit reason matched the original invalidation condition. These reflections feed back into the edge-performance tracker that informs future weighting.</p>

  <div class="disclaimer">
    <h4>Important disclaimer · DeepThinkTrader · Generated {today}</h4>
    <p>DeepThinkTrader is experimental software for educational and research purposes. Paper trading only. It is not financial advice. Past performance does not predict future results. Always validate strategies against historical data before risking real capital.</p>
  </div>
</div>

</body>
</html>"""


def main() -> int:
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(chrome):
        print(f"Chrome not found at {chrome}. Cannot generate PDF.", file=sys.stderr)
        return 1

    html = generate_html()
    html_path = os.path.join(tempfile.gettempdir(), "dtt_overview.html")
    pdf_path = os.path.join(_DOCS_DIR, "DeepThinkTrader-Overview.pdf")

    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    result = subprocess.run(
        [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            f"file://{html_path}",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Chrome failed (code {result.returncode}):", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1

    print(f"PDF generated: {pdf_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
