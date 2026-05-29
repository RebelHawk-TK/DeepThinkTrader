"""Tests for the P1 require-fundamental-edge gate (DeepThinkAgent._fundamental_gate).

Pure logic — no network, no construction of the agent. Verifies a long BUY is
blocked without a passing fundamental edge, shorts are never gated, and the
flag toggles the behaviour.
"""
from __future__ import annotations

from agents.deepthink_agent import DeepThinkAgent

F_PASS = {"label": "Fundamental", "passed": True}
F_FAIL = {"label": "Fundamental", "passed": False}
T_PASS = {"label": "Technical", "passed": True}
S_PASS = {"label": "Sentiment", "passed": True}


def test_blocks_buy_without_fundamental():
    # T+S combo (the toxic one) on a long -> blocked
    assert DeepThinkAgent._fundamental_gate("BUY", [T_PASS, S_PASS], enabled=True) is True


def test_blocks_buy_with_failing_fundamental():
    assert DeepThinkAgent._fundamental_gate("BUY", [F_FAIL, T_PASS, S_PASS], enabled=True) is True


def test_allows_buy_with_fundamental():
    assert DeepThinkAgent._fundamental_gate("BUY", [F_PASS, S_PASS], enabled=True) is False


def test_never_gates_shorts():
    # good fundamentals are the wrong sign for a short, so SELL is never blocked here
    assert DeepThinkAgent._fundamental_gate("SELL", [T_PASS, S_PASS], enabled=True) is False


def test_never_gates_hold():
    assert DeepThinkAgent._fundamental_gate("HOLD", [], enabled=True) is False


def test_flag_off_passes_through():
    assert DeepThinkAgent._fundamental_gate("BUY", [T_PASS, S_PASS], enabled=False) is False
