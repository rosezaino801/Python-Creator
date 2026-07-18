"""
Entry point for Render Web Service deployments.

Render requires a process to bind to $PORT within ~2 minutes or it
kills the deployment as "timed out". A Telegram polling bot never
opens a port, so we satisfy Render by running a tiny health-check
HTTP server on $PORT in a background daemon thread, then start the
bot's blocking polling loop on the main thread.

Start command on Render:  python main.py
"""

import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# ── Health-check server ───────────────────────────────────────────────────────

class _HealthHandler(BaseHTTPRequestHandler):
    """Returns 200 OK for any GET — satisfies Render's health check."""

    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, *_):  # silence default request logging
        pass


def _start_health_server():
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    print(f"[main] Health-check server listening on port {port}", flush=True)
    server.serve_forever()


# ── Bot startup ───────────────────────────────────────────────────────────────

# Make telegram-bot/ importable without a package __init__
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "telegram-bot"))

from bot import main as bot_main  # noqa: E402

if __name__ == "__main__":
    # 1. Bind to PORT immediately so Render doesn't time out
    health_thread = threading.Thread(target=_start_health_server, daemon=True)
    health_thread.start()

    # 2. Run the bot — blocks forever (polling loop)
    bot_main()
