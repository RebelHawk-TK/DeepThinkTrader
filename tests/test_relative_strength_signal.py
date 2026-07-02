"""Tests for the validated MAIN relative_strength entry signal (2026-07-02 sleeve).

Pure logic on a research-report dict — no network/agent. Mirrors the validated rule
(backtest.signal_search 'relative_strength', bootstrap CI [1.57, 2.35, 3.46], n=443):
price within 10% of its 30-day high + volume_ratio > 1.5 + up on the day (longs only).
"""
from __future__ import annotations

from agents.deepthink_agent import DeepThinkAgent


def _report(price=100.0, high30=105.0, vol=2.0, chg=1.0):
    return {
        "technicals": {
            "current_price": price,
            "high_30d": high30,
            "volume_ratio": vol,
            "daily_change_pct": chg,
        },
    }


def test_fires_when_all_conditions_met():
    assert DeepThinkAgent._relative_strength_signal(_report()) is True


def test_fires_at_exactly_90pct_of_high():
    assert DeepThinkAgent._relative_strength_signal(_report(price=90.0, high30=100.0)) is True


def test_blocked_too_far_below_high():
    assert DeepThinkAgent._relative_strength_signal(_report(price=89.0, high30=100.0)) is False


def test_blocked_on_weak_volume():
    assert DeepThinkAgent._relative_strength_signal(_report(vol=1.5)) is False  # strict >1.5


def test_blocked_on_down_day():
    assert DeepThinkAgent._relative_strength_signal(_report(chg=-0.5)) is False


def test_blocked_on_flat_day():
    assert DeepThinkAgent._relative_strength_signal(_report(chg=0.0)) is False  # strict >0


def test_blocked_when_high30_missing():
    assert DeepThinkAgent._relative_strength_signal(_report(high30=0.0)) is False
    assert DeepThinkAgent._relative_strength_signal(_report(high30=None)) is False


def test_unparseable_fields_coerce_to_default():
    # mirrors signal_search._f fidelity: garbage coerces to 0.0 -> blocked
    assert DeepThinkAgent._relative_strength_signal(_report(vol="n/a")) is False


# ── Multi-signal MAIN_SIGNAL parsing (comma-separated sleeves) ───────────────


def _full_report(ticker="ABC", **tech):
    technicals = {
        "current_price": 100.0,
        "high_30d": 120.0,       # NOT within 10% -> relative_strength quiet
        "above_sma_10": False,   # -> momentum_breakout quiet
        "above_sma_20": True,
        "volume_ratio": 1.0,
        "daily_change_pct": 1.0,
        "rsi_14": 50,
    }
    technicals.update(tech)
    return {"ticker": ticker, "technicals": technicals}


def _agent(db, monkeypatch, signals):
    agent = DeepThinkAgent(user_id=1, db=db)
    monkeypatch.setattr(agent.config, "MAIN_SIGNAL", signals)
    monkeypatch.setattr(agent.config, "DEBATE_ENABLED", False)
    monkeypatch.setattr(agent.config, "CLAUDE_ANALYSIS_ENABLED", False)
    agent.debate_engine = None
    return agent


def test_analyze_multi_signal_fires_on_second_sleeve(db, monkeypatch):
    agent = _agent(db, monkeypatch, "momentum_breakout,relative_strength")
    # relative_strength conditions met, momentum_breakout not (below SMA-10)
    report = _full_report(current_price=118.0, volume_ratio=1.8)
    result = agent.analyze(report, portfolio="main")
    assert result["action"] == "BUY"
    # attribution names only the firing rule's description
    assert "relative_strength: within 10% of 30d-high" in result["reasoning_summary"]
    assert "momentum_breakout: >SMA10&20" not in result["reasoning_summary"]


def test_analyze_multi_signal_holds_when_none_fire(db, monkeypatch):
    agent = _agent(db, monkeypatch, "momentum_breakout,relative_strength")
    result = agent.analyze(_full_report(), portfolio="main")
    assert result["action"] == "HOLD"


def test_analyze_unknown_signal_name_is_ignored_not_conviction_fallback(db, monkeypatch, caplog):
    import logging
    agent = _agent(db, monkeypatch, "momentum_breakout,relative_strenth")  # typo
    with caplog.at_level(logging.ERROR):
        result = agent.analyze(_full_report(current_price=118.0, volume_ratio=1.8), portfolio="main")
    # typo'd name is reported, valid one still runs in signal mode (no silent
    # fallback to the retired conviction stack)
    assert "relative_strenth" in caplog.text
    assert result["action"] == "HOLD"  # momentum_breakout alone doesn't fire here
