"""
tests/test_qr.py — Unit tests for payment QR storage, resolution, and delivery.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

import bot.qr as qr
from bot import handlers as bot_handlers
from bot.keyboards import CALLBACK_PAYNOW, pay_now_keyboard
from bot.messages import format_qr_payment_caption


@pytest.fixture
def qr_paths(tmp_path, monkeypatch):
    """Point the QR module at isolated temp paths and clear the env override."""
    saved = tmp_path / "data" / "qr.png"
    monkeypatch.setattr(qr, "SAVED_QR_PATH", saved)
    monkeypatch.delenv("UPI_QR_PATH", raising=False)
    return saved


# ---------------------------------------------------------------------------
# resolve_qr_path — priority: /setqr upload > UPI_QR_PATH env
# ---------------------------------------------------------------------------

def test_resolve_prefers_uploaded_qr(qr_paths, monkeypatch):
    qr_paths.parent.mkdir(parents=True)
    qr_paths.write_bytes(b"uploaded-qr")

    monkeypatch.setenv("UPI_QR_PATH", "/nonexistent/env-qr.png")
    assert qr.resolve_qr_path() == qr_paths


def test_resolve_falls_back_to_env_path(qr_paths, tmp_path, monkeypatch):
    env_qr = tmp_path / "env-qr.png"
    env_qr.write_bytes(b"env-qr")
    monkeypatch.setenv("UPI_QR_PATH", str(env_qr))

    assert qr.resolve_qr_path() == env_qr


def test_resolve_returns_none_when_not_configured(qr_paths):
    assert qr.resolve_qr_path() is None


def test_resolve_returns_none_when_env_file_missing(qr_paths, monkeypatch):
    monkeypatch.setenv("UPI_QR_PATH", "/nonexistent/env-qr.png")
    assert qr.resolve_qr_path() is None


# ---------------------------------------------------------------------------
# save / clear uploaded QR
# ---------------------------------------------------------------------------

def test_save_qr_bytes_creates_file(qr_paths):
    saved = qr.save_qr_bytes(b"fake-image-bytes")
    assert saved == qr_paths
    assert saved.read_bytes() == b"fake-image-bytes"


def test_save_qr_bytes_rejects_empty(qr_paths):
    with pytest.raises(ValueError):
        qr.save_qr_bytes(b"")


def test_save_qr_bytes_rejects_oversized(qr_paths, monkeypatch):
    monkeypatch.setattr(qr, "MAX_QR_BYTES", 10)
    with pytest.raises(ValueError):
        qr.save_qr_bytes(b"x" * 11)


def test_clear_saved_qr(qr_paths):
    assert qr.clear_saved_qr() is False  # nothing to clear

    qr.save_qr_bytes(b"fake-image-bytes")
    assert qr.clear_saved_qr() is True
    assert not qr_paths.exists()


# ---------------------------------------------------------------------------
# send_order_qr — sends photo when configured, no-ops otherwise
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_order_qr_sends_photo(qr_paths):
    qr.save_qr_bytes(b"fake-image-bytes")
    bot = AsyncMock()

    sent = await qr.send_order_qr(bot, chat_id=42, order_id=7, total=123.5)

    assert sent is True
    bot.send_photo.assert_awaited_once()
    kwargs = bot.send_photo.await_args.kwargs
    assert kwargs["chat_id"] == 42
    assert "#7" in kwargs["caption"]
    assert "₹123.50" in kwargs["caption"]


@pytest.mark.asyncio
async def test_send_order_qr_delivered_stage_caption(qr_paths):
    qr.save_qr_bytes(b"fake-image-bytes")
    bot = AsyncMock()

    sent = await qr.send_order_qr(bot, chat_id=42, order_id=9, total=80.0, stage="delivered")

    assert sent is True
    kwargs = bot.send_photo.await_args.kwargs
    assert "delivered" in kwargs["caption"]
    assert "#9" in kwargs["caption"]
    assert "₹80.00" in kwargs["caption"]


@pytest.mark.asyncio
async def test_send_order_qr_returns_false_when_not_configured(qr_paths):
    bot = AsyncMock()

    sent = await qr.send_order_qr(bot, chat_id=42, order_id=7, total=100.0)

    assert sent is False
    bot.send_photo.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_order_qr_swallows_send_errors(qr_paths):
    qr.save_qr_bytes(b"fake-image-bytes")
    bot = AsyncMock()
    bot.send_photo.side_effect = RuntimeError("telegram down")

    sent = await qr.send_order_qr(bot, chat_id=42, order_id=7, total=100.0)

    assert sent is False


# ---------------------------------------------------------------------------
# Pay Now button — on-demand QR
# ---------------------------------------------------------------------------

def test_pay_now_keyboard_builder():
    kb = pay_now_keyboard(5)
    (btn,) = kb.inline_keyboard[0]
    assert btn.text == "💳 Pay Now"
    assert btn.callback_data == f"{CALLBACK_PAYNOW}5"


@pytest.mark.asyncio
async def test_paynow_callback_sends_qr_on_tap(monkeypatch):
    """Tapping Pay Now sends the QR with the right stage — never automatically."""
    order = MagicMock()
    order.order_id = 9
    order.status = "delivered"
    order.total = 55.0
    monkeypatch.setattr(bot_handlers, "get_order_detail", lambda oid: order)

    qr_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(bot_handlers, "send_order_qr", qr_mock)

    query = AsyncMock()
    query.data = f"{CALLBACK_PAYNOW}9"
    query.message = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    update.effective_user = MagicMock(id=42)

    await bot_handlers.handle_callback(update, MagicMock())

    qr_mock.assert_awaited_once()
    args, kwargs = qr_mock.await_args
    assert args[0].__class__.__name__ == "MagicMock"  # bot
    assert args[1] == 42  # customer chat id (the tapper)
    assert args[2] == 9   # order id
    assert kwargs.get("stage") == "delivered"
    query.message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_paynow_callback_without_qr_configured(monkeypatch):
    """When no QR is set, the customer gets a friendly warning instead."""
    order = MagicMock()
    order.order_id = 9
    order.status = "accepted"
    order.total = 55.0
    monkeypatch.setattr(bot_handlers, "get_order_detail", lambda oid: order)
    monkeypatch.setattr(bot_handlers, "send_order_qr", AsyncMock(return_value=False))

    query = AsyncMock()
    query.data = f"{CALLBACK_PAYNOW}9"
    query.message = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    update.effective_user = MagicMock(id=42)

    await bot_handlers.handle_callback(update, MagicMock())

    query.message.reply_text.assert_awaited_once()
    assert "QR" in query.message.reply_text.await_args.args[0]


@pytest.mark.asyncio
async def test_paynow_callback_invalid_order(monkeypatch):
    monkeypatch.setattr(bot_handlers, "get_order_detail", lambda oid: None)

    query = AsyncMock()
    query.data = f"{CALLBACK_PAYNOW}999"
    query.message = AsyncMock()
    update = MagicMock()
    update.callback_query = query
    update.effective_user = MagicMock(id=42)

    await bot_handlers.handle_callback(update, MagicMock())

    query.message.reply_text.assert_awaited_once()
    assert "not found" in query.message.reply_text.await_args.args[0]


# ---------------------------------------------------------------------------
# Caption formatter
# ---------------------------------------------------------------------------

def test_format_qr_payment_caption():
    caption = format_qr_payment_caption(12, 250)
    assert "#12" in caption
    assert "₹250.00" in caption
    assert "UPI" in caption


def test_format_qr_payment_caption_delivered_stage():
    caption = format_qr_payment_caption(12, 250, stage="delivered")
    assert "#12" in caption
    assert "delivered" in caption
    assert "₹250.00" in caption
    assert "UPI" in caption
