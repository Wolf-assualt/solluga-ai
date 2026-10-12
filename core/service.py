"""
core/service.py — Channel-independent Order Service.

Coordinates session state, LLM extraction, database validation, and notifications.
Called by both Telegram handlers and WhatsApp webhooks.
"""

from __future__ import annotations

import logging
from typing import Optional

from bot.messages import (
    format_cancelled,
    format_confirmed,
    format_empty_order,
    format_only_unknowns,
    format_order_summary,
    format_owner_new_order,
    format_low_stock_alert,
)
from core.channel import Button, Channel
from core.inventory import get_low_stock_items, get_order_detail
from core.order import OrderDraft, confirm_order, process_message

logger = logging.getLogger(__name__)

# Global channel-aware session storage: { "channel:user_id" -> OrderDraft }
_channel_sessions: dict[str, OrderDraft] = {}


def _session_key(channel_name: str, user_id: str) -> str:
    return f"{channel_name}:{user_id}"


def get_user_draft(channel_name: str, user_id: str) -> Optional[OrderDraft]:
    return _channel_sessions.get(_session_key(channel_name, user_id))


def set_user_draft(channel_name: str, user_id: str, draft: OrderDraft) -> None:
    _channel_sessions[_session_key(channel_name, user_id)] = draft


def clear_user_draft(channel_name: str, user_id: str) -> None:
    _channel_sessions.pop(_session_key(channel_name, user_id), None)


async def handle_customer_text(
    channel: Channel,
    customer_id: str,
    text: str,
) -> None:
    """
    Process incoming customer message from any channel (Telegram / WhatsApp / etc.)
    and send back the appropriate response via the channel.
    """
    cleaned = text.strip()
    if not cleaned:
        return

    from core.db import get_all_shops, get_customer_shop_id, set_customer_shop_id, get_shop_by_id

    # Check for shop selection commands (e.g. /shop, /shops)
    if cleaned.lower() in ("/shops", "/shop", "shops", "shop"):
        shops = get_all_shops()
        current_id = get_customer_shop_id(customer_id)
        current_shop = get_shop_by_id(current_id)
        lines = [
            f"🏪 *Sollunga Shops*",
            f"Current Shop: *{current_shop['name']}*",
            "",
            "Change shop by replying with `/shop <number>`:",
        ]
        buttons = []
        for s in shops:
            active_marker = " ✅" if s["id"] == current_id else ""
            lines.append(f"• `{s['id']}` - *{s['name']}*{active_marker}")
            buttons.append(Button(title=f"Shop {s['id']}", payload=f"shop:select:{s['id']}"))
        await channel.send_buttons(customer_id, "\n".join(lines), buttons[:3])
        return

    # Check if user sent `/shop <id>` or `shop <id>`
    if cleaned.lower().startswith("/shop ") or cleaned.lower().startswith("shop "):
        parts = cleaned.split()
        if len(parts) >= 2 and parts[1].isdigit():
            chosen_id = int(parts[1])
            target_shop = get_shop_by_id(chosen_id)
            set_customer_shop_id(customer_id, chosen_id)
            await channel.send_text(
                customer_id,
                f"✅ Selected shop: *{target_shop['name']}*! You can now send your order.",
            )
            return

    # Fetch customer's current shop
    active_shop_id = get_customer_shop_id(customer_id)

    # Check for stock / items inquiry
    from bot.messages import is_stock_inquiry, format_customer_stock_list
    if is_stock_inquiry(cleaned):
        from core.db import get_all_items
        shop = get_shop_by_id(active_shop_id)
        items = get_all_items(shop_id=active_shop_id)
        stock_msg = format_customer_stock_list(items, shop_name=shop["name"])
        await channel.send_text(customer_id, stock_msg)
        return

    # Process draft with active shop
    try:
        draft = process_message(cleaned, shop_id=active_shop_id)
    except Exception as exc:
        logger.exception("Error processing customer message: %s", exc)
        await channel.send_text(
            customer_id,
            "⚠️ Sir/Ma'am, small technical glitch aagiduchi. Please try sending again in a few seconds!",
        )
        return

    # No items found
    if not draft.lines and not draft.unknown_items:
        await channel.send_text(customer_id, format_empty_order(cleaned))
        return

    # Only unknown items
    if not draft.lines and draft.unknown_items:
        await channel.send_text(
            customer_id,
            format_only_unknowns(draft.unknown_items, cleaned),
        )
        return

    # Store draft in session
    set_user_draft(channel.channel_name, customer_id, draft)

    # Format summary and prompt for confirmation
    summary = format_order_summary(draft, cleaned)
    buttons = [
        Button(title="Confirm", payload="order:confirm"),
        Button(title="Cancel", payload="order:cancel"),
    ]
    await channel.send_buttons(customer_id, summary, buttons)


async def handle_order_confirmation(
    channel: Channel,
    customer_id: str,
    customer_display_name: str = "",
    original_text: str = "",
    owner_channel: Optional[Channel] = None,
    owner_id: Optional[str] = None,
) -> Optional[int]:
    """
    Confirm pending draft for user on this channel.
    Returns the created order_id, or None if no draft.
    """
    from core.db import get_customer_shop_id

    draft = get_user_draft(channel.channel_name, customer_id)
    if draft is None or not draft.lines:
        await channel.send_text(
            customer_id,
            "⚠️ No pending order found. Please send your order again.",
        )
        return None

    active_shop_id = get_customer_shop_id(customer_id)

    try:
        order_id = confirm_order(customer_id, draft, shop_id=active_shop_id)
    except ValueError as exc:
        logger.error("confirm_order failed for %s: %s", customer_id, exc)
        clear_user_draft(channel.channel_name, customer_id)
        await channel.send_text(
            customer_id,
            f"⚠️ Could not confirm order: {exc}\nPlease try ordering again.",
        )
        return None

    clear_user_draft(channel.channel_name, customer_id)

    # Notify customer of success
    await channel.send_text(
        customer_id,
        format_confirmed(order_id, draft.total, original_text),
    )

    # Notify shop owner if configured
    if owner_channel and owner_id:
        try:
            summary = get_order_detail(order_id)
            if summary:
                display = customer_display_name or f"Customer `{customer_id}` ({channel.channel_name})"
                owner_msg = format_owner_new_order(summary, customer_name=display)
                owner_buttons = [
                    Button(title="Accept", payload=f"owner:accept:{order_id}"),
                    Button(title="Reject", payload=f"owner:reject:{order_id}"),
                    Button(title="Delivered", payload=f"owner:delivered:{order_id}"),
                ]
                await owner_channel.send_buttons(owner_id, owner_msg, owner_buttons)

            # Check low stock
            low_items = get_low_stock_items()
            ordered_ids = {li.item_id for li in draft.lines}
            newly_low = [it for it in low_items if it.id in ordered_ids]
            if newly_low:
                alert_text = format_low_stock_alert(newly_low)
                await owner_channel.send_text(owner_id, alert_text)
        except Exception as exc:
            logger.warning("Failed notifying owner: %s", exc)

    return order_id


async def handle_order_cancellation(
    channel: Channel,
    customer_id: str,
    original_text: str = "",
) -> None:
    """Cancel pending draft for user."""
    clear_user_draft(channel.channel_name, customer_id)
    await channel.send_text(customer_id, format_cancelled(original_text))
