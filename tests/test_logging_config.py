"""Logging configuration tests — plain vs JSON format."""
from __future__ import annotations

import io
import json
import logging

from utils.logging_config import configure_logging


def _capture_log(monkeypatch, log_format: str) -> io.StringIO:
    """Configure logging with the given format env and return the stream."""
    monkeypatch.setenv("LOG_FORMAT", log_format)
    buf = io.StringIO()
    configure_logging()  # sets up a stdout handler
    # Redirect the freshly-added stdout handler to our buffer.
    root = logging.getLogger()
    root.handlers[0].stream = buf
    return buf


def test_plain_format_is_default(monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    buf = _capture_log(monkeypatch, "plain")
    logging.getLogger("test").info("hello world")
    out = buf.getvalue()
    assert "hello world" in out
    # Plain format has bracketed level.
    assert "[INFO]" in out


def test_json_format_emits_parseable_json(monkeypatch):
    buf = _capture_log(monkeypatch, "json")
    logging.getLogger("test").info("hello")
    out = buf.getvalue().strip()
    record = json.loads(out)
    assert record["msg"] == "hello"
    assert record["level"] == "INFO"
    assert record["logger"] == "test"
    assert "ts" in record


def test_json_format_includes_extras(monkeypatch):
    buf = _capture_log(monkeypatch, "json")
    logging.getLogger("trading").info(
        "exit", extra={"ticker": "NVDA", "pnl": 150.5, "reason": "take_profit"}
    )
    out = buf.getvalue().strip()
    record = json.loads(out)
    assert record["ticker"] == "NVDA"
    assert record["pnl"] == 150.5
    assert record["reason"] == "take_profit"


def test_json_format_handles_unserializable_extras(monkeypatch):
    buf = _capture_log(monkeypatch, "json")

    class NotJSON:
        def __repr__(self) -> str:
            return "<NotJSON>"

    logging.getLogger("test").info("msg", extra={"obj": NotJSON()})
    record = json.loads(buf.getvalue().strip())
    assert record["obj"] == "<NotJSON>"


def test_configure_is_idempotent(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "plain")
    configure_logging()
    configure_logging()
    configure_logging()
    # Should have one stdout handler, not three stacked.
    stdout_handlers = [
        h for h in logging.getLogger().handlers
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
    ]
    assert len(stdout_handlers) == 1


def test_log_level_env_respected(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "plain")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    configure_logging()
    assert logging.getLogger().level == logging.WARNING
