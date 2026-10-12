"""
bot/keyboards.py — Inline keyboard builders for Telegram.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

CALLBACK_CONFIRM = "order:confirm"
CALLBACK_CANCEL = "order:cancel"

CALLBACK_OWNER_ACCEPT = "owner:accept:"
CALLBACK_OWNER_REJECT = "owner:reject:"
CALLBACK_OWNER_DELIVERED = "owner:delivered:"


def confirm_cancel_keyboard() -> InlineKeyboardMarkup:
    """Return an inline keyboard with Confirm ✅ and Cancel ❌ buttons."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Confirm", callback_data=CALLBACK_CONFIRM),
                InlineKeyboardButton("❌ Cancel", callback_data=CALLBACK_CANCEL),
            ]
        ]
    )


def owner_order_actions_keyboard(order_id: int) -> InlineKeyboardMarkup:
    """Return inline keyboard with Accept, Reject, Delivered buttons for owner."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Accept", callback_data=f"{CALLBACK_OWNER_ACCEPT}{order_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"{CALLBACK_OWNER_REJECT}{order_id}"),
            ],
            [
                InlineKeyboardButton("🚚 Delivered", callback_data=f"{CALLBACK_OWNER_DELIVERED}{order_id}"),
            ],
        ]
    )

