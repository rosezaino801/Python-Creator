"""
Render entry point for Muhammed Fashion Store Telegram bot.

Architecture
------------
Render kills any web-service process that doesn't bind $PORT within 60 s.
We solve that here by running a minimal asyncio HTTP health-check server
(GET / → 200 OK) in the SAME event loop as the Telegram bot, so there is
no threading complexity and no risk of the health server surviving a dead bot.

Start-up sequence
-----------------
1. asyncio.run(main()) creates one event loop.
2. _serve_health() starts an asyncio TCP server on $PORT — Render's health
   check immediately sees the port bound.
3. _run_bot() builds the Application, explicitly deletes any stale Telegram
   webhook (a registered webhook prevents getUpdates from ever returning
   messages), then starts the polling loop.
4. Both coroutines run concurrently inside the same event loop via
   asyncio.gather().  If either crashes the whole process exits, which
   causes Render to restart — the correct behaviour.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

# ── Make telegram-bot/ importable ────────────────────────────────────────────
BOT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "telegram-bot")
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

# ── Logging (configure before any other import so bot.py inherits it) ─────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

from bot import build_app          # noqa: E402  (must come after sys.path tweak)
from telegram import Update        # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# ── Async health-check server ─────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

async def _health_handler(
    reader: asyncio.StreamReader, writer: asyncio.StreamWriter
) -> None:
    """Minimal HTTP/1.1 handler: any request → 200 OK."""
    try:
        await reader.read(1024)           # drain the request bytes
        response = (
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain\r\n"
            b"Content-Length: 2\r\n"
            b"Connection: close\r\n"
            b"\r\n"
            b"OK"
        )
        writer.write(response)
        await writer.drain()
    finally:
        writer.close()


async def _serve_health(port: int) -> None:
    """Start the health-check TCP server and keep it running forever."""
    server = await asyncio.start_server(_health_handler, "0.0.0.0", port)
    addr = server.sockets[0].getsockname()
    logger.info("[health] Listening on %s:%d", addr[0], addr[1])
    async with server:
        await server.serve_forever()


# ─────────────────────────────────────────────────────────────────────────────
# ── Bot polling ───────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

async def _run_bot(stop_event: asyncio.Event) -> None:
    """Build the Application, clear any stale webhook, start polling."""
    app = build_app()

    async with app:
        # ── Delete any registered webhook before polling ───────────────────
        # If a webhook URL is set on this token, Telegram silently routes all
        # updates there and getUpdates returns nothing — the bot appears dead
        # even though the process is running.  Deleting the webhook here
        # guarantees we own the update stream.
        wh_info = await app.bot.get_webhook_info()
        if wh_info.url:
            logger.warning(
                "[bot] Stale webhook detected (%s) — deleting it now.", wh_info.url
            )
        await app.bot.delete_webhook(drop_pending_updates=True)
        logger.info("[bot] Webhook cleared. Starting polling...")

        await app.start()

        await app.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
        )
        logger.info("[bot] Polling active — bot is online.")

        # Wait until a shutdown signal arrives
        await stop_event.wait()

        logger.info("[bot] Shutdown signal received — stopping gracefully.")
        await app.updater.stop()
        await app.stop()


# ─────────────────────────────────────────────────────────────────────────────
# ── Entry point ───────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

async def _main() -> None:
    port = int(os.environ.get("PORT", 8080))
    stop_event = asyncio.Event()

    # Register OS-level shutdown signals so SIGTERM from Render triggers a
    # clean shutdown rather than an abrupt kill.
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):
            # Windows doesn't support add_signal_handler; safe to ignore.
            pass

    logger.info("[main] Starting — health port %d", port)

    # Run health server and bot concurrently.
    # asyncio.gather() propagates the first exception and cancels the rest,
    # so a crash in either task kills the whole process — Render restarts it.
    await asyncio.gather(
        _serve_health(port),
        _run_bot(stop_event),
    )


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("[main] Process exiting.")
