"""Bull/Bear debate engine — adversarial LLM analysis for trade decisions.

Inspired by TradingAgents' multi-agent debate system. Runs bull and bear
analysts through 2 rounds of argument, then a judge synthesizes the winner.
"""

import json
import logging

import anthropic

logger = logging.getLogger(__name__)

_BULL_SYSTEM = """You are a bull analyst at a hedge fund, advocating FOR this trade.
Find every reason to buy. Use the research data — cite exact numbers.
Be aggressive but grounded in data. Counter the bear's arguments directly.

Respond with ONLY valid JSON (no markdown):
{"thesis": "your bull case in 2-3 sentences",
 "key_evidence": ["evidence 1", "evidence 2", "evidence 3"],
 "conviction": 7.5,
 "rebuttal": "counter to bear's last argument (empty string if round 1)"}"""

_BEAR_SYSTEM = """You are a bear analyst at a hedge fund, arguing AGAINST this trade.
Find every reason NOT to buy. Expose weaknesses, hidden risks, and what the
bull is ignoring. Be specific — cite exact numbers from the data.

Respond with ONLY valid JSON (no markdown):
{"counter_thesis": "your bear case in 2-3 sentences",
 "key_risks": ["risk 1", "risk 2", "risk 3"],
 "conviction": 7.5,
 "rebuttal": "counter to bull's last argument (empty string if round 1)"}"""

_JUDGE_SYSTEM = """You are the portfolio manager making the final call. You've read the
bull and bear debate. Pick the side with the most compelling EVIDENCE,
not the strongest rhetoric. Do NOT split the difference — commit to a direction.

If the evidence is genuinely balanced, choose HOLD. But if one side has
stronger data-backed arguments, commit to BUY or SELL.

Respond with ONLY valid JSON (no markdown):
{"decision": "BUY or SELL or HOLD",
 "conviction": 7.5,
 "reasoning": "why you chose this side in 2-3 sentences",
 "winning_side": "bull or bear",
 "key_factor": "the single most important piece of evidence"}"""


class DebateEngine:
    def __init__(self, model: str, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def _call(self, system: str, prompt: str, max_tokens: int = 1024) -> str | None:
        import time
        from utils.llm_logger import log_call
        start = time.monotonic()
        response = None
        error = None
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.content[0].text
        except Exception as e:
            error = str(e)
            logger.error(f"Debate LLM call failed: {e}")
            return None
        finally:
            log_call(
                source="debate_engine",
                model=self.model,
                system=system,
                prompt=prompt,
                response=response,
                latency_ms=int((time.monotonic() - start) * 1000),
                error=error,
            )

    def _parse_json(self, text: str | None) -> dict | None:
        if not text:
            return None
        # Strip markdown fences first
        cleaned = text.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (```json or ```)
            first_nl = cleaned.index("\n") if "\n" in cleaned else len(cleaned)
            cleaned = cleaned[first_nl + 1:]
            # Remove closing fence if present
            if "```" in cleaned:
                cleaned = cleaned[:cleaned.rindex("```")]
            cleaned = cleaned.strip()
        # Try direct parse
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass
        # Try finding raw braces (handles truncated responses)
        try:
            start = cleaned.index("{")
            # Find matching closing brace
            depth = 0
            for i in range(start, len(cleaned)):
                if cleaned[i] == "{":
                    depth += 1
                elif cleaned[i] == "}":
                    depth -= 1
                    if depth == 0:
                        return json.loads(cleaned[start:i + 1])
        except (ValueError, json.JSONDecodeError):
            pass
        # Last resort: find outermost braces even if JSON is truncated — try to repair
        try:
            start = cleaned.index("{")
            fragment = cleaned[start:]
            # Close any open strings and braces
            if not fragment.endswith("}"):
                # Truncated — try closing it
                fragment = fragment.rstrip(",\n ") + '}'
                # Close any open strings
                if fragment.count('"') % 2 == 1:
                    fragment = fragment.rstrip() + '"}'
            return json.loads(fragment)
        except (ValueError, json.JSONDecodeError):
            pass
        logger.warning(f"Failed to parse debate JSON: {text[:200]}")
        return None

    def _build_data_summary(self, report: dict, rule_analysis: dict) -> str:
        """Build condensed data summary for debate prompts."""
        ticker = report.get("ticker", "?")
        tech = report.get("technicals", {})
        fundamentals = report.get("fundamentals", {})
        adv = report.get("advanced_technicals", {})
        macd = adv.get("macd", {})
        stoch = adv.get("stoch", {})
        fins = fundamentals.get("financials", {}) if fundamentals else {}
        analyst = fundamentals.get("analyst", {}) if fundamentals else {}
        news = report.get("news_articles", [])
        options = report.get("options_flow", {})

        edges = rule_analysis.get("edge_details", [])
        bull_factors = [f["factor"] for f in rule_analysis.get("bullish_factors", [])[:4]]
        bear_factors = [f["factor"] for f in rule_analysis.get("bearish_factors", [])[:4]]

        opt_line = ""
        if options and options.get("unusual_strikes", 0) > 0:
            opt_line = (
                f"\nOPTIONS FLOW: P/C={options.get('put_call_ratio', 1):.2f}, "
                f"unusual strikes={options.get('unusual_strikes', 0)}, "
                f"premium=${options.get('total_unusual_premium', 0):,.0f}, "
                f"signal={options.get('signal_strength', 0):+.3f}"
            )

        return f"""TICKER: {ticker} | ${tech.get('current_price', 0):.2f} | {tech.get('daily_change_pct', 0):+.2f}%
RSI: {tech.get('rsi_14', 50)} | Volume: {tech.get('volume_ratio', 1):.1f}x | MACD: {macd.get('crossover', 'none')} | Stoch: {stoch.get('zone', 'none')}
P/E: {fins.get('pe_ratio', 'N/A')} | Growth: {fins.get('revenue_growth', 'N/A')} | ROE: {fins.get('roe', 'N/A')} | D/E: {fins.get('debt_to_equity', 'N/A')}
Analyst: {analyst.get('recommendation', 'N/A')} | Target upside: {analyst.get('upside_pct', 'N/A')}%
Edges: {', '.join(f"{e['label']}={'PASS' if e['passed'] else 'FAIL'}" for e in edges)}
Rule conviction: {rule_analysis.get('conviction', 5)}/10 | Action: {rule_analysis.get('action', 'HOLD')}
Bullish: {'; '.join(bull_factors)}
Bearish: {'; '.join(bear_factors)}
News: {'; '.join(a.get('title', '')[:60] for a in news[:3])}{opt_line}"""

    def run_debate(self, report: dict, rule_analysis: dict, rounds: int = 2) -> dict | None:
        """Run bull/bear debate with judge synthesis.

        Returns dict with decision, conviction, reasoning, or None on failure.
        """
        ticker = report.get("ticker", "?")
        data_summary = self._build_data_summary(report, rule_analysis)
        logger.info(f"Debate starting for {ticker} ({rounds} rounds)")

        bull_history = []
        bear_history = []

        for round_num in range(1, rounds + 1):
            # Bull's turn
            bull_context = f"DATA:\n{data_summary}"
            if bear_history:
                bull_context += f"\n\nBEAR'S LAST ARGUMENT:\n{bear_history[-1]}"
            bull_context += f"\n\nRound {round_num}/{rounds}. Make your case."

            bull_raw = self._call(_BULL_SYSTEM, bull_context)
            bull_parsed = self._parse_json(bull_raw)
            if not bull_parsed:
                logger.warning(f"Bull failed to produce valid JSON in round {round_num}")
                return None
            bull_history.append(bull_raw)

            # Bear's turn
            bear_context = f"DATA:\n{data_summary}"
            bear_context += f"\n\nBULL'S ARGUMENT:\n{bull_raw}"
            if len(bear_history) > 0:
                bear_context += f"\n\nYour previous argument:\n{bear_history[-1]}"
            bear_context += f"\n\nRound {round_num}/{rounds}. Counter the bull."

            bear_raw = self._call(_BEAR_SYSTEM, bear_context)
            bear_parsed = self._parse_json(bear_raw)
            if not bear_parsed:
                logger.warning(f"Bear failed to produce valid JSON in round {round_num}")
                return None
            bear_history.append(bear_raw)

            logger.info(
                f"Debate {ticker} R{round_num}: bull conv={bull_parsed.get('conviction', '?')}, "
                f"bear conv={bear_parsed.get('conviction', '?')}"
            )

        # Judge synthesis
        debate_transcript = ""
        for i in range(len(bull_history)):
            debate_transcript += f"\n--- Round {i+1} ---\nBULL: {bull_history[i]}\nBEAR: {bear_history[i]}"

        judge_prompt = f"DATA:\n{data_summary}\n\nDEBATE TRANSCRIPT:{debate_transcript}\n\nMake your decision."

        judge_raw = self._call(_JUDGE_SYSTEM, judge_prompt, max_tokens=512)
        judge_parsed = self._parse_json(judge_raw)
        if not judge_parsed:
            logger.warning(f"Judge failed to produce valid JSON for {ticker}")
            return None

        decision = judge_parsed.get("decision", "HOLD").upper()
        if decision not in ("BUY", "SELL", "HOLD"):
            decision = "HOLD"

        conviction = max(1.0, min(10.0, float(judge_parsed.get("conviction", 5.0))))

        result = {
            "decision": decision,
            "conviction": conviction,
            "bull_thesis": bull_parsed.get("thesis", ""),
            "bear_thesis": bear_parsed.get("counter_thesis", ""),
            "judge_reasoning": judge_parsed.get("reasoning", ""),
            "winning_side": judge_parsed.get("winning_side", "unknown"),
            "key_factor": judge_parsed.get("key_factor", ""),
            "rounds_played": rounds,
        }

        logger.info(
            f"Debate {ticker} VERDICT: {decision} (conviction {conviction:.1f}, "
            f"winner: {result['winning_side']}, factor: {result['key_factor'][:60]})"
        )

        return result
