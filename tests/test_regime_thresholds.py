"""Tests for volatility-conditional entry thresholds (DeepThinkAgent._regime_thresholds).

Pure logic — no network/agent. Guards the high-vol edge bump that was documented
(VIX>25 → require 3/3 edges, "tighter in panic") but silently unimplemented until
2026-06-06: the old inline block only raised min_conviction and never touched the
edge count, so regime_min_edges stayed at the base value in every regime.
"""
from __future__ import annotations

from agents.deepthink_agent import DeepThinkAgent


def test_low_vol_relaxes_conviction_not_edges():
    conv, edges, label = DeepThinkAgent._regime_thresholds(12.0, 7.0, 2)
    assert conv == 6.5          # base 7.0 - 0.5
    assert edges == 2           # calm markets do not change the edge count
    assert label == "low-vol"


def test_high_vol_tightens_both():
    conv, edges, label = DeepThinkAgent._regime_thresholds(30.0, 7.0, 2)
    assert conv == 8.0          # base 7.0 + 1.0
    assert edges == 3           # the fix: panic demands 3/3 edges
    assert label == "high-vol"


def test_high_vol_edges_capped_at_3():
    # never require more than 3/3 even if the base is already 3
    _, edges, _ = DeepThinkAgent._regime_thresholds(40.0, 7.0, 3)
    assert edges == 3


def test_normal_vol_unchanged():
    assert DeepThinkAgent._regime_thresholds(18.0, 7.0, 2) == (7.0, 2, "normal")


def test_missing_vix_is_unknown_and_unchanged():
    assert DeepThinkAgent._regime_thresholds(0, 7.0, 2) == (7.0, 2, "unknown")


def test_conviction_relax_floored_at_1():
    conv, _, _ = DeepThinkAgent._regime_thresholds(10.0, 1.0, 2)
    assert conv == 1.0          # max(1.0, 1.0 - 0.5)


def test_conviction_bump_capped_at_10():
    conv, _, _ = DeepThinkAgent._regime_thresholds(30.0, 9.5, 2)
    assert conv == 10.0         # min(10.0, 9.5 + 1.0)
