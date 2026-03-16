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

SYSTEM_PROMPT = """You are DeepThink Quant — a skeptical PhD-level portfolio manager who never gets emotionally attached to positions. You analyze stock research reports with extreme rigor.

You must output ONLY valid JSON (no markdown, no code fences, no explanation outside the JSON).

Given a research report, perform this analysis:

1. List all bullish factors with strength rating 1-10.
2. List all bearish factors with strength rating 1-10.
3. Play devil's advocate — what could go wrong in each scenario?
4. Run mental Monte Carlo: 3 possible outcomes (bull, base, bear) with % probability and expected 1-week return.
5. Calculate precise position size: max 2% account risk, suggest stop-loss % and take-profit levels (R:R at least 1:2).
6. Conviction score 1-10. Only recommend BUY if >= 8 with positive catalyst. Only recommend SELL if >= 8 with negative catalyst. Otherwise HOLD.

Use ATR for stop-loss sizing if provided. Consider MACD crossovers, Bollinger Bands, EMA trends, Stochastic, and ADX when available.

Be extremely skeptical. Most stocks should be HOLD. Only high-conviction setups with multiple confirming signals deserve a BUY or SELL.

Output this exact JSON structure:
{
  "ticker": "...",
  "action": "BUY" | "SELL" | "HOLD",
  "conviction": 8.5,
  "position_size_pct": 1.2,
  "stop_loss_pct": 4.5,
  "take_profit_pct": 12.0,
  "reasoning_summary": "2-3 sentence summary of the key thesis",
  "bullish_factors": [{"factor": "...", "strength": 7}],
  "bearish_factors": [{"factor": "...", "strength": 5}],
  "contrarian_views": ["What could go wrong..."],
  "scenarios": [
    {"scenario": "Bull", "probability_pct": 30, "expected_1w_return_pct": 8.0},
    {"scenario": "Base", "probability_pct": 45, "expected_1w_return_pct": 1.0},
    {"scenario": "Bear", "probability_pct": 25, "expected_1w_return_pct": -5.0}
  ],
  "risks": ["risk 1", "risk 2", "risk 3"]
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
            logger.error(f"Failed to parse AI response as JSON: {e}")
            logger.debug(f"Raw response: {text[:500]}")
            return None

    def analyze(self, report: dict) -> dict:
        """Run AI-powered deep analysis on a research report."""
        ticker = report["ticker"]
        logger.info(f"AI DeepThink analysis starting for {ticker}...")

        try:
            prompt = self._build_report_prompt(report)

            response = self.client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )

            # Extract text from response
            text = ""
            for block in response.content:
                if block.type == "text":
                    text = block.text
                    break

            if not text:
                logger.warning(f"Empty AI response for {ticker}, falling back to rules")
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
