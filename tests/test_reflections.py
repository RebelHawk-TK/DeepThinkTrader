"""Reflection memory tests — DB round-trip, retrieval, writer."""
from __future__ import annotations

from unittest.mock import MagicMock

from agents.reflection_writer import ReflectionWriter, format_reflections_for_prompt


# ─────────────────────────── DB layer ────────────────────────────────────


def test_save_and_retrieve_reflection(db):
    # Need a real trade for FK integrity.
    tid = db.save_trade({
        "ticker": "NVDA", "action": "BUY", "quantity": 10, "entry_price": 900.0,
        "stop_loss_price": 855.0, "take_profit_price": 990.0, "conviction": 8.0,
        "order_id": "ord1",
    })
    rid = db.save_reflection(
        trade_id=tid, ticker="NVDA", thesis="momentum + earnings beat",
        outcome_pnl=150.0, lesson="RSI >75 on entry was a warning; wait for pullback next time.",
    )
    assert rid > 0

    rows = db.get_reflections(ticker="NVDA", limit=5)
    assert len(rows) == 1
    assert rows[0]["outcome_label"] == "win"
    assert rows[0]["lesson"].startswith("RSI >75")


def test_retrieve_scoped_to_ticker_first(db):
    # Two tickers, both with reflections. Asking for NVDA should surface the
    # NVDA one first, then backfill with global recent (here: the AAPL one).
    for t in ("NVDA", "AAPL"):
        tid = db.save_trade({
            "ticker": t, "action": "BUY", "quantity": 10, "entry_price": 100.0,
            "stop_loss_price": 95.0, "take_profit_price": 110.0, "conviction": 7.0,
            "order_id": f"o-{t}",
        })
        db.save_reflection(
            trade_id=tid, ticker=t, thesis="test",
            outcome_pnl=10.0 if t == "NVDA" else -5.0,
            lesson=f"{t} lesson",
        )

    rows = db.get_reflections(ticker="NVDA", limit=5)
    assert len(rows) == 2
    assert rows[0]["ticker"] == "NVDA"  # scoped first
    assert rows[1]["ticker"] == "AAPL"  # global backfill


def test_retrieve_limit_caps_results(db):
    tid = db.save_trade({
        "ticker": "NVDA", "action": "BUY", "quantity": 10, "entry_price": 100.0,
        "stop_loss_price": 95.0, "take_profit_price": 110.0, "conviction": 7.0,
        "order_id": "o1",
    })
    for i in range(10):
        db.save_reflection(tid, "NVDA", "t", 1.0, f"lesson {i}")
    assert len(db.get_reflections(ticker="NVDA", limit=3)) == 3


# ─────────────────────────── Writer ──────────────────────────────────────


def test_writer_saves_via_claude_when_available(db):
    writer = ReflectionWriter.__new__(ReflectionWriter)
    writer.db = db
    writer.config = MagicMock(CLAUDE_MODEL="claude-haiku-4-5")
    # Stub the Claude client.
    fake_msg = MagicMock()
    fake_msg.content = [MagicMock(text="Entering at RSI 78 is the mistake to avoid.")]
    writer._client = MagicMock()
    writer._client.messages.create.return_value = fake_msg

    tid = db.save_trade({
        "ticker": "NVDA", "action": "BUY", "quantity": 10, "entry_price": 900.0,
        "stop_loss_price": 855.0, "take_profit_price": 990.0, "conviction": 8.0,
        "order_id": "ord-w",
    })
    rid = writer.on_trade_closed(
        trade_id=tid, ticker="NVDA",
        thesis="momentum crossover with earnings tailwind",
        outcome_pnl=-200.0, outcome_context="stop_loss after earnings miss",
    )
    assert rid is not None
    rows = db.get_reflections(ticker="NVDA", limit=1)
    assert "RSI 78" in rows[0]["lesson"]

    # Verify cache_control was passed through.
    call = writer._client.messages.create.call_args
    system = call.kwargs["system"]
    assert system[0]["cache_control"] == {"type": "ephemeral"}


def test_writer_falls_back_when_client_missing(db):
    writer = ReflectionWriter.__new__(ReflectionWriter)
    writer.db = db
    writer.config = MagicMock()
    writer._client = None  # API key missing

    tid = db.save_trade({
        "ticker": "NVDA", "action": "BUY", "quantity": 10, "entry_price": 100.0,
        "stop_loss_price": 95.0, "take_profit_price": 110.0, "conviction": 7.0,
        "order_id": "o-f",
    })
    rid = writer.on_trade_closed(
        trade_id=tid, ticker="NVDA", thesis="test thesis",
        outcome_pnl=50.0, outcome_context="take_profit",
    )
    assert rid is not None
    rows = db.get_reflections(ticker="NVDA", limit=1)
    assert "NVDA win" in rows[0]["lesson"]
    assert "take_profit" in rows[0]["lesson"]


def test_writer_swallows_claude_errors(db):
    writer = ReflectionWriter.__new__(ReflectionWriter)
    writer.db = db
    writer.config = MagicMock()
    writer._client = MagicMock()
    writer._client.messages.create.side_effect = RuntimeError("API down")

    tid = db.save_trade({
        "ticker": "NVDA", "action": "BUY", "quantity": 10, "entry_price": 100.0,
        "stop_loss_price": 95.0, "take_profit_price": 110.0, "conviction": 7.0,
        "order_id": "o-e",
    })
    # Even if Claude raises, fallback must produce a lesson and save it.
    rid = writer.on_trade_closed(tid, "NVDA", "thesis", 10.0, "ctx")
    assert rid is not None


# ─────────────────────────── Prompt formatter ────────────────────────────


def test_format_reflections_empty_returns_empty_string():
    assert format_reflections_for_prompt([]) == ""


def test_format_reflections_renders_lines():
    out = format_reflections_for_prompt([
        {"created_at": "2026-04-10T09:00:00", "ticker": "NVDA",
         "outcome_label": "loss", "lesson": "avoid entering at RSI 78"},
        {"created_at": "2026-04-11T09:00:00", "ticker": "AAPL",
         "outcome_label": "win", "lesson": "earnings-day entry worked"},
    ])
    assert "NVDA loss" in out
    assert "AAPL win" in out
    assert "2026-04-10" in out
