"""
bot/keyboards.py — Inline keyboard builders for Telegram.
"""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

CALLBACK_CONFIRM = "order:confirm"
CALLBACK_CANCEL = "order:cancel"


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
