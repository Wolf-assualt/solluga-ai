"""
bot/main.py — Entry point for the Sollunga Telegram bot.
"""

import logging
import os
import sys
from pathlib import Path

# Ensure project root is in sys.path regardless of execution directory
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dotenv import load_dotenv
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from bot.handlers import (
    cmd_start,
    handle_callback,
    handle_order_message,
    handle_voice_message,
)
from bot.owner_handlers import (
    cmd_addstock,
    cmd_orders,
    cmd_sales,
    cmd_setprice,
    cmd_stock,
    get_additem_conversation_handler,
    handle_owner_order_callback,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set. Check your .env file.")

    app = Application.builder().token(token).build()

    # Owner Handlers (Phase 2)
    app.add_handler(CommandHandler("stock", cmd_stock))
    app.add_handler(CommandHandler("addstock", cmd_addstock))
    app.add_handler(CommandHandler("setprice", cmd_setprice))
    app.add_handler(CommandHandler("orders", cmd_orders))
    app.add_handler(CommandHandler("sales", cmd_sales))
    app.add_handler(get_additem_conversation_handler())
    app.add_handler(CallbackQueryHandler(handle_owner_order_callback, pattern=r"^owner:"))

    # Customer Handlers (Phase 1 & 4)
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(handle_callback, pattern=r"^order:"))
    app.add_handler(
        MessageHandler(filters.VOICE | filters.AUDIO, handle_voice_message)
    )
    app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_order_message)
    )

    logger.info("🤖 Sollunga bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
