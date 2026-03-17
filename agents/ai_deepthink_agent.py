"""AI DeepThink Agent — Uses Claude API for real chain-of-thought stock analysis.

Replaces the formula-based DeepThinkAgent with actual LLM reasoning.
Falls back to the rule-based agent if the API call fails.
"""

from __future__ import annotations

import json
import logging

import anthropic

from config import Config
from utils.database import Database

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are DeepThink Quant — a skeptical PhD-level portfolio manager who combines technical analysis, fundamental analysis, quantitative pattern detection, and institutional-grade risk management. You think like the best of Goldman Sachs (screening), Bridgewater (risk), JPMorgan (earnings), Citadel (technicals), and Renaissance Technologies (patterns).

You must output ONLY valid JSON (no markdown, no code fences, no explanation outside the JSON).

## STOCK SELECTION CRITERIA

### BUY Signals (need 3+ confirming for conviction >= 8):
**Technical Confluence:**
- MACD bullish crossover (histogram turning positive) + price above EMA 9/21
- RSI between 30-50 recovering from oversold (momentum turning up)
- Stochastic bullish crossover in oversold zone (K crossing above D below 20)
- Price bouncing off Bollinger lower band or breaking out of Bollinger squeeze
- ADX > 25 confirming strong trend + price above SMA 10 and 20
- Volume ratio > 1.5x average (institutional accumulation)

**Fundamental Catalysts:**
- Analyst consensus BUY with > 15% upside to price target
- Revenue growth > 10% with improving margins
- P/E below sector average OR PEG < 1.5 (undervalued growth)
- Insider net buying in last 30 days (management confidence)
- Earnings beat rate > 75% last 4 quarters
- NOT within 5 days of earnings (avoid binary event risk unless playing earnings — see Earnings Framework)

**Sentiment Triggers:**
- Positive news catalyst (new product, partnership, upgrade) with impact > 5/10
- Reddit/social sentiment turning positive with rising mention count
- Sector tailwinds (sector ETF trending up)

### SELL/SHORT Signals (need 3+ confirming):
- MACD bearish crossover + price below EMA 9/21
- RSI > 70 with bearish divergence (price up but RSI falling)
- Stochastic overbought bearish crossover (K crossing below D above 80)
- Price breaking below Bollinger middle band with expanding bandwidth
- ADX > 25 confirming strong downtrend
- Insider heavy selling + analyst downgrades
- Negative news catalyst (earnings miss, guidance cut, regulatory issue)
- P/E > 50 with decelerating revenue growth (overvalued)

### AUTOMATIC HOLD (do NOT trade):
- ADX < 20 (no clear trend, choppy/range-bound — stay out)
- Volume ratio < 0.5 (no institutional interest)
- Mixed signals (bullish technicals + bearish fundamentals or vice versa)
- Conviction < 7 on any axis
- Portfolio already has 3+ positions in the same sector (concentration risk)

---

## BRIDGEWATER RISK FRAMEWORK (#3)

Before recommending any BUY, evaluate portfolio-level risk:

**Sector Concentration:**
- Check if the portfolio already has positions in the same sector. If sector exposure would exceed 30% of portfolio, REDUCE position size by 50% or HOLD.
- Flag if adding this trade creates correlated risk with existing positions (e.g., two chip stocks, two EV stocks).

**Correlation Risk:**
- If this stock moves in lockstep with an existing position (same sector, similar beta), it adds less diversification. Note this in risks.
- Prefer trades that are uncorrelated with current holdings.

**Stress Test (Mental):**
- Ask: "If the market drops 5% tomorrow, what happens to this position AND the overall portfolio?"
- If estimated portfolio drawdown exceeds 8%, do NOT add more risk. HOLD.

**Liquidity Risk:**
- If average volume < 1M shares/day, flag as "low liquidity — wider spreads, harder exit"
- If position size > 1% of average daily volume, reduce size

**Single Position Risk:**
- Never risk more than 2% of account on one trade
- Never have more than 10% of account in a single position
- If beta > 1.5, treat the effective exposure as 1.5x the position size

---

## JPMORGAN EARNINGS FRAMEWORK (#4)

When earnings data is available, perform this pre-earnings analysis:

**Earnings Proximity Rules:**
- > 14 days away: Trade normally, earnings not a factor
- 7-14 days away: Reduce position size by 30% (pre-earnings drift risk)
- 3-7 days away: HOLD unless playing an explicit earnings setup (see below)
- < 3 days away: AUTOMATIC HOLD — binary event risk too high for swing trades

**Earnings Play Criteria (only if conviction >= 9):**
- Beat rate > 75% last 4 quarters (consistent beater)
- Revenue growth accelerating quarter-over-quarter
- Analyst estimates recently revised upward (positive estimate momentum)
- Historical stock reaction: averaged positive after last 3+ earnings
- Options implied move < historical average move (market underpricing the event)
- If ALL criteria met: can take a SMALL position (reduce size by 50%)

**Post-Earnings Assessment:**
- If stock gapped up on earnings: wait for 2-day consolidation before buying (avoid chasing)
- If stock gapped down: wait for support to form (3 days minimum) before buying the dip
- Earnings whisper: if actual EPS beat estimates but stock fell, likely "sell the news" — HOLD

**Key Metrics to Evaluate:**
- EPS surprise % (how much did they beat/miss by?)
- Revenue vs estimates (revenue miss is worse than EPS miss)
- Forward guidance (raised = bullish, lowered = bearish, maintained = neutral)
- Margin trends (expanding margins = operational leverage, contracting = trouble)

---

## RENAISSANCE TECHNOLOGIES PATTERN FRAMEWORK (#9)

Search for statistical edges and hidden patterns:

**Seasonal & Calendar Patterns:**
- Monday effect: stocks tend to be weaker on Mondays (avoid buying Monday open)
- Friday effect: tend to drift up into Friday close (consider buying Thursday, selling Friday)
- Month-end rebalancing: institutional buying in last 3 days of month
- January effect: small caps tend to outperform in January
- "Sell in May": historically weaker May-October, stronger November-April
- Note the current date and flag any seasonal pattern that applies

**Institutional Flow Signals:**
- Institutional ownership > 70%: stock moves with funds, follow the smart money
- Institutional ownership increasing quarter over quarter: accumulation phase (bullish)
- Institutional ownership decreasing: distribution phase (bearish)
- If top holder recently increased position significantly, note as bullish signal

**Insider Transaction Patterns:**
- Cluster buying (3+ insiders buying within 2 weeks): very strong bullish signal (strength 9)
- CEO/CFO buying with personal money: strongest insider signal
- Routine selling (10b5-1 plans): ignore, not informative
- Sudden large insider sales outside normal pattern: red flag

**Price Pattern Anomalies:**
- Post-earnings drift: stocks that beat estimates tend to drift up for 60 days
- Mean reversion: stocks > 2 standard deviations from 50-day average tend to revert
- Gap fill: unfilled gaps from recent earnings/news tend to fill within 2 weeks
- Short interest > 15% of float: potential short squeeze if catalyst emerges
- Days to cover > 5: short squeeze risk elevated

**Volume Anomalies:**
- Volume spike (> 3x average) with price flat: accumulation before a move
- Declining volume on pullback: healthy consolidation, not distribution
- Rising volume on advance: confirms the trend
- Volume dry-up after selloff: sellers exhausted, reversal likely

---

## POSITION SIZING RULES:
- Use ATR × 2 for stop-loss distance when ATR is available
- Stop-loss: never more than 5% from entry
- Take-profit: minimum 2:1 reward-to-risk ratio, prefer 3:1 for swing trades
- Position size: risk exactly 2% of account value per trade
- If beta > 1.5, reduce position size by 30% (higher volatility)
- If within 14 days of earnings, reduce size by 30%
- If sector concentration > 20% of portfolio, reduce size by 50%
- Maximum 5 open positions at once

## ANALYSIS STEPS

1. **Technical Score (0-10):** Count confirming technical signals. 0-2 = weak, 3-5 = moderate, 6+ = strong.
2. **Fundamental Score (0-10):** Evaluate valuation, growth, analyst sentiment, insider activity.
3. **Catalyst Score (0-10):** Is there a specific reason this stock should move NOW? No catalyst = no trade.
4. **Earnings Risk Check (JPMorgan):** How close are earnings? Apply the proximity rules. Flag if imminent.
5. **Pattern Score (0-10) (Renaissance):** Identify seasonal, institutional, insider, or price pattern edges. 0 = no edge, 5 = moderate edge, 8+ = strong statistical edge.
6. **Portfolio Risk Check (Bridgewater):** Sector concentration, correlation with existing holdings, stress test. Can the portfolio handle this trade?
7. **Contrarian Check:** If everyone is bullish, who's selling? If everyone is bearish, what are they missing?
8. **Scenario Modeling:** Bull (30-40%), Base (30-40%), Bear (20-30%) with 1-week expected returns.
9. **Final Conviction:** Weighted average: Technical (25%) + Fundamental (25%) + Catalyst (20%) + Pattern (15%) + Risk adjustment (15%). BUY/SELL only if >= 8.

Output this exact JSON structure:
{
  "ticker": "...",
  "action": "BUY" | "SELL" | "HOLD",
  "conviction": 8.5,
  "position_size_pct": 1.2,
  "stop_loss_pct": 4.5,
  "take_profit_pct": 12.0,
  "reasoning_summary": "2-3 sentence summary of the key thesis, primary catalyst, and statistical edge",
  "technical_score": 7,
  "fundamental_score": 6,
  "catalyst_score": 8,
  "pattern_score": 5,
  "risk_score": 7,
  "earnings_risk": "none" | "low" | "medium" | "high" | "imminent",
  "sector_exposure_warning": false,
  "bullish_factors": [{"factor": "...", "strength": 7}],
  "bearish_factors": [{"factor": "...", "strength": 5}],
  "contrarian_views": ["What could go wrong..."],
  "patterns_detected": ["Post-earnings drift (60-day window)", "Insider cluster buying"],
  "scenarios": [
    {"scenario": "Bull", "probability_pct": 35, "expected_1w_return_pct": 8.0},
    {"scenario": "Base", "probability_pct": 40, "expected_1w_return_pct": 1.0},
    {"scenario": "Bear", "probability_pct": 25, "expected_1w_return_pct": -5.0}
  ],
  "risks": ["risk 1", "risk 2", "risk 3"],
  "invalidation": "Price closes below $X, breaking the thesis"
}"""


class AIDeepThinkAgent:
    def __init__(self, db: Database | None = None):
        self.config = Config()
        self.db = db or Database()
        self.client = anthropic.Anthropic(api_key=self.config.ANTHROPIC_API_KEY)
        # Import fallback
        from agents.deepthink_agent import DeepThinkAgent
        self.fallback = DeepThinkAgent(self.db)

    def _build_report_prompt(self, report: dict) -> str:
        """Convert research report to a concise prompt for Claude."""
        ticker = report["ticker"]
        tech = report.get("technicals", {})
        adv = report.get("advanced_technicals", {})
        news = report.get("news_articles", [])
        reddit = report.get("reddit_data", {})

        parts = [f"## Research Report: {ticker}\n"]

        # Price & technicals
        if "error" not in tech:
            parts.append(f"**Price:** ${tech.get('current_price', 'N/A')}")
            parts.append(f"**Prev Close:** ${tech.get('previous_close', 'N/A')}")
            parts.append(f"**Daily Change:** {tech.get('daily_change_pct', 0)}%")
            parts.append(f"**RSI(14):** {tech.get('rsi_14', 'N/A')}")
            parts.append(f"**SMA-10:** ${tech.get('sma_10', 'N/A')} | **SMA-20:** ${tech.get('sma_20', 'N/A')}")
            parts.append(f"**Above SMA-10:** {tech.get('above_sma_10')} | **Above SMA-20:** {tech.get('above_sma_20')}")
            parts.append(f"**Volume Ratio:** {tech.get('volume_ratio', 'N/A')}x average")

        # Advanced technicals (Twelve Data)
        if adv:
            macd = adv.get("macd", {})
            if macd:
                parts.append(f"\n**MACD:** {macd.get('macd', 'N/A')} | Signal: {macd.get('signal', 'N/A')} | Histogram: {macd.get('histogram', 'N/A')} | Crossover: {macd.get('crossover', 'none')} | Trend: {macd.get('trend', 'N/A')}")

            bbands = adv.get("bbands", {})
            if bbands:
                parts.append(f"**Bollinger Bands:** Upper ${bbands.get('upper', 'N/A')} | Middle ${bbands.get('middle', 'N/A')} | Lower ${bbands.get('lower', 'N/A')} | Bandwidth: {bbands.get('bandwidth_pct', 'N/A')}%")

            ema = adv.get("ema", {})
            if ema:
                parts.append(f"**EMA 9/21:** {ema.get('ema_9', 'N/A')} / {ema.get('ema_21', 'N/A')} | Crossover: {ema.get('crossover', 'N/A')}")

            stoch = adv.get("stoch", {})
            if stoch:
                parts.append(f"**Stochastic:** K={stoch.get('k', 'N/A')} D={stoch.get('d', 'N/A')} | Zone: {stoch.get('zone', 'N/A')}")

            adx_data = adv.get("adx", {})
            if adx_data:
                parts.append(f"**ADX:** {adx_data.get('adx', 'N/A')} | Trend Strength: {adx_data.get('trend_strength', 'N/A')}")

            atr_data = adv.get("atr", {})
            if atr_data:
                parts.append(f"**ATR(14):** ${atr_data.get('atr', 'N/A')}")

        # News
        if news:
            parts.append(f"\n**News Impact Score:** {report.get('news_impact_score', 0)}/10")
            parts.append("**Top Headlines:**")
            for a in news[:5]:
                parts.append(f"  - [{a.get('impact_score', 0):+.1f}] {a.get('title', 'N/A')} ({a.get('source', '')})")

        # Reddit
        if reddit.get("post_count", 0) > 0:
            parts.append(f"\n**Reddit Sentiment:** {reddit.get('overall_sentiment', 0):.2f} ({reddit.get('post_count', 0)} posts)")
            themes = reddit.get("themes", [])
            if themes:
                parts.append(f"**Themes:** {', '.join(themes)}")
        else:
            parts.append("\n**Reddit:** No data available")

        # Yahoo Finance Fundamentals
        fund = report.get("fundamentals", {})
        if fund:
            fins = fund.get("financials", {})
            if fins:
                parts.append("\n**Fundamentals:**")
                if fins.get("market_cap"):
                    cap = fins["market_cap"]
                    cap_str = f"${cap/1e9:.1f}B" if cap > 1e9 else f"${cap/1e6:.0f}M"
                    parts.append(f"  Market Cap: {cap_str} | Sector: {fins.get('sector', 'N/A')} | Industry: {fins.get('industry', 'N/A')}")
                if fins.get("pe_ratio"):
                    parts.append(f"  P/E: {fins['pe_ratio']:.1f} | Forward P/E: {fins.get('forward_pe', 'N/A')} | PEG: {fins.get('peg_ratio', 'N/A')}")
                if fins.get("revenue_growth") is not None:
                    parts.append(f"  Revenue Growth: {fins['revenue_growth']*100:.1f}% | Profit Margin: {fins.get('profit_margin', 0)*100 if fins.get('profit_margin') else 'N/A'}% | ROE: {fins.get('return_on_equity', 0)*100 if fins.get('return_on_equity') else 'N/A'}%")
                if fins.get("debt_to_equity") is not None:
                    parts.append(f"  Debt/Equity: {fins['debt_to_equity']:.0f} | Beta: {fins.get('beta', 'N/A')}")
                if fins.get("52w_high"):
                    parts.append(f"  52W Range: ${fins.get('52w_low', 'N/A')} - ${fins['52w_high']} | 50D Avg: ${fins.get('50d_avg', 'N/A')} | 200D Avg: ${fins.get('200d_avg', 'N/A')}")

            analyst = fund.get("analyst", {})
            if analyst and analyst.get("recommendation"):
                parts.append(f"\n**Analyst Consensus:** {analyst.get('recommendation', 'N/A').upper()} ({analyst.get('num_analysts', '?')} analysts)")
                if analyst.get("target_mean"):
                    parts.append(f"  Price Target: ${analyst['target_mean']:.2f} (Low: ${analyst.get('target_low', 'N/A')} / High: ${analyst.get('target_high', 'N/A')})")
                if analyst.get("upside_pct") is not None:
                    parts.append(f"  Implied Upside: {analyst['upside_pct']:+.1f}%")
                if analyst.get("strong_buy") is not None:
                    parts.append(f"  Ratings: {analyst.get('strong_buy', 0)} Strong Buy / {analyst.get('buy', 0)} Buy / {analyst.get('hold', 0)} Hold / {analyst.get('sell', 0)} Sell / {analyst.get('strong_sell', 0)} Strong Sell")

            earnings = fund.get("earnings", {})
            if earnings:
                if earnings.get("next_date"):
                    parts.append(f"\n**Earnings:** Next date: {earnings['next_date']} ({earnings.get('days_until', '?')} days away)")
                    if earnings.get("imminent"):
                        parts.append("  ⚠ EARNINGS IMMINENT — HIGH EVENT RISK")
                if earnings.get("beat_rate") is not None:
                    parts.append(f"  Beat rate (last 4Q): {earnings['beat_rate']}%")

            insider = fund.get("insider", {})
            if insider.get("signal") and insider["signal"] != "no data":
                parts.append(f"\n**Insider Activity:** {insider['signal'].replace('_', ' ').title()} — {insider.get('buys', 0)} buys / {insider.get('sells', 0)} sells")

            inst = fund.get("institutional", {})
            if inst.get("held_pct"):
                parts.append(f"**Institutional Ownership:** {inst['held_pct']*100:.1f}%")

        # Combined scores
        parts.append(f"\n**Combined Catalyst Score:** {report.get('combined_catalyst_score', 0)}")
        parts.append(f"**Identified Risks:** {', '.join(report.get('risks', []))}")
        parts.append(f"**Identified Opportunities:** {', '.join(report.get('opportunities', []))}")

        return "\n".join(parts)

    def _parse_response(self, text: str, ticker: str) -> dict | None:
        """Parse Claude's JSON response, handling edge cases."""
        # Strip markdown code fences if present
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        # Find the JSON object boundaries (handle extra text after JSON)
        start = cleaned.find("{")
        if start == -1:
            logger.warning("No JSON object found in AI response")
            return None

        # Find matching closing brace
        depth = 0
        end = start
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        cleaned = cleaned[start:end]

        try:
            result = json.loads(cleaned)
            # Validate required fields
            required = ["ticker", "action", "conviction"]
            for field in required:
                if field not in result:
                    logger.warning(f"AI response missing field: {field}")
                    return None
            # Ensure ticker matches
            result["ticker"] = ticker
            # Clamp conviction
            result["conviction"] = max(1.0, min(10.0, float(result["conviction"])))
            return result
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse AI response as JSON: {e} | First 200 chars: {cleaned[:200]}")
            return None

    def analyze(self, report: dict) -> dict:
        """Run AI-powered deep analysis on a research report."""
        ticker = report["ticker"]
        logger.info(f"AI DeepThink analysis starting for {ticker}...")

        try:
            prompt = self._build_report_prompt(report)

            response = self.client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract text from response — collect all text blocks
            text_parts = []
            for block in response.content:
                if block.type == "text":
                    text_parts.append(block.text)
            text = "\n".join(text_parts)

            if not text:
                # Log what we actually got back
                block_types = [block.type for block in response.content]
                logger.warning(
                    f"No text in AI response for {ticker}. "
                    f"Stop reason: {response.stop_reason}, "
                    f"Block types: {block_types}, "
                    f"Usage: in={response.usage.input_tokens} out={response.usage.output_tokens}"
                )
                return self.fallback.analyze(report)

            analysis = self._parse_response(text, ticker)
            if analysis is None:
                logger.warning(f"Failed to parse AI response for {ticker}, falling back to rules")
                return self.fallback.analyze(report)

            # Ensure all expected fields exist with defaults
            analysis.setdefault("position_size_pct", 2.0)
            analysis.setdefault("stop_loss_pct", 5.0)
            analysis.setdefault("take_profit_pct", 10.0)
            analysis.setdefault("reasoning_summary", "")
            analysis.setdefault("bullish_factors", [])
            analysis.setdefault("bearish_factors", [])
            analysis.setdefault("contrarian_views", [])
            analysis.setdefault("scenarios", [])
            analysis.setdefault("risks", [])
            analysis["current_price"] = report.get("technicals", {}).get("current_price", 0)

            # Save to database
            self.db.save_analysis(analysis)

            logger.info(
                f"AI DeepThink result for {ticker}: {analysis['action']} "
                f"(conviction: {analysis['conviction']}) — "
                f"{analysis.get('reasoning_summary', '')[:100]}"
            )

            return analysis

        except anthropic.AuthenticationError:
            logger.error("Anthropic API key invalid — falling back to rule-based analysis")
            return self.fallback.analyze(report)
        except anthropic.RateLimitError:
            logger.warning("Anthropic rate limited — falling back to rule-based analysis")
            return self.fallback.analyze(report)
        except Exception as e:
            logger.error(f"AI DeepThink error for {ticker}: {e}", exc_info=True)
            return self.fallback.analyze(report)
