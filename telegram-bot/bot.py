"""
Telegram Customer Support Bot
================================
A clean, well-commented bot using python-telegram-bot v20+.
It greets users, displays an inline keyboard, and handles each button via
CallbackQueryHandler so the menu stays embedded in the message.
"""

import logging
import os

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
# Inline keyboard layout
# ---------------------------------------------------------------------------
# Each InlineKeyboardButton needs a label (text) and a callback_data string
# that identifies which button was pressed.
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
    """
    /start — Entry point for every new user.
    Sends a friendly welcome message with the inline keyboard attached.
    """
    user = update.effective_user
    first_name = user.first_name if user else "there"

    welcome_text = (
        f"👋 Hello, {first_name}! Welcome to our Customer Support bot.\n\n"
        "I'm here to help you with:\n"
        "• Product information\n"
        "• Pricing details\n"
        "• Getting in touch with our support team\n"
        "• Learning more about us\n\n"
        "Tap a button below to get started 👇"
    )

    await update.message.reply_text(welcome_text, reply_markup=MAIN_KEYBOARD)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /help — Shows available commands and inline menu.
    """
    help_text = (
        "🆘 *Help Menu*\n\n"
        "Use the inline buttons below or type one of these commands:\n\n"
        "/start — Restart the bot and show the main menu\n"
        "/help  — Show this help message\n\n"
        "*Menu options:*\n"
        "🛍️ *Products* — Browse our product catalogue\n"
        "💰 *Prices*   — View our current pricing\n"
        "🎧 *Contact Support* — Reach a human agent\n"
        "ℹ️ *About Us* — Learn who we are\n"
    )

    await update.message.reply_text(
        help_text,
        parse_mode="Markdown",
        reply_markup=MAIN_KEYBOARD,
    )


# ---------------------------------------------------------------------------
# Callback query handlers (inline button presses)
# ---------------------------------------------------------------------------

async def handle_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Called when the user taps the 🛍️ Products inline button."""
    query = update.callback_query
    # Acknowledge the button press so Telegram stops showing a loading spinner.
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

    # Edit the original message so the inline keyboard stays visible.
    await query.edit_message_text(text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)


async def handle_prices(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Called when the user taps the 💰 Prices inline button."""
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
    """Called when the user taps the 🎧 Contact Support inline button."""
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
    """Called when the user taps the ℹ️ About Us inline button."""
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
# Fallback message handler
# ---------------------------------------------------------------------------

async def handle_unknown(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Fallback handler for any text message that isn't a command.
    Nudges the user back to the inline menu.
    """
    text = (
        "🤔 I didn't quite get that.\n\n"
        "Please use the buttons below, or type /help to see what I can do."
    )
    await update.message.reply_text(text, reply_markup=MAIN_KEYBOARD)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    """Build and start the bot."""

    # Read the token from the environment variable set in Replit Secrets.
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN environment variable is not set. "
            "Add it in the Replit Secrets panel."
        )

    # Build the Application (handles networking and dispatching).
    app = Application.builder().token(token).build()

    # --- Command handlers ---
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))

    # --- Inline button handlers ---
    # Each CallbackQueryHandler matches on the callback_data string set in
    # the InlineKeyboardButton above.
    app.add_handler(CallbackQueryHandler(handle_products,       pattern="^products$"))
    app.add_handler(CallbackQueryHandler(handle_prices,         pattern="^prices$"))
    app.add_handler(CallbackQueryHandler(handle_contact_support, pattern="^contact_support$"))
    app.add_handler(CallbackQueryHandler(handle_about_us,       pattern="^about_us$"))

    # --- Fallback: catch all other text messages ---
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unknown))

    logger.info("Bot is running. Press Ctrl+C to stop.")

    # Start polling Telegram for updates (blocks until interrupted).
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
