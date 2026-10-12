"""
core/whatsapp.py — WhatsApp Cloud API Channel implementation.

Handles inbound webhook validation, message parsing, and outbound sending of
text and interactive quick reply buttons via Meta WhatsApp Cloud API.
"""

from __future__ import annotations

import logging
import os
from typing import Optional
import httpx
from dotenv import load_dotenv

from core.channel import Button, Channel

load_dotenv()

logger = logging.getLogger(__name__)


class WhatsAppChannel(Channel):
    """WhatsApp Cloud API transport."""

    def __init__(
        self,
        phone_number_id: Optional[str] = None,
        access_token: Optional[str] = None,
        verify_token: Optional[str] = None,
    ):
        self.phone_number_id = (phone_number_id or os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")).strip()
        self.access_token = (access_token or os.getenv("WHATSAPP_ACCESS_TOKEN", "")).strip()
        self.verify_token = (verify_token or os.getenv("WHATSAPP_VERIFY_TOKEN", "sollunga_verify_token")).strip()
        self.api_version = os.getenv("WHATSAPP_API_VERSION", "v21.0")

    @property
    def channel_name(self) -> str:
        return "whatsapp"

    @property
    def messages_endpoint(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}/{self.phone_number_id}/messages"

    async def send_text(self, recipient_id: str, text: str) -> bool:
        """Send a standard text message on WhatsApp."""
        if not self.phone_number_id or not self.access_token:
            logger.warning("WhatsApp credentials not configured; skipped send_text to %s", recipient_id)
            return False

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_id,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.messages_endpoint, json=payload, headers=headers)
                if resp.status_code >= 400:
                    logger.error("WhatsApp send_text error (%d): %s", resp.status_code, resp.text)
                    return False
                return True
        except Exception as exc:
            logger.exception("Failed sending WhatsApp text: %s", exc)
            return False

    async def send_buttons(
        self,
        recipient_id: str,
        text: str,
        buttons: list[Button],
    ) -> bool:
        """
        Send an interactive message with quick reply buttons on WhatsApp.
        Meta allows up to 3 quick reply buttons per message.
        """
        if not self.phone_number_id or not self.access_token:
            logger.warning("WhatsApp credentials not configured; skipped send_buttons to %s", recipient_id)
            return False

        # WhatsApp buttons are capped at 3
        wa_buttons = []
        for i, b in enumerate(buttons[:3]):
            wa_buttons.append({
                "type": "reply",
                "reply": {
                    "id": b.payload,
                    "title": b.title[:20],  # Meta max 20 chars for button title
                },
            })

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": recipient_id,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": text},
                "action": {"buttons": wa_buttons},
            },
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.messages_endpoint, json=payload, headers=headers)
                if resp.status_code >= 400:
                    logger.error("WhatsApp send_buttons error (%d): %s", resp.status_code, resp.text)
                    # Fallback to plain text if interactive fails
                    options_str = "\n".join(f"👉 Reply '{b.title}'" for b in buttons)
                    return await self.send_text(recipient_id, f"{text}\n\n{options_str}")
                return True
        except Exception as exc:
            logger.exception("Failed sending WhatsApp buttons: %s", exc)
            return False

    async def download_media(self, media_id: str) -> Optional[tuple[bytes, str]]:
        """
        Download binary media (e.g. voice note audio) given a WhatsApp media_id.
        Returns (content_bytes, mime_type) or None on failure.
        """
        if not self.access_token:
            return None

        headers = {"Authorization": f"Bearer {self.access_token}"}
        url = f"https://graph.facebook.com/{self.api_version}/{media_id}"

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Step 1: Query media url
                info_resp = await client.get(url, headers=headers)
                if info_resp.status_code != 200:
                    logger.error("Failed querying media url: %s", info_resp.text)
                    return None
                data = info_resp.json()
                media_url = data.get("url")
                mime_type = data.get("mime_type", "audio/ogg")
                if not media_url:
                    return None

                # Step 2: Download raw binary
                download_resp = await client.get(media_url, headers=headers)
                if download_resp.status_code == 200:
                    return download_resp.content, mime_type
                return None
        except Exception as exc:
            logger.exception("WhatsApp download_media failed: %s", exc)
            return None


def parse_whatsapp_webhook(payload: dict) -> list[dict]:
    """
    Extract normalized message events from WhatsApp webhook payload.
    Returns list of dicts:
      {
        "from": "919876543210",
        "name": "Customer Name",
        "type": "text" | "button" | "audio" | "unknown",
        "text": str,
        "payload": str,
        "media_id": str,
        "mime_type": str,
      }
    """
    events = []
    try:
        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                contacts = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}

                for msg in messages:
                    sender = msg.get("from", "")
                    name = contacts.get(sender, sender)
                    msg_type = msg.get("type", "")

                    event = {
                        "from": sender,
                        "name": name,
                        "type": msg_type,
                        "text": "",
                        "payload": "",
                        "media_id": "",
                        "mime_type": "",
                    }

                    if msg_type == "text":
                        event["text"] = msg.get("text", {}).get("body", "")
                    elif msg_type == "interactive":
                        reply = msg.get("interactive", {}).get("button_reply", {})
                        event["type"] = "button"
                        event["payload"] = reply.get("id", "")
                        event["text"] = reply.get("title", "")
                    elif msg_type == "button":
                        btn = msg.get("button", {})
                        event["type"] = "button"
                        event["payload"] = btn.get("payload", "")
                        event["text"] = btn.get("text", "")
                    elif msg_type in ("audio", "voice"):
                        audio = msg.get("audio") or msg.get("voice") or {}
                        event["type"] = "audio"
                        event["media_id"] = audio.get("id", "")
                        event["mime_type"] = audio.get("mime_type", "audio/ogg")
                    else:
                        continue

                    events.append(event)
    except Exception as exc:
        logger.warning("Error parsing whatsapp webhook: %s", exc)

    return events
