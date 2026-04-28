"""Notifications — Sends trade alerts and system events via Slack webhooks.

Fire-and-forget design: notification failures never block trading.
Rate-limited per event type to prevent spam during cascading failures.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from urllib.request import Request, urlopen

from config import Config

logger = logging.getLogger(__name__)

# Rate limit: max 1 notification per event type per 5 minutes
_RATE_LIMIT_SECONDS = 300
_last_sent: dict[str, float] = {}


def _is_rate_limited(event_type: str) -> bool:
    last = _last_sent.get(event_type, 0)
    return (time.time() - last) < _RATE_LIMIT_SECONDS


def _mark_sent(event_type: str) -> None:
    _last_sent[event_type] = time.time()


_ALLOWED_SLACK_HOSTS = {"hooks.slack.com", "hooks.enterprise.slack.com"}


def _post_slack(webhook_url: str, text: str, blocks: list[dict] | None = None) -> None:
    """POST to Slack webhook in a background thread. Never blocks the caller.

    Validates the URL host to prevent SSRF in case the webhook URL ever comes
    from an untrusted source (DB, API, env override).
    """
    from urllib.parse import urlparse
    parsed = urlparse(webhook_url)
    if parsed.scheme != "https" or parsed.hostname not in _ALLOWED_SLACK_HOSTS:
        logger.warning(
            f"Refusing Slack POST to non-Slack URL: scheme={parsed.scheme} "
            f"host={parsed.hostname}"
        )
        return
    payload: dict = {"text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        data = json.dumps(payload).encode("utf-8")
        req = Request(webhook_url, data=data, headers={"Content-Type": "application/json"})
        urlopen(req, timeout=10)
    except Exception as e:
        logger.debug(f"Slack notification failed: {e}")


def _send(event_type: str, text: str, blocks: list[dict] | None = None) -> None:
    config = Config()
    if not config.NOTIFICATIONS_ENABLED or not config.SLACK_WEBHOOK_URL:
        return
    if _is_rate_limited(event_type):
        return
    _mark_sent(event_type)
    thread = threading.Thread(
        target=_post_slack,
        args=(config.SLACK_WEBHOOK_URL, text, blocks),
        daemon=True,
    )
    thread.start()


# ── Public API ─────────────────────────────────────────────────────


def notify_trade_executed(
    ticker: str,
    action: str,
    shares: int,
    price: float,
    conviction: float,
    reasoning: str = "",
) -> None:
    text = f"Trade Executed: {action} {shares}x {ticker} @ ${price:.2f} (conviction {conviction}/10)"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{action} {ticker}"}},
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Shares:* {shares}"},
                {"type": "mrkdwn", "text": f"*Price:* ${price:.2f}"},
                {"type": "mrkdwn", "text": f"*Conviction:* {conviction}/10"},
                {"type": "mrkdwn", "text": f"*Action:* {action}"},
            ],
        },
    ]
    if reasoning:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Reasoning:* {reasoning[:500]}"},
        })
    _send("TRADE_EXECUTED", text, blocks)


def notify_trade_exited(
    ticker: str,
    reason: str,
    pnl: float,
    partial: bool = False,
) -> None:
    exit_type = "Partial Exit" if partial else "Position Closed"
    emoji = "+" if pnl >= 0 else ""
    text = f"{exit_type}: {ticker} — {reason} | P&L: {emoji}${pnl:.2f}"
    _send("TRADE_EXITED", text)


def notify_strategy_paused(portfolio: str, win_rate_delta: float) -> None:
    text = (
        f"Strategy PAUSED [{portfolio}]: Win rate dropped "
        f"{abs(win_rate_delta)*100:.0f}% from baseline. "
        "New trades halted. Exit monitoring continues."
    )
    _send("STRATEGY_PAUSED", text)


def notify_strategy_resumed(portfolio: str, win_rate_delta: float) -> None:
    text = (
        f"Strategy RESUMED [{portfolio}]: Win rate delta recovered to "
        f"{win_rate_delta*100:+.0f}%. Trading re-enabled."
    )
    _send("STRATEGY_RESUMED", text)


def notify_circuit_breaker(reason: str) -> None:
    text = f"Circuit Breaker Triggered: {reason}. New long positions blocked."
    _send("CIRCUIT_BREAKER", text)


def notify_daily_loss_limit(loss_pct: float, limit_pct: float) -> None:
    text = (
        f"Daily Loss Limit Hit: {loss_pct*100:.1f}% loss "
        f"(limit: {limit_pct*100:.1f}%). Trading halted for today."
    )
    _send("DAILY_LOSS_LIMIT", text)


def notify_system_event(message: str) -> None:
    _send("SYSTEM_EVENT", f"DeepThinkTrader: {message}")
