"""Claude Analyst — LLM-powered qualitative analysis layer for DeepThinkTrader.

Uses Claude API to provide qualitative judgment that rule-based scoring can't:
- News headline interpretation (sarcasm, one-time events, misleading sentiment)
- Signal correlation detection (are the 3 edges truly independent?)
- Earnings quality assessment (sustainable growth vs accounting tricks)
- Risk narrative synthesis (connecting dots between multiple risk factors)
- Contrarian reasoning that goes beyond templates

Returns structured JSON that feeds into the conviction scoring pipeline.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from config import Config

logger = logging.getLogger(__name__)


class ClaudeAnalyst:
    """Qualitative analysis powered by Claude API."""

    def __init__(self):
        self.config = Config()
        self._client = None
        self._enabled = bool(self.config.ANTHROPIC_API_KEY) and self.config.CLAUDE_ANALYSIS_ENABLED
        self._model = self.config.CLAUDE_MODEL

        if self._enabled:
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=self.config.ANTHROPIC_API_KEY)
                logger.info(f"Claude Analyst initialized (model: {self._model})")
            except Exception as e:
                logger.warning(f"Claude Analyst disabled: {e}")
                self._enabled = False
        else:
            reason = "disabled by config" if not self.config.CLAUDE_ANALYSIS_ENABLED else "no API key"
            logger.info(f"Claude Analyst disabled — {reason}")

    @property
    def enabled(self) -> bool:
        return self._enabled and self._client is not None

    def _call(self, system: str, prompt: str, max_tokens: int = 1024) -> str | None:
        """Make a Claude API call. Returns raw text response or None on error.

        The system prompt is marked with ephemeral cache_control. Anthropic
        silently ignores it when the block is below the model's minimum
        cache size, so this is safe for short prompts too.
        """
        if not self.enabled:
            return None
        import time
        from utils.llm_logger import log_call
        start = time.monotonic()
        response = None
        error = None
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=max_tokens,
                system=[{
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            error = str(e)
            logger.error(f"Claude API error: {e}")
            return None
        finally:
            log_call(
                source="claude_analyst",
                model=self._model,
                system=system,
                prompt=prompt,
                response=response,
                latency_ms=int((time.monotonic() - start) * 1000),
                error=error,
            )

    def _parse_json_response(self, text: str | None) -> dict | None:
        """Extract JSON from Claude's response."""
        if not text:
            return None
        try:
            # Try direct parse first
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        # Try extracting JSON block
        for start, end in [("```json", "```"), ("```", "```"), ("{", None)]:
            idx = text.find(start)
            if idx != -1:
                content = text[idx + len(start):]
                if end and end != start:
                    end_idx = content.find(end)
                    if end_idx != -1:
                        content = content[:end_idx]
                elif start == "{":
                    # Find matching closing brace
                    depth = 0
                    for i, c in enumerate(text[idx:]):
                        if c == "{":
                            depth += 1
                        elif c == "}":
                            depth -= 1
                            if depth == 0:
                                content = text[idx:idx + i + 1]
                                break
                try:
                    return json.loads(content.strip())
                except json.JSONDecodeError:
                    continue
        logger.warning(f"Failed to parse Claude JSON response: {text[:200]}")
        return None

    def analyze_trade(self, report: dict, rule_analysis: dict) -> dict:
        """Run full qualitative analysis on a research report + rule-based analysis.

        Called after the rule-based DeepThink scoring but before the final decision.

        Returns:
            {
                "conviction_adjustment": float (-2.0 to +2.0),
                "action_override": str | None ("BUY", "SELL", "HOLD", or None to keep rule-based),
                "qualitative_assessment": str,
                "news_interpretation": str,
                "signal_independence": str,
                "key_risk": str,
                "catalyst_quality": str,
                "confidence": float (0-1),
            }
        """
        if not self.enabled:
            return self._default_result()

        ticker = report.get("ticker", "UNKNOWN")
        logger.info(f"Claude Analyst: analyzing {ticker}...")

        # Build a concise data summary for the prompt
        data_summary = self._build_data_summary(report, rule_analysis)

        system = """You are a senior equity analyst at a quantitative hedge fund. You review
research data and rule-based trading signals, then provide qualitative judgment that algorithms miss.

You MUST respond with valid JSON only — no markdown, no explanation outside the JSON.

Your job is NOT to repeat what the numbers say. Your job is to catch what the numbers miss:
- Is a positive news headline actually sarcastic or misleading?
- Is an earnings beat sustainable or a one-time accounting trick?
- Are the bullish signals actually correlated (not independent edges)?
- Is there a macro narrative that changes everything?
- Would a human trader see something the algorithm doesn't?

Be skeptical. Most trade setups fail. Your conviction_adjustment should usually be small (-0.5 to +0.5).
Only use larger adjustments (-2 to +2) when you see something the rules clearly missed."""

        prompt = f"""Analyze this trade setup for {ticker} and return JSON:

{data_summary}

Return this exact JSON structure:
{{
  "conviction_adjustment": <float, -2.0 to +2.0, how much to adjust the rule-based conviction>,
  "action_override": <null to keep rule-based action, or "BUY"/"SELL"/"HOLD" to override>,
  "qualitative_assessment": "<1-2 sentence overall judgment>",
  "news_interpretation": "<are the news headlines being scored correctly by VADER? any misleading sentiment?>",
  "signal_independence": "<are the bullish/bearish signals truly independent or correlated?>",
  "key_risk": "<the single biggest risk the rule-based system might be underweighting>",
  "catalyst_quality": "<is the catalyst sustainable or a one-time event?>",
  "confidence": <float 0-1, how confident are you in your assessment>
}}"""

        raw = self._call(system, prompt)
        result = self._parse_json_response(raw)

        if result:
            # Clamp conviction adjustment
            adj = result.get("conviction_adjustment", 0)
            result["conviction_adjustment"] = max(-2.0, min(2.0, float(adj)))
            result["confidence"] = max(0, min(1, float(result.get("confidence", 0.5))))

            # Validate action_override
            override = result.get("action_override")
            if override and override not in ("BUY", "SELL", "HOLD"):
                result["action_override"] = None

            logger.info(
                f"Claude Analyst {ticker}: adj={result['conviction_adjustment']:+.1f}, "
                f"override={result.get('action_override')}, "
                f"conf={result['confidence']:.0%}, "
                f"assessment={result.get('qualitative_assessment', '')[:80]}"
            )
            return result

        logger.warning(f"Claude Analyst: failed to get valid response for {ticker}")
        return self._default_result()

    def _build_data_summary(self, report: dict, rule_analysis: dict) -> str:
        """Build a concise text summary of all data for the prompt."""
        ticker = report.get("ticker", "?")
        tech = report.get("technicals", {})
        fundamentals = report.get("fundamentals", {})
        sa = report.get("seeking_alpha", {})

        # Technicals
        price = tech.get("current_price", 0)
        rsi = tech.get("rsi_14", 50)
        vol_ratio = tech.get("volume_ratio", 1)
        daily_change = tech.get("daily_change_pct", 0)

        # Advanced technicals
        adv = report.get("advanced_technicals", {})
        macd = adv.get("macd", {})
        bbands = adv.get("bbands", {})
        stoch = adv.get("stoch", {})

        # Fundamentals
        fins = fundamentals.get("financials", {}) if fundamentals else {}
        analyst = fundamentals.get("analyst", {}) if fundamentals else {}
        earnings = fundamentals.get("earnings", {}) if fundamentals else {}

        # News
        news_articles = report.get("news_articles", [])
        news_titles = [a.get("title", "") for a in news_articles[:5]]

        # SA
        sa_articles = sa.get("rss_articles", []) if sa else []
        sa_titles = [a.get("title", "") for a in sa_articles[:5]]

        # Rule-based signals
        action = rule_analysis.get("action", "HOLD")
        conviction = rule_analysis.get("conviction", 5)
        bull_factors = [f["factor"] for f in rule_analysis.get("bullish_factors", [])[:4]]
        bear_factors = [f["factor"] for f in rule_analysis.get("bearish_factors", [])[:4]]
        edges = rule_analysis.get("edge_details", [])

        return f"""TICKER: {ticker} | Price: ${price:.2f} | Daily Change: {daily_change:+.2f}%

TECHNICALS:
  RSI(14): {rsi} | Volume: {vol_ratio:.1f}x avg
  MACD: crossover={macd.get('crossover', 'none')}, trend={macd.get('trend', 'none')}
  Stochastic: zone={stoch.get('zone', 'none')}, K={stoch.get('k', 0):.0f}
  Bollinger: bandwidth={bbands.get('bandwidth_pct', 0):.1f}%

FUNDAMENTALS:
  P/E: {fins.get('pe_ratio', 'N/A')} | Forward P/E: {fins.get('forward_pe', 'N/A')}
  Revenue Growth: {fins.get('revenue_growth', 'N/A')} | ROE: {fins.get('roe', 'N/A')}
  Debt/Equity: {fins.get('debt_to_equity', 'N/A')} | Beta: {fins.get('beta', 'N/A')}
  Analyst Consensus: {analyst.get('recommendation', 'N/A')} | Target Upside: {analyst.get('upside_pct', 'N/A')}%
  Earnings in: {earnings.get('days_until', 'N/A')} days

NEWS HEADLINES (VADER-scored):
{chr(10).join(f'  - {t}' for t in news_titles) if news_titles else '  (none)'}

SEEKING ALPHA ARTICLES:
{chr(10).join(f'  - [{a.get("sentiment", 0):+.2f}] {a.get("title", "")}' for a in sa_articles[:5]) if sa_articles else '  (none)'}

RULE-BASED ANALYSIS:
  Action: {action} | Conviction: {conviction}/10
  Catalyst Score: {report.get('combined_catalyst_score', 0):.3f}
  Edges: {', '.join(f"{e['label']}={'PASS' if e['passed'] else 'FAIL'}" for e in edges)}
  Bullish: {'; '.join(bull_factors)}
  Bearish: {'; '.join(bear_factors)}"""

    def _default_result(self) -> dict:
        """Return neutral result when Claude is disabled or fails."""
        return {
            "conviction_adjustment": 0.0,
            "action_override": None,
            "qualitative_assessment": "Claude analysis unavailable",
            "news_interpretation": "",
            "signal_independence": "",
            "key_risk": "",
            "catalyst_quality": "",
            "confidence": 0.0,
        }
