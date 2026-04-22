"""Post-trade reflection writer.

Called when a trade closes. Asks Claude for a 1-2 sentence lesson comparing
the original thesis to the actual outcome, then persists it to the
`reflections` table. The point: next time we analyze a similar setup, we
can retrieve these lessons and inject them into the prompt.

If the Anthropic client is unavailable (no API key, network down), we fall
back to a templated lesson so the memory loop still has *something* to
retrieve.
"""
from __future__ import annotations

import logging

from config import Config
from utils.database import Database

logger = logging.getLogger(__name__)

_SYSTEM = """You are a trading coach writing one-line post-trade lessons for your own future use.

Given a trade's original thesis and actual outcome, distill the single most
transferable lesson in 1-2 sentences. Focus on:
- What the thesis got right or wrong
- What signal (if any) could have warned us earlier
- A concrete rule a future version of you could apply

Be specific and terse. No hedging, no generic platitudes, no "remember to..."
openings. Write as if you'll re-read it in a month and need it to change
your behavior. Respond with the lesson text only — no JSON, no quotes."""


class ReflectionWriter:
    def __init__(self, user_id: int, db: Database | None = None, config: Config | None = None) -> None:
        """Per-user reflection writer. Lessons are written scoped to user_id."""
        self.db = db or Database()
        self.config = config or Config()
        self.user_id = user_id
        self._client = self._build_client()

    def _build_client(self):
        api_key = getattr(self.config, "ANTHROPIC_API_KEY", None)
        if not api_key:
            return None
        try:
            import anthropic
            return anthropic.Anthropic(api_key=api_key)
        except Exception as e:  # import error, bad key, etc.
            logger.warning(f"Reflection writer: Claude client unavailable ({e})")
            return None

    # ── Main entry point ──────────────────────────────────────────────────

    def on_trade_closed(
        self,
        trade_id: int,
        ticker: str,
        thesis: str,
        outcome_pnl: float,
        outcome_context: str = "",
    ) -> int | None:
        """Generate and save a lesson. Returns reflection id, or None on failure."""
        lesson = self._generate_lesson(ticker, thesis, outcome_pnl, outcome_context)
        if not lesson:
            return None
        try:
            rid = self.db.save_reflection(
                user_id=self.user_id, trade_id=trade_id, ticker=ticker, thesis=thesis,
                outcome_pnl=outcome_pnl, lesson=lesson,
            )
            logger.info(f"Reflection saved for {ticker} trade {trade_id} (id={rid})")
            return rid
        except Exception as e:
            logger.warning(f"Failed to save reflection for {ticker}: {e}")
            return None

    # ── Lesson generation ────────────────────────────────────────────────

    def _generate_lesson(
        self, ticker: str, thesis: str, pnl: float, context: str = ""
    ) -> str | None:
        if self._client is None:
            return self._fallback_lesson(ticker, thesis, pnl, context)
        prompt = self._build_prompt(ticker, thesis, pnl, context)
        try:
            resp = self._client.messages.create(
                model=getattr(self.config, "CLAUDE_MODEL", "claude-haiku-4-5"),
                max_tokens=256,
                system=[{
                    "type": "text",
                    "text": _SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt}],
            )
            return resp.content[0].text.strip()
        except Exception as e:
            logger.warning(f"Reflection Claude call failed for {ticker}: {e}")
            return self._fallback_lesson(ticker, thesis, pnl, context)

    @staticmethod
    def _build_prompt(ticker: str, thesis: str, pnl: float, context: str) -> str:
        outcome = "won" if pnl > 0 else "lost" if pnl < 0 else "breakeven"
        ctx = f"\n\nExit context: {context}" if context else ""
        return (
            f"Ticker: {ticker}\n"
            f"Original thesis: {thesis}\n"
            f"Outcome: {outcome} (${pnl:+.2f})"
            f"{ctx}\n\n"
            "Write the lesson."
        )

    @staticmethod
    def _fallback_lesson(ticker: str, thesis: str, pnl: float, context: str) -> str:
        """Deterministic fallback when Claude is unavailable. Not useful for
        learning, but keeps the memory table non-empty so retrieval works."""
        outcome = "win" if pnl > 0 else "loss" if pnl < 0 else "flat"
        reason = context or "no exit context recorded"
        return f"{ticker} {outcome} (${pnl:+.2f}): {reason}. Original thesis: {thesis[:160]}"


# ─────────────────────────── Retrieval helper ────────────────────────────


def format_reflections_for_prompt(reflections: list[dict]) -> str:
    """Render retrieved reflections as a concise prompt fragment."""
    if not reflections:
        return ""
    lines = ["# Past trade lessons (most recent first, for context):"]
    for r in reflections:
        date = r["created_at"][:10]
        lines.append(f"- [{date} {r['ticker']} {r['outcome_label']}] {r['lesson']}")
    return "\n".join(lines)
