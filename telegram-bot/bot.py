"""
Telegram Customer Support Bot
================================
Uses python-telegram-bot v20+ and the Google Gemini SDK (google-genai).

- Inline keyboard: Products, Prices, Contact Support, About Us.
- Any free-text message that is not a command or button press is sent to
  Google Gemini and the AI reply is returned to the user.
"""

import logging
import os

from google import genai
from google.genai import types as genai_types
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gemini client
# ---------------------------------------------------------------------------
# genai.Client() automatically picks up GEMINI_API_KEY from the environment.
gemini_client = genai.Client()

# Model — gemini-3.1-flash-lite is fast and available on this API key.
GEMINI_MODEL = "gemini-3.1-flash-lite"

# System prompt that shapes the AI's persona inside this support bot.
SYSTEM_PROMPT = (
    "You are a friendly and helpful customer support assistant for our business. "
    "Answer questions clearly and concisely. "
    "If you don't know something, say so honestly and suggest the user contact "
    "the support team at support@example.com."
)

# ---------------------------------------------------------------------------
# Inline keyboard layout
# ---------------------------------------------------------------------------
MAIN_KEYBOARD = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("🛍️ Products", callback_data="products"),
            InlineKeyboardButton("💰 Prices",   callback_data="prices"),
        ],
        [
            InlineKeyboardButton("🎧 Contact Support", callback_data="contact_support"),
            InlineKeyboardButton("ℹ️ About Us",        callback_data="about_us"),
        ],
    ]
)

# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start — Welcome message with inline keyboard."""
    user = update.effective_user
    first_name = user.first_name if user else "there"

    welcome_text = (
        f"👋 Hello, {first_name}! Welcome to our Customer Support bot.\n\n"
        "I'm here to help you with:\n"
        "• Product information\n"
        "• Pricing details\n"
        "• Getting in touch with our support team\n"
        "• Learning more about us\n\n"
        "Tap a button below, or just type your question and I'll answer it 💬"
    )
    await update.message.reply_text(welcome_text, reply_markup=MAIN_KEYBOARD)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help — Command reference with inline menu."""
    help_text = (
        "🆘 *Help Menu*\n\n"
        "Use the inline buttons below or type one of these commands:\n\n"
        "/start — Restart the bot and show the main menu\n"
        "/help  — Show this help message\n\n"
        "*Menu options:*\n"
        "🛍️ *Products* — Browse our product catalogue\n"
        "💰 *Prices*   — View our current pricing\n"
        "🎧 *Contact Support* — Reach a human agent\n"
        "ℹ️ *About Us* — Learn who we are\n\n"
        "Or just *type any question* and our AI assistant will help you! 🤖"
    )
    await update.message.reply_text(
        help_text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD
    )


# ---------------------------------------------------------------------------
# Inline button handlers
# ---------------------------------------------------------------------------

async def handle_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🛍️ Products button."""
    query = update.callback_query
    await query.answer()
    text = (
        "🛍️ *Our Products*\n\n"
        "Here's a quick overview of what we offer:\n\n"
        "• *Product A* — Premium quality, best-seller\n"
        "• *Product B* — Budget-friendly option\n"
        "• *Product C* — Limited edition, hurry!\n\n"
        "Want more details on a specific product? "
        "Tap 🎧 *Contact Support* and our team will help you out."
    )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)


async def handle_prices(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """💰 Prices button."""
    query = update.callback_query
    await query.answer()
    text = (
        "💰 *Pricing*\n\n"
        "Here are our current prices:\n\n"
        "• *Product A* — $49.99\n"
        "• *Product B* — $19.99\n"
        "• *Product C* — $79.99 *(limited edition)*\n\n"
        "All prices include VAT. Bulk discounts available — "
        "contact support for details."
    )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)


async def handle_contact_support(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """🎧 Contact Support button."""
    query = update.callback_query
    await query.answer()
    text = (
        "🎧 *Contact Support*\n\n"
        "Our team is ready to help you!\n\n"
        "📧 *Email:* support@example.com\n"
        "🕐 *Hours:* Mon–Fri, 9 AM – 6 PM (UTC)\n\n"
        "You can also leave your question here and a team member "
        "will follow up with you shortly. We typically respond within "
        "*2 business hours*."
    )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)


async def handle_about_us(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """ℹ️ About Us button."""
    query = update.callback_query
    await query.answer()
    text = (
        "ℹ️ *About Us*\n\n"
        "We're a passionate team dedicated to delivering high-quality "
        "products and exceptional customer service.\n\n"
        "🏢 Founded in 2020\n"
        "🌍 Serving customers worldwide\n"
        "⭐ 4.9 / 5 average customer rating\n\n"
        "Follow us online:\n"
        "• 🐦 Twitter: @example\n"
        "• 📘 Facebook: /example\n"
        "• 📸 Instagram: @example"
    )
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)


# ---------------------------------------------------------------------------
# Gemini AI fallback handler
# ---------------------------------------------------------------------------

async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Catches any text that is not a command or button press, sends it to
    Google Gemini, and replies with the AI's response.
    """
    user_text = update.message.text

    # Show typing indicator while waiting for Gemini.
    await update.message.chat.send_action("typing")

    try:
        response = await gemini_client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_text,
            config=genai_types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=1024,
            ),
        )
        ai_reply = response.text.strip()
        logger.info("Gemini replied (%d chars) to: %.60s", len(ai_reply), user_text)

    except Exception as exc:
        # Log the full error so it appears in the workflow console.
        logger.error("Gemini error: %s", exc)
        ai_reply = (
            "⚠️ The AI couldn't respond right now. Please try again in a moment, "
            "or tap a button below for quick help."
        )

    await update.message.reply_text(ai_reply, reply_markup=MAIN_KEYBOARD)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Validate env vars, register handlers, and start polling."""

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Add it in Replit Secrets.")

    if not os.environ.get("GEMINI_API_KEY"):
        raise RuntimeError("GEMINI_API_KEY is not set. Add it in Replit Secrets.")

    app = Application.builder().token(token).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    # Inline buttons (matched by callback_data)
    app.add_handler(CallbackQueryHandler(handle_products,         pattern="^products$"))
    app.add_handler(CallbackQueryHandler(handle_prices,           pattern="^prices$"))
    app.add_handler(CallbackQueryHandler(handle_contact_support,  pattern="^contact_support$"))
    app.add_handler(CallbackQueryHandler(handle_about_us,         pattern="^about_us$"))

    # Gemini fallback — all non-command text messages
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_message))

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
