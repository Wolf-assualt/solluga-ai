"""
bot/owner_handlers.py — Telegram handlers for shop owner commands and actions.

All owner commands verify OWNER_TELEGRAM_ID from .env and reject unauthorized users.
Includes conversation handler for /additem step-by-step flow and callbacks for
accepting/rejecting/delivering orders.
"""

import logging
import os
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.keyboards import (
    CALLBACK_OWNER_ACCEPT,
    CALLBACK_OWNER_DELIVERED,
    CALLBACK_OWNER_REJECT,
    owner_order_actions_keyboard,
)
from bot.messages import (
    format_customer_status_update,
    format_stock_list,
    format_todays_orders,
    format_todays_sales,
)
from core.inventory import (
    add_new_item,
    add_stock,
    get_order_detail,
    get_stock_list,
    get_todays_orders,
    get_todays_sales_total,
    set_price,
    update_order_status,
)

logger = logging.getLogger(__name__)

# Conversation states for /additem
ADD_NAME, ADD_UNIT, ADD_PRICE, ADD_STOCK, ADD_ALIASES = range(5)


def get_owner_id() -> str:
    """Return owner Telegram ID from environment."""
    return os.getenv("OWNER_TELEGRAM_ID", "").strip()


def is_owner(user: any) -> bool:
    """
    Check if the given Telegram user matches the configured owner.
    Supports numeric ID matching and username/name matching.
    """
    if not user:
        return False
    owner_cfg = get_owner_id()
    if not owner_cfg:
        return False

    user_id_str = str(getattr(user, "id", user)).strip()
    # Check numeric ID match
    if user_id_str == owner_cfg:
        return True

    # Check username match (case-insensitive)
    username = getattr(user, "username", None)
    if username and username.lower().strip("@") == owner_cfg.lower().strip("@"):
        return True

    # Check full_name or first_name match (case-insensitive)
    full_name = getattr(user, "full_name", None)
    if full_name and full_name.lower().strip() == owner_cfg.lower().strip():
        return True

    first_name = getattr(user, "first_name", None)
    if first_name and first_name.lower().strip() == owner_cfg.lower().strip():
        return True

    return False


async def reject_non_owner(update: Update) -> bool:
    """
    Returns True if user is unauthorized and replies with friendly rejection
    including their numeric ID so they can easily configure .env if needed.
    """
    user = update.effective_user
    if not is_owner(user):
        user_info = f"`{user.id}`" if user else "unknown"
        msg = (
            f"⛔ Unauthorized. This command is restricted to the shop owner.\n\n"
            f"ℹ️ Your Telegram User ID is: {user_info}\n"
            f"To authorize yourself, set `OWNER_TELEGRAM_ID={user.id if user else ''}` in `.env`."
        )
        if update.message:
            await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)
        elif update.callback_query:
            await update.callback_query.answer("⛔ Unauthorized.", show_alert=True)
        return True
    return False


# ---------------------------------------------------------------------------
# /stock command
# ---------------------------------------------------------------------------

async def cmd_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not is_owner(user):
        from core.db import get_customer_shop_id, get_shop_by_id, get_all_items
        from bot.messages import format_customer_stock_list
        active_shop_id = get_customer_shop_id(str(user.id) if user else "1")
        shop = get_shop_by_id(active_shop_id)
        items = get_all_items(shop_id=active_shop_id)
        stock_msg = format_customer_stock_list(items, shop_name=shop["name"])
        await update.message.reply_text(stock_msg, parse_mode=ParseMode.MARKDOWN)
        return

    stocks = get_stock_list()
    msg = format_stock_list(stocks)
    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# /addstock <item> <qty>
# ---------------------------------------------------------------------------

async def cmd_addstock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_non_owner(update):
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "⚠️ Usage: `/addstock <item> <qty>`\nExample: `/addstock rice 50` or `/addstock oil 10`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    qty_str = args[-1]
    item_name = " ".join(args[:-1])

    try:
        qty = float(qty_str)
        updated_row = add_stock(item_name, qty)
        await update.message.reply_text(
            f"✅ Stock updated for *{updated_row.name.title()}*!\n"
            f"Added: *+{qty:g} {updated_row.unit}*\n"
            f"Current Stock: *{updated_row.stock:g} {updated_row.unit}*",
            parse_mode=ParseMode.MARKDOWN,
        )
    except ValueError as exc:
        await update.message.reply_text(f"⚠️ Error: {exc}", parse_mode=ParseMode.MARKDOWN)
    except Exception as exc:
        logger.exception("addstock error: %s", exc)
        await update.message.reply_text(f"⚠️ Failed to update stock: {exc}")


# ---------------------------------------------------------------------------
# /setprice <item> <price>
# ---------------------------------------------------------------------------

async def cmd_setprice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_non_owner(update):
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "⚠️ Usage: `/setprice <item> <price>`\nExample: `/setprice rice 60` or `/setprice sugar 48`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    price_str = args[-1]
    item_name = " ".join(args[:-1])

    try:
        new_price = float(price_str)
        updated_row = set_price(item_name, new_price)
        await update.message.reply_text(
            f"✅ Price updated for *{updated_row.name.title()}*!\n"
            f"New Price: *₹{updated_row.price:.2f} per {updated_row.unit}*",
            parse_mode=ParseMode.MARKDOWN,
        )
    except ValueError as exc:
        await update.message.reply_text(f"⚠️ Error: {exc}", parse_mode=ParseMode.MARKDOWN)
    except Exception as exc:
        logger.exception("setprice error: %s", exc)
        await update.message.reply_text(f"⚠️ Failed to update price: {exc}")


# ---------------------------------------------------------------------------
# /orders & /sales
# ---------------------------------------------------------------------------

async def cmd_orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_non_owner(update):
        return

    orders = get_todays_orders()
    text = format_todays_orders(orders)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


async def cmd_sales(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await reject_non_owner(update):
        return

    orders = get_todays_orders()
    active_count = sum(1 for o in orders if o.status in ("confirmed", "accepted", "delivered"))
    total_sales = get_todays_sales_total()
    text = format_todays_sales(total_sales, active_count)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# /additem step-by-step ConversationHandler
# ---------------------------------------------------------------------------

async def additem_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if await reject_non_owner(update):
        return ConversationHandler.END

    context.user_data.pop("new_item", None)
    context.user_data["new_item"] = {}
    await update.message.reply_text(
        "📝 *Add New Item (Step 1/5)*\n\nWhat is the item name? (e.g. `tea powder`)\n\n_Type /cancel to abort._",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADD_NAME


async def additem_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip().lower()
    if not name:
        await update.message.reply_text("Please enter a valid item name:")
        return ADD_NAME

    context.user_data["new_item"]["name"] = name
    await update.message.reply_text(
        f"Item name set to: *{name}*\n\n📝 *Step 2/5:* What is the unit? (e.g. `kg`, `litre`, `piece`, `packet`)",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADD_UNIT


async def additem_unit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    unit = update.message.text.strip().lower()
    if not unit:
        await update.message.reply_text("Please enter a valid unit:")
        return ADD_UNIT

    context.user_data["new_item"]["unit"] = unit
    await update.message.reply_text(
        f"Unit set to: *{unit}*\n\n📝 *Step 3/5:* What is the price per {unit} in ₹? (e.g. `120`)",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADD_PRICE


async def additem_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        price = float(text)
        if price <= 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a positive number for price:")
        return ADD_PRICE

    context.user_data["new_item"]["price"] = price
    await update.message.reply_text(
        f"Price set to: *₹{price:.2f}*\n\n📝 *Step 4/5:* What is the starting stock? (e.g. `25`)",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADD_STOCK


async def additem_stock(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    try:
        stock = float(text)
        if stock < 0:
            raise ValueError()
    except ValueError:
        await update.message.reply_text("⚠️ Please enter a non-negative number for stock:")
        return ADD_STOCK

    context.user_data["new_item"]["stock"] = stock
    await update.message.reply_text(
        f"Starting stock set to: *{stock:g}*\n\n"
        f"📝 *Step 5/5:* Enter aliases/keywords separated by commas (Tamil/Tanglish/spelling variations).\n"
        f"Example: `tea, chaya, theila, tea packet`\n"
        f"Or type `none` to skip extra aliases.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return ADD_ALIASES


async def additem_aliases(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    data = context.user_data.get("new_item", {})

    if text.lower() == "none":
        aliases = []
    else:
        aliases = [a.strip().lower() for a in text.split(",") if a.strip()]

    try:
        created = add_new_item(
            name=data["name"],
            unit=data["unit"],
            price=data["price"],
            stock=data["stock"],
            aliases=aliases,
        )
        await update.message.reply_text(
            f"🎉 *Item Added Successfully!*\n\n"
            f"• *Name:* {created.name.title()}\n"
            f"• *Unit:* {created.unit}\n"
            f"• *Price:* ₹{created.price:.2f}\n"
            f"• *Stock:* {created.stock:g} {created.unit}\n"
            f"• *Aliases:* {', '.join(created.aliases)}",
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as exc:
        logger.exception("Failed to add new item: %s", exc)
        await update.message.reply_text(f"⚠️ Error adding item: {exc}")
    finally:
        context.user_data.pop("new_item", None)

    return ConversationHandler.END


async def additem_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("new_item", None)
    await update.message.reply_text("❌ Item addition cancelled.")
    return ConversationHandler.END


# ---------------------------------------------------------------------------
# Owner Order Action Callbacks (Accept, Reject, Delivered)
# ---------------------------------------------------------------------------

async def handle_owner_order_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if await reject_non_owner(update):
        return

    data = query.data
    action = None
    order_id = None

    if data.startswith(CALLBACK_OWNER_ACCEPT):
        action = "accepted"
        order_id = int(data[len(CALLBACK_OWNER_ACCEPT):])
    elif data.startswith(CALLBACK_OWNER_REJECT):
        action = "rejected"
        order_id = int(data[len(CALLBACK_OWNER_REJECT):])
    elif data.startswith(CALLBACK_OWNER_DELIVERED):
        action = "delivered"
        order_id = int(data[len(CALLBACK_OWNER_DELIVERED):])

    if not action or order_id is None:
        await query.answer("Unknown action.")
        return

    await query.answer()

    order = get_order_detail(order_id)
    if not order:
        await query.edit_message_text(f"⚠️ Order #{order_id} not found.")
        return

    try:
        update_order_status(order_id, action)
    except Exception as exc:
        await query.message.reply_text(f"⚠️ Failed to update order: {exc}")
        return

    # Update owner's message
    original_text = query.message.text or ""
    status_emoji = {"accepted": "✅ ACCEPTED", "rejected": "❌ REJECTED", "delivered": "🚚 DELIVERED"}
    header_update = f"📌 Status updated: *{status_emoji.get(action, action.upper())}*"

    # If action is delivered or rejected, remove or keep updated keyboard
    new_keyboard = None if action in ("delivered", "rejected") else owner_order_actions_keyboard(order_id)

    await query.edit_message_text(
        text=f"{original_text}\n\n{header_update}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=new_keyboard,
    )

    # Notify customer if customer_id is a valid Telegram chat ID
    if order.customer_id and order.customer_id.isdigit():
        try:
            cust_msg = format_customer_status_update(order_id, action)
            await context.bot.send_message(
                chat_id=int(order.customer_id),
                text=cust_msg,
                parse_mode=ParseMode.MARKDOWN,
            )
            logger.info("Notified customer %s about order %d -> %s", order.customer_id, order_id, action)
        except Exception as exc:
            logger.warning("Could not notify customer %s: %s", order.customer_id, exc)


def get_additem_conversation_handler() -> ConversationHandler:
    """Build and return the ConversationHandler for /additem."""
    return ConversationHandler(
        entry_points=[CommandHandler("additem", additem_start)],
        states={
            ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, additem_name)],
            ADD_UNIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, additem_unit)],
            ADD_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, additem_price)],
            ADD_STOCK: [MessageHandler(filters.TEXT & ~filters.COMMAND, additem_stock)],
            ADD_ALIASES: [MessageHandler(filters.TEXT & ~filters.COMMAND, additem_aliases)],
        },
        fallbacks=[CommandHandler("cancel", additem_cancel)],
        allow_reentry=True,
    )
