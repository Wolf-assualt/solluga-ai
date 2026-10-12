"""
core/telegram_channel.py — Telegram implementation of Channel interface.

Wraps the telegram Bot API so outbound channel actions (send_text, send_buttons)
can be invoked uniformly across all channels.
"""

from __future__ import annotations

import logging
from typing import Optional
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from core.channel import Button, Channel

logger = logging.getLogger(__name__)


class TelegramChannel(Channel):
    """Telegram bot channel implementation."""

    def __init__(self, bot: Bot):
        self._bot = bot

    @property
    def channel_name(self) -> str:
        return "telegram"

    async def send_text(self, recipient_id: str, text: str) -> bool:
        try:
            chat_id = int(recipient_id)
            await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
            )
            return True
        except Exception as exc:
            logger.error("Telegram send_text failed for %s: %s", recipient_id, exc)
            return False

    async def send_buttons(
        self,
        recipient_id: str,
        text: str,
        buttons: list[Button],
    ) -> bool:
        try:
            chat_id = int(recipient_id)
            keyboard = InlineKeyboardMarkup(
                [[InlineKeyboardButton(b.title, callback_data=b.payload) for b in buttons]]
            )
            await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
            )
            return True
        except Exception as exc:
            logger.error("Telegram send_buttons failed for %s: %s", recipient_id, exc)
            return False
