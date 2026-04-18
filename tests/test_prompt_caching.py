"""Tests that both Claude-calling agents send cache_control on the system prompt.

Prompt caching is a cost lever. A missed cache_control on ai_deepthink means
~10× cost on every analysis. These tests intercept the messages.create call
and assert the system content block structure.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock


def test_ai_deepthink_sends_cache_control_on_system_prompt(monkeypatch):
    from agents.ai_deepthink_agent import AIDeepThinkAgent

    captured: dict = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(
                type="text",
                text=(
                    '{"ticker":"TEST","action":"HOLD","conviction":5,'
                    '"reasoning":"test","edges_hit":0,'
                    '"stop_loss_pct":0,"take_profit_pct":0}'
                ),
            )],
        )

    # Build an agent without hitting the real anthropic client.
    agent = AIDeepThinkAgent.__new__(AIDeepThinkAgent)
    agent.client = MagicMock()
    agent.client.messages.create = fake_create
    agent.config = MagicMock()
    agent.fallback = MagicMock()  # used only if parse fails
    agent.logger = MagicMock()

    # Minimal report shape for _build_report_prompt.
    report = {
        "ticker": "TEST",
        "news": [], "reddit": {"overall_sentiment": 0}, "technicals": {},
        "fundamentals": {}, "options_flow": {}, "sa_intel": {},
        "sa_rss_intel": {}, "market_regime": {},
        "advanced_technicals": {}, "aggregated_articles": [],
        "combined_catalyst_score": 0.0,
    }
    agent.analyze(report)

    # cache_control must be on the system block.
    system = captured.get("system")
    assert isinstance(system, list), "system must be a list of content blocks for caching"
    assert system[0].get("cache_control") == {"type": "ephemeral"}
    assert "DeepThink" in system[0]["text"]  # Sanity — still the right prompt


def test_claude_analyst_sends_cache_control_on_system_prompt(monkeypatch):
    from utils.claude_analyst import ClaudeAnalyst

    captured: dict = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            content=[SimpleNamespace(text='{"conviction_adjustment":0,"action_override":null,"qualitative_assessment":"t","news_interpretation":"t","signal_independence":"t","key_risk":"t","catalyst_quality":"t","confidence":0.5}')]
        )

    analyst = ClaudeAnalyst.__new__(ClaudeAnalyst)
    analyst._client = MagicMock()
    analyst._client.messages.create = fake_create
    analyst._enabled = True
    analyst._model = "claude-haiku-4-5"

    analyst._call(system="test system", prompt="test prompt", max_tokens=128)

    system = captured.get("system")
    assert isinstance(system, list)
    assert system[0].get("cache_control") == {"type": "ephemeral"}
    assert system[0]["text"] == "test system"
