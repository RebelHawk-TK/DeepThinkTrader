"""Structured logger for Anthropic API calls.

Appends one JSON line per call to logs/llm_calls.jsonl. Captures full
prompt + response + token usage so the data can later be used for
LoRA fine-tuning, cost analysis, or replay-based backtesting.

Designed to never break the bot — all writes are wrapped in try/except.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
_LOG_PATH = _LOG_DIR / "llm_calls.jsonl"


def _extract_usage(response: Any) -> dict:
    """Extract token usage from an Anthropic Message response."""
    try:
        usage = response.usage
        return {
            "input": getattr(usage, "input_tokens", 0),
            "output": getattr(usage, "output_tokens", 0),
            "cache_read": getattr(usage, "cache_read_input_tokens", 0) or 0,
            "cache_creation": getattr(usage, "cache_creation_input_tokens", 0) or 0,
        }
    except Exception:
        return {}


def _extract_text(response: Any) -> str:
    try:
        return response.content[0].text
    except Exception:
        return ""


def log_call(
    *,
    source: str,
    model: str,
    system: str,
    prompt: str,
    response: Any | None,
    latency_ms: int,
    error: str | None = None,
) -> None:
    """Append one record to the LLM call log. Never raises."""
    import os as _os
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "model": model,
            "latency_ms": latency_ms,
            "system": system,
            "prompt": prompt,
            "response": _extract_text(response) if response is not None else "",
            "tokens": _extract_usage(response) if response is not None else {},
            "stop_reason": getattr(response, "stop_reason", None) if response is not None else None,
            "error": error,
        }
        is_new = not _LOG_PATH.exists()
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        if is_new:
            _os.chmod(_LOG_PATH, 0o600)
    except Exception as e:
        logger.debug(f"llm_logger write failed: {e}")
