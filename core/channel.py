"""
core/channel.py — Channel abstraction for Sollunga AI.

Defines a clean, unified interface for messaging channels (Telegram, WhatsApp, Web, Test).
The core ordering workflow and business logic interact with Channel without caring
about the specific transport details.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class Button:
    """Action button representation."""
    title: str
    payload: str


class Channel(ABC):
    """Abstract messaging channel."""

    @property
    @abstractmethod
    def channel_name(self) -> str:
        """Name of the channel, e.g. 'telegram', 'whatsapp', 'fake'."""
        pass

    @abstractmethod
    async def send_text(self, recipient_id: str, text: str) -> bool:
        """Send a plain or markdown text message to a user."""
        pass

    @abstractmethod
    async def send_buttons(
        self,
        recipient_id: str,
        text: str,
        buttons: list[Button],
    ) -> bool:
        """Send a message with interactive buttons/options to a user."""
        pass


class FakeChannel(Channel):
    """
    In-memory channel used for testing and mock simulations.
    Records all outbound messages for assertions.
    """

    def __init__(self, name: str = "fake"):
        self._name = name
        self.sent_messages: list[dict] = []

    @property
    def channel_name(self) -> str:
        return self._name

    async def send_text(self, recipient_id: str, text: str) -> bool:
        self.sent_messages.append({
            "type": "text",
            "recipient_id": recipient_id,
            "text": text,
        })
        return True

    async def send_buttons(
        self,
        recipient_id: str,
        text: str,
        buttons: list[Button],
    ) -> bool:
        self.sent_messages.append({
            "type": "buttons",
            "recipient_id": recipient_id,
            "text": text,
            "buttons": [{"title": b.title, "payload": b.payload} for b in buttons],
        })
        return True

    def clear(self) -> None:
        self.sent_messages.clear()
