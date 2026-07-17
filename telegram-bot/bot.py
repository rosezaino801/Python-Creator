"""
Muhammed Fashion Store — Shopping Bot with Admin Panel
=======================================================
python-telegram-bot v20+  |  Google Gemini AI  |  products.json catalog

Customer flow
─────────────
  /start  → store banner + main menu (photo message, edited in-place)
  Browse Products → category grid → product carousel (◀ ▶)
  Buy Now → order instructions (new reply)
  Contact Us → contact details

Admin panel  (owner only, gated by ADMIN_CHAT_ID)
──────────────────────────────────────────────────
  /admin  → Admin Main Menu
    ├── 📦 Manage Products
    │     ├── ➕ Add Product    (category → name → description → price → photo)
    │     ├── ✏️ Edit Product   (category → product → field → new value/photo)
    │     └── 🗑️ Delete Product (category → product → confirm)
    └── 🏪 Store Settings      (name / Gmail / WhatsApp)

All changes are written to products.json and hot-reloaded into memory
immediately — customers see updates without any bot restart.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from google import genai
from google.genai import types as genai_types
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# ─────────────────────────────────────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Catalog — loaded from products.json; hot-reloadable
# ─────────────────────────────────────────────────────────────────────────────
PRODUCTS_FILE = Path(__file__).parent / "products.json"

# Module-level globals updated by reload_catalog()
STORE:   dict = {}
CATS:    list = []
CAT_MAP: dict = {}


def load_catalog() -> dict:
    with open(PRODUCTS_FILE, encoding="utf-8") as f:
        return json.load(f)


def reload_catalog() -> None:
    """Re-read products.json and refresh all in-memory catalog globals."""
    global STORE, CATS, CAT_MAP
    data    = load_catalog()
    STORE   = data["store"]
    CATS    = data["categories"]
    CAT_MAP = {c["id"]: c for c in CATS}
    logger.info(
        "Catalog reloaded: %d categories, %d products",
        len(CATS),
        sum(len(c["products"]) for c in CATS),
    )


def save_catalog() -> None:
    """Persist the current in-memory catalog to products.json, then reload."""
    data = {"store": STORE, "categories": CATS}
    with open(PRODUCTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    reload_catalog()
    logger.info("Catalog saved to %s", PRODUCTS_FILE)


# Initial load at startup
reload_catalog()

# ─────────────────────────────────────────────────────────────────────────────
# Gemini AI client
# ─────────────────────────────────────────────────────────────────────────────
gemini_client = genai.Client()
GEMINI_MODEL  = "gemini-3.1-flash-lite"


def build_system_prompt() -> str:
    return (
        f"You are a friendly shopping assistant for {STORE['name']}, "
        "a premium Nigerian fashion and lifestyle store. "
        "Help customers with product questions, sizing, availability, and delivery. "
        "Be concise and warm. "
        f"For orders, direct customers to {STORE.get('contact_email', 'our support team')} "
        f"or WhatsApp {STORE.get('contact_whatsapp', '')}."
    )

# ─────────────────────────────────────────────────────────────────────────────
# Admin config
# ─────────────────────────────────────────────────────────────────────────────
_raw = os.environ.get("ADMIN_CHAT_ID", "").strip()
ADMIN_CHAT_ID: int | None = int(_raw) if _raw.lstrip("-").isdigit() else None

if ADMIN_CHAT_ID:
    logger.info("Admin panel enabled for chat ID %d", ADMIN_CHAT_ID)
else:
    logger.warning("ADMIN_CHAT_ID not set — admin panel is disabled.")


def is_admin(update: Update) -> bool:
    user = update.effective_user
    return bool(user and ADMIN_CHAT_ID and user.id == ADMIN_CHAT_ID)


async def notify_admin(
    context: ContextTypes.DEFAULT_TYPE, user, action: str
) -> None:
    if not ADMIN_CHAT_ID:
        return
    if user and user.id == ADMIN_CHAT_ID:
        return
    full_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "Unknown"
    username  = f"@{user.username}" if user.username else "_(no username)_"
    try:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=(
                f"🔔 *New interaction*\n\n"
                f"👤 *Name:* {full_name}\n"
                f"🆔 *User ID:* `{user.id}`\n"
                f"📎 *Username:* {username}\n"
                f"💬 *Action:* {action}"
            ),
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.error("Admin notification failed: %s", exc)

# ─────────────────────────────────────────────────────────────────────────────
# ConversationHandler states  (admin panel)
# ─────────────────────────────────────────────────────────────────────────────
(
    ADMIN_MAIN,
    ADD_CAT, ADD_NAME, ADD_DESC, ADD_PRICE, ADD_PHOTO,
    EDIT_CAT, EDIT_PROD, EDIT_FIELD, EDIT_VAL, EDIT_PHOTO,
    DEL_CAT, DEL_PROD, DEL_CONFIRM,
    SETTINGS_FIELD, SETTINGS_VAL,
) = range(16)

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _fmt_price(price: int) -> str:
    return f"₦{price:,}"


def _new_prod_id(cat_id: str) -> str:
    return f"{cat_id}_{int(time.time())}"

# ─────────────────────────────────────────────────────────────────────────────
# ── CUSTOMER UI ──────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ Browse Products", callback_data="cats")],
        [InlineKeyboardButton("📞 Contact Us",       callback_data="contact")],
    ])


def cats_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row:  list[InlineKeyboardButton]       = []
    for cat in CATS:
        row.append(InlineKeyboardButton(
            f"{cat['emoji']} {cat['name']}", callback_data=f"cat:{cat['id']}"
        ))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 Home", callback_data="home")])
    return InlineKeyboardMarkup(rows)


def product_keyboard(cat_id: str, idx: int, total: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if total > 1:
        rows.append([
            InlineKeyboardButton("◀ Prev", callback_data=f"nav:{cat_id}:{(idx-1)%total}"),
            InlineKeyboardButton("Next ▶", callback_data=f"nav:{cat_id}:{(idx+1)%total}"),
        ])
    rows.append([InlineKeyboardButton("🛒 Buy Now", callback_data=f"buy:{cat_id}:{idx}")])
    rows.append([
        InlineKeyboardButton("🔙 Categories", callback_data="cats"),
        InlineKeyboardButton("🏠 Home",       callback_data="home"),
    ])
    return InlineKeyboardMarkup(rows)


def contact_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🛍️ Browse Products", callback_data="cats")],
        [InlineKeyboardButton("🏠 Home",             callback_data="home")],
    ])


def after_buy_keyboard(cat_id: str, idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Back to Product", callback_data=f"nav:{cat_id}:{idx}")],
        [InlineKeyboardButton("🛍️ Browse More",    callback_data="cats")],
        [InlineKeyboardButton("🏠 Home",            callback_data="home")],
    ])


def home_caption() -> str:
    return (
        f"🛍️ *Welcome to {STORE['name']}!*\n\n"
        f"_{STORE['tagline']}_\n\n"
        "Browse our collection of premium fashion and lifestyle products. "
        "Tap a button below to get started 👇"
    )


def cats_caption() -> str:
    lines = "\n".join(f"  {c['emoji']} {c['name']}" for c in CATS)
    return f"📂 *Shop by Category*\n\n{lines}\n\nChoose a category to browse 👇"


def product_caption(cat: dict, product: dict, idx: int) -> str:
    total = len(cat["products"])
    return (
        f"*{product['name']}*\n\n"
        f"{product['description']}\n\n"
        f"💰 *Price: {_fmt_price(product['price'])}*\n\n"
        f"_{cat['emoji']} {cat['name']}  •  {idx + 1} of {total}_"
    )


def contact_caption() -> str:
    email    = STORE.get("contact_email", "")
    whatsapp = STORE.get("contact_whatsapp", "")
    hours    = STORE.get("business_hours", "Mon – Fri, 9 AM – 6 PM")
    lines    = [f"📞 *Contact {STORE['name']}*\n"]
    if email:    lines.append(f"📧 *Email:* {email}")
    if whatsapp: lines.append(f"💬 *WhatsApp:* {whatsapp}")
    lines += [
        f"\n🕐 *Hours:* {hours}",
        "\nWe typically respond within *2 business hours*.",
        "Include the product name and your delivery address for faster service.",
    ]
    return "\n".join(lines)


def order_caption(product: dict, cat_id: str) -> str:
    email        = STORE.get("contact_email", "")
    whatsapp     = STORE.get("contact_whatsapp", "")
    instructions = STORE.get("order_instructions", "Contact us to place your order.")
    text = (
        f"🛒 *Place Your Order*\n\n"
        f"*Product:* {product['name']}\n"
        f"*Price:* {_fmt_price(product['price'])}\n\n"
        f"{instructions}\n\n"
    )
    if email:    text += f"📧 *Email:* {email}\n"
    if whatsapp: text += f"💬 *WhatsApp:* {whatsapp}\n"
    return text


async def _render_photo(
    q, photo_url: str, caption: str, keyboard: InlineKeyboardMarkup
) -> None:
    """Edit the catalog message in-place, or replace it if it was a text message."""
    media = InputMediaPhoto(media=photo_url, caption=caption, parse_mode="Markdown")
    if q.message.photo:
        await q.edit_message_media(media=media, reply_markup=keyboard)
    else:
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.message.chat.send_photo(
            photo=photo_url, caption=caption,
            parse_mode="Markdown", reply_markup=keyboard,
        )

# ─────────────────────────────────────────────────────────────────────────────
# ── CUSTOMER COMMAND HANDLERS ─────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    logger.info("/start from %s (%s)", user.first_name if user else "?", user.id if user else "?")
    await notify_admin(context, user, "/start — opened the store")
    await update.message.reply_photo(
        photo=STORE["banner_image"],
        caption=home_caption(),
        parse_mode="Markdown",
        reply_markup=home_keyboard(),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await notify_admin(context, user, "/help")
    await update.message.reply_text(
        f"ℹ️ *{STORE['name']} — Help*\n\n"
        "Commands:\n"
        "/start — Open the store\n"
        "/help  — Show this message\n"
        "/myid  — Show your Telegram user ID\n\n"
        "Use the buttons to browse and order. "
        "Or just *type a question* and our AI will answer it 🤖",
        parse_mode="Markdown",
        reply_markup=home_keyboard(),
    )


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"🆔 Your numeric Telegram ID:\n\n`{update.effective_chat.id}`",
        parse_mode="Markdown",
    )

# ─────────────────────────────────────────────────────────────────────────────
# ── CUSTOMER CALLBACK HANDLERS ───────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

async def cb_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query; await q.answer()
    await notify_admin(context, q.from_user, "🏠 Home")
    await _render_photo(q, STORE["banner_image"], home_caption(), home_keyboard())


async def cb_cats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query; await q.answer()
    await notify_admin(context, q.from_user, "📂 Browse categories")
    await _render_photo(q, STORE["banner_image"], cats_caption(), cats_keyboard())


async def cb_contact(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query; await q.answer()
    await notify_admin(context, q.from_user, "📞 Contact Us")
    await _render_photo(q, STORE["banner_image"], contact_caption(), contact_keyboard())


async def cb_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q      = update.callback_query
    cat_id = q.data.split(":", 1)[1]
    cat    = CAT_MAP.get(cat_id)
    if not cat or not cat["products"]:
        await q.answer("No products in this category yet.", show_alert=True); return
    await q.answer()
    await notify_admin(context, q.from_user, f"Browsed: {cat['emoji']} {cat['name']}")
    p = cat["products"][0]
    await _render_photo(q, p["image_url"], product_caption(cat, p, 0),
                        product_keyboard(cat_id, 0, len(cat["products"])))


async def cb_navigate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q              = update.callback_query
    _, cat_id, raw = q.data.split(":")
    idx            = int(raw)
    cat            = CAT_MAP.get(cat_id)
    if not cat:
        await q.answer("Category not found.", show_alert=True); return
    products = cat["products"]
    idx      = idx % len(products)
    p        = products[idx]
    await q.answer()
    await notify_admin(context, q.from_user, f"Viewed: {p['name']}")
    await _render_photo(q, p["image_url"], product_caption(cat, p, idx),
                        product_keyboard(cat_id, idx, len(products)))


async def cb_buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q              = update.callback_query
    _, cat_id, raw = q.data.split(":")
    idx            = int(raw)
    cat            = CAT_MAP.get(cat_id)
    if not cat or idx >= len(cat["products"]):
        await q.answer("Product not found.", show_alert=True); return
    p = cat["products"][idx]
    await q.answer("📦 Order details sent below!")
    await notify_admin(context, q.from_user,
                       f"🛒 Buy Now — {p['name']} ({_fmt_price(p['price'])})")
    await q.message.reply_text(
        order_caption(p, cat_id),
        parse_mode="Markdown",
        reply_markup=after_buy_keyboard(cat_id, idx),
    )

# ─────────────────────────────────────────────────────────────────────────────
# ── GEMINI AI FALLBACK ────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

async def handle_ai_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text
    user      = update.effective_user
    logger.info("AI fallback — %s: %.60s", user.first_name if user else "?", user_text)
    await notify_admin(context, user, user_text)
    await update.message.chat.send_action("typing")
    try:
        response = await gemini_client.aio.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_text,
            config=genai_types.GenerateContentConfig(
                system_instruction=build_system_prompt(),
                max_output_tokens=1024,
            ),
        )
        ai_reply = (response.text or "").strip() or (
            "I'm sorry, I couldn't generate a response. Please try rephrasing."
        )
    except Exception as exc:
        logger.error("Gemini error: %s", exc)
        ai_reply = (
            f"⚠️ I couldn't reach the AI right now. "
            f"Contact us at {STORE.get('contact_email', 'our support team')}."
        )
    await update.message.reply_text(
        ai_reply,
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛍️ Browse Products", callback_data="cats")],
            [InlineKeyboardButton("📞 Contact Us",       callback_data="contact")],
        ]),
    )

# ─────────────────────────────────────────────────────────────────────────────
# ── ADMIN PANEL — keyboards ───────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def _adm_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Manage Products", callback_data="adm:products")],
        [InlineKeyboardButton("🏪 Store Settings",   callback_data="adm:settings")],
        [InlineKeyboardButton("❌ Close Panel",      callback_data="adm:close")],
    ])


def _adm_products_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add Product",    callback_data="adm:add")],
        [InlineKeyboardButton("✏️ Edit Product",   callback_data="adm:edit")],
        [InlineKeyboardButton("🗑️ Delete Product", callback_data="adm:del")],
        [InlineKeyboardButton("🔙 Back",           callback_data="adm:main")],
    ])


def _adm_cats_kb(action: str) -> InlineKeyboardMarkup:
    """Category selection — one per row."""
    rows = [
        [InlineKeyboardButton(f"{c['emoji']} {c['name']}",
                              callback_data=f"adm_cat:{action}:{c['id']}")]
        for c in CATS
    ]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="adm:products")])
    return InlineKeyboardMarkup(rows)


def _adm_prods_kb(cat_id: str, action: str) -> InlineKeyboardMarkup:
    cat   = CAT_MAP.get(cat_id, {})
    prods = cat.get("products", [])
    rows  = [
        [InlineKeyboardButton(
            f"{p['name']} — {_fmt_price(p['price'])}",
            callback_data=f"adm_prod:{action}:{cat_id}:{i}",
        )]
        for i, p in enumerate(prods)
    ]
    rows.append([InlineKeyboardButton("🔙 Back", callback_data=f"adm:{action}")])
    return InlineKeyboardMarkup(rows)


def _adm_fields_kb(cat_id: str, idx: int) -> InlineKeyboardMarkup:
    base = f"adm_field:{cat_id}:{idx}"
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 Name",        callback_data=f"{base}:name"),
            InlineKeyboardButton("📄 Description", callback_data=f"{base}:desc"),
        ],
        [
            InlineKeyboardButton("💰 Price",       callback_data=f"{base}:price"),
            InlineKeyboardButton("🖼️ Photo",       callback_data=f"{base}:photo"),
        ],
        [InlineKeyboardButton("🔙 Back",            callback_data=f"adm_cat:edit:{cat_id}")],
    ])


def _adm_settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏪 Store Name", callback_data="adm_setting:name")],
        [InlineKeyboardButton("📧 Gmail",      callback_data="adm_setting:email")],
        [InlineKeyboardButton("💬 WhatsApp",   callback_data="adm_setting:whatsapp")],
        [InlineKeyboardButton("🔙 Back",       callback_data="adm:main")],
    ])


def _adm_confirm_kb(yes_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, delete", callback_data=f"adm_confirm:yes:{yes_data}"),
            InlineKeyboardButton("❌ Cancel",      callback_data=f"adm_confirm:no"),
        ],
    ])

# ─────────────────────────────────────────────────────────────────────────────
# ── ADMIN PANEL — shared helpers ──────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def _adm_header() -> str:
    return f"🔐 *{STORE['name']} — Admin Panel*\n\n"


async def _adm_reply(update_or_q, text: str, keyboard: InlineKeyboardMarkup,
                     is_callback: bool = True) -> None:
    """Send or edit a text message in the admin panel."""
    if is_callback:
        await update_or_q.edit_message_text(
            text, parse_mode="Markdown", reply_markup=keyboard
        )
    else:
        await update_or_q.reply_text(
            text, parse_mode="Markdown", reply_markup=keyboard
        )

# ─────────────────────────────────────────────────────────────────────────────
# ── ADMIN PANEL — conversation entry & main menu ──────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

async def admin_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Entry point: /admin"""
    if not is_admin(update):
        await update.message.reply_text("⛔ Access denied.")
        return ConversationHandler.END
    context.user_data.clear()
    await update.message.reply_text(
        _adm_header() + "What would you like to do?",
        parse_mode="Markdown",
        reply_markup=_adm_main_kb(),
    )
    return ADMIN_MAIN


async def adm_show_main(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    context.user_data.clear()
    await _adm_reply(q, _adm_header() + "What would you like to do?", _adm_main_kb())
    return ADMIN_MAIN


async def adm_show_products(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    await _adm_reply(q, _adm_header() + "📦 *Manage Products*\n\nChoose an action:",
                     _adm_products_kb())
    return ADMIN_MAIN


async def adm_close(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    await q.edit_message_text(
        "✅ Admin panel closed. Type /admin to reopen it or /start for the store.",
        reply_markup=None,
    )
    context.user_data.clear()
    return ConversationHandler.END


async def admin_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Admin panel closed. Type /admin to reopen.")
    context.user_data.clear()
    return ConversationHandler.END

# ─────────────────────────────────────────────────────────────────────────────
# ── ADMIN PANEL — ADD product flow ────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

async def adm_start_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    context.user_data["new_prod"] = {}
    await _adm_reply(q, _adm_header() + "➕ *Add Product*\n\nSelect the category:",
                     _adm_cats_kb("add"))
    return ADD_CAT


async def add_select_cat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q      = update.callback_query; await q.answer()
    cat_id = q.data.split(":")[-1]
    context.user_data["new_prod"]["cat_id"] = cat_id
    await _adm_reply(q, _adm_header() + "➕ *Add Product*\n\nSend me the *product name*:",
                     InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm:add")]]))
    return ADD_NAME


async def add_get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_prod"]["name"] = update.message.text.strip()
    await update.message.reply_text(
        _adm_header() + "➕ *Add Product*\n\nNow send the *product description*:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="adm:main")]]),
    )
    return ADD_DESC


async def add_get_desc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["new_prod"]["description"] = update.message.text.strip()
    await update.message.reply_text(
        _adm_header() + "➕ *Add Product*\n\nNow send the *price in Naira* (numbers only, e.g. `25000`):",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="adm:main")]]),
    )
    return ADD_PRICE


async def add_get_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = re.sub(r"[^\d]", "", update.message.text)
    if not raw:
        await update.message.reply_text("❌ Please send numbers only (e.g. `25000`).",
                                         parse_mode="Markdown")
        return ADD_PRICE
    context.user_data["new_prod"]["price"] = int(raw)
    await update.message.reply_text(
        _adm_header() + "➕ *Add Product*\n\nFinally, *upload a photo* for this product:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Cancel", callback_data="adm:main")]]),
    )
    return ADD_PHOTO


async def add_get_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    file_id = update.message.photo[-1].file_id
    np      = context.user_data.get("new_prod", {})
    cat_id  = np.get("cat_id")
    cat     = CAT_MAP.get(cat_id)
    if not cat:
        await update.message.reply_text("❌ Category not found. Start over with /admin.")
        return ConversationHandler.END

    new_product = {
        "id":          _new_prod_id(cat_id),
        "name":        np["name"],
        "description": np["description"],
        "price":       np["price"],
        "image_url":   file_id,
    }
    cat["products"].append(new_product)
    save_catalog()

    await update.message.reply_text(
        f"✅ *{new_product['name']}* added to *{cat['name']}*!\n\n"
        f"Price: {_fmt_price(new_product['price'])}\n"
        f"Customers can see it immediately.",
        parse_mode="Markdown",
        reply_markup=_adm_main_kb(),
    )
    context.user_data.clear()
    return ADMIN_MAIN


async def add_photo_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("📸 Please *upload a photo* (not a URL).",
                                    parse_mode="Markdown")
    return ADD_PHOTO

# ─────────────────────────────────────────────────────────────────────────────
# ── ADMIN PANEL — EDIT product flow ───────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

async def adm_start_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    await _adm_reply(q, _adm_header() + "✏️ *Edit Product*\n\nSelect the category:",
                     _adm_cats_kb("edit"))
    return EDIT_CAT


async def edit_select_cat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q      = update.callback_query; await q.answer()
    cat_id = q.data.split(":")[-1]
    context.user_data["edit_cat"] = cat_id
    cat = CAT_MAP.get(cat_id)
    if not cat or not cat["products"]:
        await q.answer("No products in this category.", show_alert=True)
        return EDIT_CAT
    await _adm_reply(q,
        _adm_header() + f"✏️ *Edit Product*\n\nCategory: {cat['emoji']} *{cat['name']}*\n\nSelect a product:",
        _adm_prods_kb(cat_id, "edit"))
    return EDIT_PROD


async def edit_select_prod(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q              = update.callback_query; await q.answer()
    _, _, cat_id, raw = q.data.split(":", 3)
    idx            = int(raw)
    context.user_data["edit_prod_idx"] = idx
    context.user_data["edit_cat"]      = cat_id
    cat  = CAT_MAP.get(cat_id, {})
    prod = cat.get("products", [])[idx]
    await _adm_reply(q,
        _adm_header() +
        f"✏️ *Edit Product*\n\n"
        f"*{prod['name']}*\n"
        f"Price: {_fmt_price(prod['price'])}\n\n"
        f"Which field would you like to change?",
        _adm_fields_kb(cat_id, idx))
    return EDIT_FIELD


async def edit_select_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q    = update.callback_query; await q.answer()
    # callback_data: adm_field:{cat_id}:{idx}:{field}
    parts = q.data.split(":")          # ['adm_field', cat_id, idx, field]
    field  = parts[-1]
    cat_id = parts[1]
    idx    = int(parts[2])
    context.user_data["edit_field"]    = field
    context.user_data["edit_cat"]      = cat_id
    context.user_data["edit_prod_idx"] = idx

    if field == "photo":
        await _adm_reply(q,
            _adm_header() + "✏️ *Edit Product*\n\nUpload the new product photo:",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"adm_prod:edit:{cat_id}:{idx}")]]))
        return EDIT_PHOTO
    else:
        labels = {"name": "product name", "desc": "description", "price": "price (numbers only)"}
        await _adm_reply(q,
            _adm_header() + f"✏️ *Edit Product*\n\nSend the new *{labels.get(field, field)}*:",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data=f"adm_prod:edit:{cat_id}:{idx}")]]))
        return EDIT_VAL


async def edit_get_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    field   = context.user_data.get("edit_field")
    cat_id  = context.user_data.get("edit_cat")
    idx     = context.user_data.get("edit_prod_idx", 0)
    cat     = CAT_MAP.get(cat_id)
    if not cat:
        await update.message.reply_text("❌ Session expired. Run /admin again."); return ConversationHandler.END

    prod = cat["products"][idx]
    text = update.message.text.strip()

    if field == "price":
        raw = re.sub(r"[^\d]", "", text)
        if not raw:
            await update.message.reply_text("❌ Numbers only (e.g. `25000`).", parse_mode="Markdown")
            return EDIT_VAL
        prod["price"] = int(raw)
    elif field == "name":
        prod["name"] = text
    elif field == "desc":
        prod["description"] = text

    save_catalog()
    await update.message.reply_text(
        f"✅ *{prod['name']}* updated successfully! Customers see the change immediately.",
        parse_mode="Markdown",
        reply_markup=_adm_main_kb(),
    )
    context.user_data.clear()
    return ADMIN_MAIN


async def edit_get_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    cat_id = context.user_data.get("edit_cat")
    idx    = context.user_data.get("edit_prod_idx", 0)
    cat    = CAT_MAP.get(cat_id)
    if not cat:
        await update.message.reply_text("❌ Session expired. Run /admin again."); return ConversationHandler.END

    prod               = cat["products"][idx]
    prod["image_url"]  = update.message.photo[-1].file_id
    save_catalog()
    await update.message.reply_text(
        f"✅ Photo updated for *{prod['name']}*! Customers see the change immediately.",
        parse_mode="Markdown",
        reply_markup=_adm_main_kb(),
    )
    context.user_data.clear()
    return ADMIN_MAIN


async def edit_photo_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("📸 Please *upload a photo* (not a URL).",
                                    parse_mode="Markdown")
    return EDIT_PHOTO

# ─────────────────────────────────────────────────────────────────────────────
# ── ADMIN PANEL — DELETE product flow ─────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

async def adm_start_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    await _adm_reply(q, _adm_header() + "🗑️ *Delete Product*\n\nSelect the category:",
                     _adm_cats_kb("del"))
    return DEL_CAT


async def del_select_cat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q      = update.callback_query; await q.answer()
    cat_id = q.data.split(":")[-1]
    context.user_data["del_cat"] = cat_id
    cat = CAT_MAP.get(cat_id)
    if not cat or not cat["products"]:
        await q.answer("No products in this category.", show_alert=True)
        return DEL_CAT
    await _adm_reply(q,
        _adm_header() + f"🗑️ *Delete Product*\n\nCategory: {cat['emoji']} *{cat['name']}*\n\nSelect a product:",
        _adm_prods_kb(cat_id, "del"))
    return DEL_PROD


async def del_select_prod(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q              = update.callback_query; await q.answer()
    _, _, cat_id, raw = q.data.split(":", 3)
    idx            = int(raw)
    cat            = CAT_MAP.get(cat_id)
    prod           = cat["products"][idx]
    context.user_data["del_cat"]      = cat_id
    context.user_data["del_prod_idx"] = idx
    await _adm_reply(q,
        _adm_header() +
        f"🗑️ *Delete Product*\n\n"
        f"Are you sure you want to delete:\n\n"
        f"*{prod['name']}*\n"
        f"Price: {_fmt_price(prod['price'])}\n\n"
        f"⚠️ This cannot be undone.",
        _adm_confirm_kb(f"{cat_id}:{idx}"))
    return DEL_CONFIRM


async def del_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q     = update.callback_query; await q.answer()
    parts = q.data.split(":")   # adm_confirm:yes:{cat_id}:{idx}  or  adm_confirm:no
    decision = parts[1]

    if decision == "no":
        await _adm_reply(q, _adm_header() + "Deletion cancelled.", _adm_main_kb())
        context.user_data.clear()
        return ADMIN_MAIN

    cat_id = parts[2]
    idx    = int(parts[3])
    cat    = CAT_MAP.get(cat_id)
    if not cat or idx >= len(cat["products"]):
        await _adm_reply(q, "❌ Product not found.", _adm_main_kb())
        return ADMIN_MAIN

    removed = cat["products"].pop(idx)
    save_catalog()
    await _adm_reply(q,
        _adm_header() + f"✅ *{removed['name']}* has been deleted. Catalog updated immediately.",
        _adm_main_kb())
    context.user_data.clear()
    return ADMIN_MAIN

# ─────────────────────────────────────────────────────────────────────────────
# ── ADMIN PANEL — STORE SETTINGS flow ─────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

async def adm_show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q = update.callback_query; await q.answer()
    await _adm_reply(q,
        _adm_header() +
        f"🏪 *Store Settings*\n\n"
        f"Current values:\n"
        f"• Name: *{STORE['name']}*\n"
        f"• Email: {STORE.get('contact_email', '—')}\n"
        f"• WhatsApp: {STORE.get('contact_whatsapp', '—')}\n\n"
        f"Select a setting to change:",
        _adm_settings_kb())
    return SETTINGS_FIELD


async def settings_select_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    q     = update.callback_query; await q.answer()
    field = q.data.split(":")[-1]    # name | email | whatsapp
    context.user_data["settings_field"] = field
    labels = {
        "name":      ("Store Name",    STORE.get("name", "")),
        "email":     ("Gmail Address", STORE.get("contact_email", "")),
        "whatsapp":  ("WhatsApp",      STORE.get("contact_whatsapp", "")),
    }
    label, current = labels.get(field, (field, ""))
    await _adm_reply(q,
        _adm_header() + f"🏪 *Store Settings*\n\nCurrent *{label}*: `{current}`\n\nSend the new value:",
        InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="adm:settings")]]))
    return SETTINGS_VAL


async def settings_get_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    field = context.user_data.get("settings_field")
    value = update.message.text.strip()
    if not value:
        await update.message.reply_text("❌ Value cannot be empty."); return SETTINGS_VAL

    field_map = {"name": "name", "email": "contact_email", "whatsapp": "contact_whatsapp"}
    json_key  = field_map.get(field)
    if not json_key:
        await update.message.reply_text("❌ Unknown field."); return ConversationHandler.END

    STORE[json_key] = value
    save_catalog()
    await update.message.reply_text(
        f"✅ *{json_key.replace('_', ' ').title()}* updated to:\n`{value}`\n\nChange is live immediately.",
        parse_mode="Markdown",
        reply_markup=_adm_main_kb(),
    )
    context.user_data.clear()
    return ADMIN_MAIN

# ─────────────────────────────────────────────────────────────────────────────
# ── MAIN ─────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    for key in ("TELEGRAM_BOT_TOKEN", "GEMINI_API_KEY"):
        if not os.environ.get(key):
            raise RuntimeError(f"{key} is not set. Add it in Replit Secrets.")

    app = Application.builder().token(os.environ["TELEGRAM_BOT_TOKEN"]).build()

    # ── Admin ConversationHandler (registered first for priority) ────────────
    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_start)],
        states={
            ADMIN_MAIN: [
                CallbackQueryHandler(adm_show_main,     pattern=r"^adm:main$"),
                CallbackQueryHandler(adm_show_products, pattern=r"^adm:products$"),
                CallbackQueryHandler(adm_start_add,     pattern=r"^adm:add$"),
                CallbackQueryHandler(adm_start_edit,    pattern=r"^adm:edit$"),
                CallbackQueryHandler(adm_start_del,     pattern=r"^adm:del$"),
                CallbackQueryHandler(adm_show_settings, pattern=r"^adm:settings$"),
                CallbackQueryHandler(adm_close,         pattern=r"^adm:close$"),
            ],
            ADD_CAT: [
                CallbackQueryHandler(add_select_cat,    pattern=r"^adm_cat:add:"),
                CallbackQueryHandler(adm_show_products, pattern=r"^adm:products$"),
            ],
            ADD_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_name),
            ],
            ADD_DESC: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_desc),
            ],
            ADD_PRICE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_get_price),
            ],
            ADD_PHOTO: [
                MessageHandler(filters.PHOTO,                   add_get_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_photo_prompt),
            ],
            EDIT_CAT: [
                CallbackQueryHandler(edit_select_cat,   pattern=r"^adm_cat:edit:"),
                CallbackQueryHandler(adm_show_products, pattern=r"^adm:products$"),
            ],
            EDIT_PROD: [
                CallbackQueryHandler(edit_select_prod,  pattern=r"^adm_prod:edit:"),
                CallbackQueryHandler(adm_start_edit,    pattern=r"^adm:edit$"),
            ],
            EDIT_FIELD: [
                CallbackQueryHandler(edit_select_field, pattern=r"^adm_field:"),
                CallbackQueryHandler(edit_select_cat,   pattern=r"^adm_cat:edit:"),
            ],
            EDIT_VAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_get_value),
                CallbackQueryHandler(edit_select_prod,  pattern=r"^adm_prod:edit:"),
            ],
            EDIT_PHOTO: [
                MessageHandler(filters.PHOTO,                   edit_get_photo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, edit_photo_prompt),
                CallbackQueryHandler(edit_select_prod,  pattern=r"^adm_prod:edit:"),
            ],
            DEL_CAT: [
                CallbackQueryHandler(del_select_cat,    pattern=r"^adm_cat:del:"),
                CallbackQueryHandler(adm_show_products, pattern=r"^adm:products$"),
            ],
            DEL_PROD: [
                CallbackQueryHandler(del_select_prod,   pattern=r"^adm_prod:del:"),
                CallbackQueryHandler(adm_start_del,     pattern=r"^adm:del$"),
            ],
            DEL_CONFIRM: [
                CallbackQueryHandler(del_confirm,       pattern=r"^adm_confirm:"),
            ],
            SETTINGS_FIELD: [
                CallbackQueryHandler(settings_select_field, pattern=r"^adm_setting:"),
                CallbackQueryHandler(adm_show_main,         pattern=r"^adm:main$"),
            ],
            SETTINGS_VAL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, settings_get_value),
                CallbackQueryHandler(adm_show_settings,     pattern=r"^adm:settings$"),
            ],
        },
        fallbacks=[
            CommandHandler("cancel", admin_cancel),
            CommandHandler("admin",  admin_start),   # allow re-entry at any time
        ],
        allow_reentry=True,
        per_message=False,
        name="admin_panel",
    )
    app.add_handler(admin_conv)

    # ── Customer commands ─────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help",  help_command))
    app.add_handler(CommandHandler("myid",  myid_command))

    # ── Customer inline-button callbacks ──────────────────────────────────────
    app.add_handler(CallbackQueryHandler(cb_home,     pattern=r"^home$"))
    app.add_handler(CallbackQueryHandler(cb_cats,     pattern=r"^cats$"))
    app.add_handler(CallbackQueryHandler(cb_contact,  pattern=r"^contact$"))
    app.add_handler(CallbackQueryHandler(cb_category, pattern=r"^cat:.+$"))
    app.add_handler(CallbackQueryHandler(cb_navigate, pattern=r"^nav:.+:\d+$"))
    app.add_handler(CallbackQueryHandler(cb_buy,      pattern=r"^buy:.+:\d+$"))

    # ── Gemini AI fallback for free-text messages ────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ai_message))

    logger.info("Bot is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
