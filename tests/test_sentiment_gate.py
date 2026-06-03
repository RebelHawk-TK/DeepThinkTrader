"""Tests for the penny require-sentiment-edge gate (DeepThinkAgent._sentiment_gate).

Pure logic — no network, no agent construction. Mirrors test_fundamental_gate:
a long BUY is blocked without a passing sentiment edge, shorts/holds are never
gated, and the flag toggles the behaviour.
"""
from __future__ import annotations

from agents.deepthink_agent import DeepThinkAgent

F_PASS = {"label": "Fundamental", "passed": True}
T_PASS = {"label": "Technical", "passed": True}
S_PASS = {"label": "Sentiment", "passed": True}
S_FAIL = {"label": "Sentiment", "passed": False}


def test_blocks_buy_without_sentiment():
    # F+T combo (penny-toxic, PF 0.02) on a long -> blocked
    assert DeepThinkAgent._sentiment_gate("BUY", [F_PASS, T_PASS], enabled=True) is True


def test_blocks_buy_with_failing_sentiment():
    assert DeepThinkAgent._sentiment_gate("BUY", [F_PASS, T_PASS, S_FAIL], enabled=True) is True


def test_allows_buy_with_sentiment():
    # T+S (penny PF 1.56) and other S-containing combos pass
    assert DeepThinkAgent._sentiment_gate("BUY", [T_PASS, S_PASS], enabled=True) is False


def test_never_gates_shorts():
    # good sentiment is a long signal, so SELL is never blocked here
    assert DeepThinkAgent._sentiment_gate("SELL", [F_PASS, T_PASS], enabled=True) is False


def test_never_gates_hold():
    assert DeepThinkAgent._sentiment_gate("HOLD", [], enabled=True) is False


def test_flag_off_passes_through():
    assert DeepThinkAgent._sentiment_gate("BUY", [F_PASS, T_PASS], enabled=False) is False
