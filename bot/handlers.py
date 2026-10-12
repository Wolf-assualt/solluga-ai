"""
bot/handlers.py — Telegram message and callback query handlers.
"""

import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from bot.keyboards import (
    CALLBACK_CANCEL,
    CALLBACK_CONFIRM,
    confirm_cancel_keyboard,
)
from bot.messages import (
    format_cancelled,
    format_confirmed,
    format_empty_order,
    format_only_unknowns,
    format_order_summary,
    format_welcome,
)
from bot.session import clear_draft, get_draft, set_draft
from core.order import OrderDraft, confirm_order, process_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# /start command
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        format_welcome(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ---------------------------------------------------------------------------
# Plain text message — customer sends an order
# ---------------------------------------------------------------------------

async def handle_order_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = update.message.text.strip()
    logger.info("Order message from %s (%d): %s", user.first_name, user.id, text)

    # Show typing indicator
    await update.message.chat.send_action("typing")

    try:
        draft: OrderDraft = process_message(text)
    except Exception as exc:
        logger.exception("process_message failed: %s", exc)
        await update.message.reply_text(
            "⚠️ Something went wrong. Please try again!",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # No items at all
    if not draft.lines and not draft.unknown_items:
        await update.message.reply_text(
            format_empty_order(text),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # All items unknown
    if not draft.lines and draft.unknown_items:
        await update.message.reply_text(
            format_only_unknowns(draft.unknown_items, text),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Store draft in session
    set_draft(user.id, draft)

    summary = format_order_summary(draft, text)
    await update.message.reply_text(
        summary,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=confirm_cancel_keyboard(),
    )


# ---------------------------------------------------------------------------
# Inline button callbacks — Confirm or Cancel
# ---------------------------------------------------------------------------

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    await query.answer()

    draft = get_draft(user.id)

    if query.data == CALLBACK_CONFIRM:
        if draft is None or not draft.lines:
            await query.edit_message_text("⚠️ No pending order found. Please send your order again.")
            return

        try:
            order_id = confirm_order(str(user.id), draft)
        except ValueError as exc:
            logger.error("confirm_order failed: %s", exc)
            await query.edit_message_text(
                f"⚠️ Could not confirm order: {exc}\nPlease try ordering again."
            )
            clear_draft(user.id)
            return

        clear_draft(user.id)
        # Try to read back original message text for language detection
        original_text = query.message.text or ""
        await query.edit_message_text(
            format_confirmed(order_id, draft.total, original_text),
            parse_mode=ParseMode.MARKDOWN,
        )

    elif query.data == CALLBACK_CANCEL:
        original_text = query.message.text or ""
        clear_draft(user.id)
        await query.edit_message_text(
            format_cancelled(original_text),
            parse_mode=ParseMode.MARKDOWN,
        )
