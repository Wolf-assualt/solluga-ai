"""
bot/handlers.py — Telegram message and callback query handlers.
"""

import logging
from typing import Optional

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

async def handle_order_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    order_text: Optional[str] = None,
) -> None:
    user = update.effective_user
    text = (order_text if order_text is not None else (update.message.text or "")).strip()
    logger.info("Order message from %s (%d): %s", user.first_name, user.id, text)

    # Show typing indicator
    await update.message.chat.send_action("typing")

    from bot.messages import is_stock_inquiry, format_customer_stock_list
    from core.db import get_customer_shop_id, get_shop_by_id, get_all_items

    # Intercept stock / items inquiries from customer
    if is_stock_inquiry(text):
        active_shop_id = get_customer_shop_id(str(user.id))
        shop = get_shop_by_id(active_shop_id)
        items = get_all_items(shop_id=active_shop_id)
        stock_msg = format_customer_stock_list(items, shop_name=shop["name"])
        await update.message.reply_text(stock_msg, parse_mode=ParseMode.MARKDOWN)
        return

    try:
        active_shop_id = get_customer_shop_id(str(user.id))
        draft: OrderDraft = process_message(text, shop_id=active_shop_id)
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

        # Notify shop owner (Phase 2)
        try:
            from bot.owner_handlers import get_owner_id
            from bot.keyboards import owner_order_actions_keyboard
            from bot.messages import format_owner_new_order, format_low_stock_alert
            from core.inventory import get_order_detail, get_low_stock_items

            owner_id = get_owner_id()
            if owner_id and owner_id.isdigit():
                owner_chat_id = int(owner_id)
                order_summary = get_order_detail(order_id)
                if order_summary:
                    cust_name = user.full_name or user.first_name
                    owner_msg = format_owner_new_order(order_summary, customer_name=f"{cust_name} (`{user.id}`)")
                    await context.bot.send_message(
                        chat_id=owner_chat_id,
                        text=owner_msg,
                        parse_mode=ParseMode.MARKDOWN,
                        reply_markup=owner_order_actions_keyboard(order_id),
                    )

                # Low stock check
                low_items = get_low_stock_items()
                # Check if any ordered item is now low in stock
                ordered_item_ids = {li.item_id for li in draft.lines}
                newly_low = [it for it in low_items if it.id in ordered_item_ids]
                if newly_low:
                    alert_msg = format_low_stock_alert(newly_low)
                    await context.bot.send_message(
                        chat_id=owner_chat_id,
                        text=alert_msg,
                        parse_mode=ParseMode.MARKDOWN,
                    )
        except Exception as exc:
            logger.warning("Could not notify shop owner: %s", exc)


    elif query.data == CALLBACK_CANCEL:
        original_text = query.message.text or ""
        clear_draft(user.id)
        await query.edit_message_text(
            format_cancelled(original_text),
            parse_mode=ParseMode.MARKDOWN,
        )


# ---------------------------------------------------------------------------
# Voice note / audio message handler (Phase 4)
# ---------------------------------------------------------------------------

async def handle_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    voice = update.message.voice or update.message.audio
    if not voice:
        return

    logger.info("Voice note received from %s (%d)", user.first_name, user.id)
    await update.message.chat.send_action("record_voice")

    try:
        from core.transcription import transcribe_audio_bytes

        file_obj = await context.bot.get_file(voice.file_id)
        audio_bytes = await file_obj.download_as_bytearray()
        mime_type = voice.mime_type or "audio/ogg"

        result = transcribe_audio_bytes(bytes(audio_bytes), mime_type=mime_type)

        if not result.text:
            await update.message.reply_text(
                result.clarification_prompt or "🎤 Could not hear clearly. Please try sending text or record again!"
            )
            return

        # If transcription is unsure, ask customer to clarify / confirm
        if not result.is_confident and result.clarification_prompt:
            await update.message.reply_text(
                result.clarification_prompt,
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Inform what was heard and process order flow
        await update.message.reply_text(
            f"🎙️ *Heard:* _\"{result.text}\"_",
            parse_mode=ParseMode.MARKDOWN,
        )

        # Pass transcribed text into the existing order flow
        await handle_order_message(update, context, order_text=result.text)

    except Exception as exc:
        logger.exception("Voice note processing error: %s", exc)
        await update.message.reply_text("⚠️ Could not process voice note. Please send your order as text!")

