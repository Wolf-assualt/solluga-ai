"""
bot/qr.py — Payment QR code storage and delivery helpers.

The shop owner provides a QR image (usually a UPI QR) either by:
  1. Uploading it in Telegram via /setqr  ->  saved to data/qr.png
  2. Setting UPI_QR_PATH in .env to an image file path

Whenever the owner confirms (accepts) a customer order, the QR is sent to
the customer so they can pay.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from telegram.constants import ParseMode

logger = logging.getLogger(__name__)

#: Where an uploaded QR photo is stored (written on first /setqr upload).
SAVED_QR_PATH = Path(__file__).resolve().parent.parent / "data" / "qr.png"

#: Safety cap for uploaded QR images (Bot API photos are far below this).
MAX_QR_BYTES = 10 * 1024 * 1024


def resolve_qr_path() -> Optional[Path]:
    """
    Return the path to the QR image to send, or None if not configured.

    Priority:
      1. QR uploaded via /setqr  ->  data/qr.png
      2. UPI_QR_PATH from .env
    """
    if SAVED_QR_PATH.is_file() and SAVED_QR_PATH.stat().st_size > 0:
        return SAVED_QR_PATH

    env_path = os.getenv("UPI_QR_PATH", "").strip()
    if env_path:
        p = Path(env_path).expanduser()
        if p.is_file():
            return p
        logger.warning("UPI_QR_PATH is set but the file does not exist: %s", p)
    return None


def save_qr_bytes(content: bytes) -> Path:
    """Persist an uploaded QR image to data/qr.png and return the path."""
    if not content:
        raise ValueError("Empty QR image data.")
    if len(content) > MAX_QR_BYTES:
        raise ValueError("QR image too large (max 10 MB).")

    SAVED_QR_PATH.parent.mkdir(parents=True, exist_ok=True)
    SAVED_QR_PATH.write_bytes(content)
    logger.info("Saved uploaded QR image to %s (%d bytes)", SAVED_QR_PATH, len(content))
    return SAVED_QR_PATH


def clear_saved_qr() -> bool:
    """Delete the uploaded QR image. Returns True if a file was removed."""
    if SAVED_QR_PATH.is_file():
        SAVED_QR_PATH.unlink()
        logger.info("Removed saved QR image at %s", SAVED_QR_PATH)
        return True
    return False


async def send_order_qr(bot, chat_id: int, order_id: int, total: float) -> bool:
    """
    Send the payment QR image to a customer chat with a friendly caption.

    Returns True if the photo was sent, False if no QR is configured or the
    send failed (failures are logged, never raised — the order flow must not
    break because of a missing QR).
    """
    from bot.messages import format_qr_payment_caption

    qr_path = resolve_qr_path()
    if not qr_path:
        logger.warning("No payment QR configured; skipping QR send for order #%d", order_id)
        return False

    caption = format_qr_payment_caption(order_id, total)
    try:
        with qr_path.open("rb") as fh:
            await bot.send_photo(
                chat_id=chat_id,
                photo=fh,
                caption=caption,
                parse_mode=ParseMode.MARKDOWN,
            )
        logger.info("Sent payment QR for order #%d to chat %s", order_id, chat_id)
        return True
    except Exception as exc:
        logger.warning("Failed to send QR for order #%d to %s: %s", order_id, chat_id, exc)
        return False
