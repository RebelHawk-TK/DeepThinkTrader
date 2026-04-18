"""Logging setup — opt-in JSON format via LOG_FORMAT=json.

Call `configure_logging()` once at startup. Default is plain-text (current
behavior); `LOG_FORMAT=json` emits one-line JSON for `jq`/`lnav`/log
aggregation. Optional LOG_LEVEL overrides the level.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys


class JsonFormatter(logging.Formatter):
    """Single-line JSON per log record — stable field set.

    Extras attached via `logger.info("x", extra={"ticker": "NVDA"})` are
    merged into the top-level JSON object so they're directly queryable.
    """

    RESERVED = {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "message", "module",
        "msecs", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName",
        "taskName",  # Python 3.12+
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in self.RESERVED or key.startswith("_"):
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(log_file: str | None = None) -> None:
    """Wire up handlers + format. Idempotent — safe to call repeatedly."""
    fmt_env = os.getenv("LOG_FORMAT", "plain").lower()
    level_env = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_env, logging.INFO)

    root = logging.getLogger()
    # Clear prior handlers so repeated configure() calls don't double-emit.
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(level)

    if fmt_env == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
        )

    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(formatter)
    root.addHandler(stdout)

    if log_file:
        file_h = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5,
        )
        file_h.setFormatter(formatter)
        root.addHandler(file_h)
        try:
            os.chmod(log_file, 0o600)
        except OSError:
            pass
