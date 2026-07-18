# Muhammed Fashion Store — Telegram Shopping Bot

A Telegram bot for a Nigerian fashion store. Customers can browse products by category, view a photo carousel, place orders via a guided checkout flow, and ask AI-powered questions. Admins get order notifications and can manage the product catalog through an in-bot admin panel.

## Run & Operate

- **Workflow:** `Telegram Bot` → runs `python main.py`
- The bot uses long-polling (no webhook needed). Start the workflow to bring it online.
- `main.py` also starts a health-check HTTP server on `$PORT` (default 8080) for Render compatibility.

## Required Secrets

| Secret | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from @BotFather |
| `GEMINI_API_KEY` | Google Gemini AI for answering customer questions |
| `ADMIN_CHAT_ID` | *(optional)* Your numeric Telegram user ID — enables admin panel and order alerts |

> Use `/myid` in the bot to get your Telegram numeric ID for `ADMIN_CHAT_ID`.

## Stack

- Python 3.11
- `python-telegram-bot` v22.8 (polling mode)
- `google-genai` v2.12.1 (Gemini AI)
- Product catalog: `telegram-bot/products.json` (hot-reloaded on every admin change)
- Orders: `telegram-bot/orders.json` (append-only)

## Where Things Live

- `telegram-bot/bot.py` — all bot logic (customer UI, order flow, admin panel)
- `telegram-bot/products.json` — product catalog (categories + products with images)
- `telegram-bot/orders.json` — saved orders (created at runtime)
- `main.py` — entry point; starts health server then runs the bot

## Architecture Decisions

- Products are stored in a local JSON file and hot-reloaded on every catalog change — no database required.
- Orders are appended to a local JSON file. For production, consider a database or cloud storage.
- Gemini AI is initialised from `GEMINI_API_KEY`; if both `GOOGLE_API_KEY` and `GEMINI_API_KEY` are set, `GOOGLE_API_KEY` takes precedence (google-genai library behaviour).
- The health-check HTTP server runs in a daemon thread so it never blocks the bot's polling loop.

## User Preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- The library reads `GEMINI_API_KEY` by name — **not** `GOOGLE_API_KEY`. Set `GEMINI_API_KEY` in Secrets.
- `ADMIN_CHAT_ID` is optional but strongly recommended; without it, the admin panel and all order alerts are silently disabled.
- To get your chat ID, message the bot `/myid`.
