"""Regression tests for the 2026-05-29 P0 correctness/safety fixes.

Covers: re-enabled risk gates (config-flag gated), and the ETF/fund guard in
YahooFundamentals that previously handed funds a free fundamental edge.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from config import Config


def test_safety_gate_flags_exist_and_default_on():
    assert Config.RISK_OF_RUIN_ENABLED is True
    assert Config.REVENGE_GUARD_ENABLED is True


def test_risk_of_ruin_bypass_when_disabled(risk_manager, monkeypatch):
    # Disabled flag → permissive without touching the db.
    monkeypatch.setattr(risk_manager.config, "RISK_OF_RUIN_ENABLED", False)
    assert risk_manager.check_risk_of_ruin(account_value=100_000) is True


def test_revenge_guard_bypass_when_disabled(risk_manager, monkeypatch):
    monkeypatch.setattr(risk_manager.config, "REVENGE_GUARD_ENABLED", False)
    assert risk_manager.is_revenge_trading() is False


def test_revenge_guard_enabled_no_flag_when_few_trades(risk_manager, monkeypatch):
    # Enabled + fresh db (<3 recent trades) → not revenge trading.
    monkeypatch.setattr(risk_manager.config, "REVENGE_GUARD_ENABLED", True)
    assert risk_manager.is_revenge_trading() is False


def test_etf_does_not_pass_fundamental_edge(monkeypatch):
    from utils import yahoo_fundamentals as yf_mod

    monkeypatch.setattr(yf_mod, "yf", MagicMock())
    monkeypatch.setattr(
        yf_mod, "_yf_with_timeout", lambda fn, default=None: {"quoteType": "ETF"}
    )
    res = yf_mod.YahooFundamentals().evaluate_fundamental_edge("VGSH")
    assert res["passed"] is False
    assert res["strength"] == 0


def test_etf_skips_equity_only_sections_in_get_fundamentals(monkeypatch):
    from utils import yahoo_fundamentals as yf_mod

    monkeypatch.setattr(yf_mod, "yf", MagicMock())
    monkeypatch.setattr(
        yf_mod, "_yf_with_timeout",
        lambda fn, default=None: {"quoteType": "ETF", "marketCap": None},
    )
    res = yf_mod.YahooFundamentals().get_fundamentals("VGSH")
    assert res.get("is_fund") is True
    assert "analyst" not in res  # equity-only section skipped (no 404 storm)


def test_equity_still_evaluated_in_get_fundamentals(monkeypatch):
    # Sanity: a normal equity is NOT short-circuited by the ETF guard.
    from utils import yahoo_fundamentals as yf_mod

    monkeypatch.setattr(yf_mod, "yf", MagicMock())
    monkeypatch.setattr(
        yf_mod, "_yf_with_timeout",
        lambda fn, default=None: {"quoteType": "EQUITY", "marketCap": 1_000},
    )
    res = yf_mod.YahooFundamentals().get_fundamentals("AAPL")
    assert res.get("is_fund") is not True
    assert "analyst" in res
