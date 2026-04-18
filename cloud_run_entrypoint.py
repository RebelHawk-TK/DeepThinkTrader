#!/usr/bin/env python3
"""Cloud Run entrypoint for the trader bot.

Cloud Run Services require the container to bind to $PORT. The trader bot
is a long-running scheduler (not HTTP), so we run it in a daemon thread and
serve a trivial HTTP health endpoint on $PORT. The bot does its real work
(research → analysis → execution) on its own 15-minute timer; the HTTP
endpoint just keeps Cloud Run's startup / liveness probes happy.

Phase C (multi-tenant) may migrate this to Cloud Run Jobs + Cloud Scheduler
for a more cloud-native fit. For the Phase B single-user MVP, this wrapper
is the simplest lift.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("entrypoint")


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *_):  # silence access logs
        return


def _run_bot():
    """Run the bot's main entrypoint. Crashes here propagate out to kill the
    container, letting Cloud Run auto-restart."""
    try:
        import main as bot_main

        bot_main.main()
    except SystemExit:
        raise
    except Exception:  # pragma: no cover — container exit on crash
        log.exception("Bot thread crashed; exiting container")
        os._exit(1)


def main() -> int:
    port = int(os.environ.get("PORT", "8080"))

    bot_thread = threading.Thread(target=_run_bot, name="bot", daemon=True)
    bot_thread.start()
    log.info("Bot thread started; HTTP health on :%d", port)

    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
