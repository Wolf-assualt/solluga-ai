"""
tests/test_channels.py — Unit tests for Phase 4 Channel abstraction, WhatsApp parsing, and voice notes.
"""

import json
import sqlite3
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from core.channel import Button, FakeChannel
from core.service import (
    handle_customer_text,
    handle_order_confirmation,
    handle_order_cancellation,
    get_user_draft,
    set_user_draft,
    clear_user_draft,
)
from core.whatsapp import WhatsAppChannel, parse_whatsapp_webhook
from core.transcription import TranscriptionResult, _parse_transcription_response
from web.app import app


@pytest.fixture
def temp_db(tmp_path):
    """Set up an isolated temporary SQLite DB with test schema and seed items."""
    db_file = tmp_path / "test_sollunga_channels.db"
    con = sqlite3.connect(str(db_file))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")

    # Schema
    con.executescript(
        """
        CREATE TABLE items (
            id       INTEGER PRIMARY KEY AUTOINCREMENT,
            name     TEXT    NOT NULL UNIQUE,
            aliases  TEXT    NOT NULL DEFAULT '[]',
            unit     TEXT    NOT NULL,
            price    REAL    NOT NULL,
            stock    REAL    NOT NULL DEFAULT 0
        );

        CREATE TABLE orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id TEXT    NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'pending',
            total       REAL    NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
        );

        CREATE TABLE order_items (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
            item_id    INTEGER NOT NULL REFERENCES items(id),
            quantity   REAL    NOT NULL,
            unit_price REAL    NOT NULL
        );
        """
    )

    items = [
        ("rice", json.dumps(["arisi", "rice"]), "kg", 55.0, 100.0),
        ("sugar", json.dumps(["sakkarai"]), "kg", 45.0, 50.0),
    ]
    con.executemany(
        "INSERT INTO items (name, aliases, unit, price, stock) VALUES (?, ?, ?, ?, ?)",
        items,
    )
    con.commit()
    con.close()

    with patch("core.db._DB_PATH", str(db_file)):
        yield str(db_file)


# ---------------------------------------------------------------------------
# Channel abstraction tests using FakeChannel
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fake_channel_order_flow(temp_db):
    fake_ch = FakeChannel("test_channel")
    customer_id = "user_999"

    # Mock LLM extraction
    with patch("core.order.extract_order_items", return_value=[{"item": "arisi", "qty": 2, "unit": "kg"}]):
        await handle_customer_text(fake_ch, customer_id, "2 kg arisi venum")

    # Check outbound messages sent to channel
    assert len(fake_ch.sent_messages) == 1
    msg = fake_ch.sent_messages[0]
    assert msg["type"] == "buttons"
    assert msg["recipient_id"] == customer_id
    assert "₹110.00" in msg["text"]
    assert any(b["payload"] == "order:confirm" for b in msg["buttons"])

    # Confirm order
    owner_ch = FakeChannel("owner_channel")
    order_id = await handle_order_confirmation(
        channel=fake_ch,
        customer_id=customer_id,
        customer_display_name="Test Customer",
        original_text="2 kg arisi",
        owner_channel=owner_ch,
        owner_id="owner_1",
    )
    assert order_id is not None
    assert order_id > 0

    # Customer received confirmation
    assert len(fake_ch.sent_messages) == 2
    assert "confirm" in fake_ch.sent_messages[1]["text"].lower()

    # Owner received notification with action buttons
    assert len(owner_ch.sent_messages) == 1
    assert f"#{order_id}" in owner_ch.sent_messages[0]["text"]
    assert any("accept" in b["payload"].lower() for b in owner_ch.sent_messages[0]["buttons"])


@pytest.mark.asyncio
async def test_fake_channel_cancel_order(temp_db):
    fake_ch = FakeChannel("test_channel")
    customer_id = "user_888"

    with patch("core.order.extract_order_items", return_value=[{"item": "sugar", "qty": 1, "unit": "kg"}]):
        await handle_customer_text(fake_ch, customer_id, "1 kg sugar")

    assert get_user_draft(fake_ch.channel_name, customer_id) is not None

    await handle_order_cancellation(fake_ch, customer_id, "cancel")
    assert get_user_draft(fake_ch.channel_name, customer_id) is None
    assert len(fake_ch.sent_messages) == 2
    assert "cancel" in fake_ch.sent_messages[1]["text"].lower()


# ---------------------------------------------------------------------------
# WhatsApp webhook parsing & verification
# ---------------------------------------------------------------------------

def test_whatsapp_webhook_verification():
    client = TestClient(app)
    # Correct verify token
    res = client.get(
        "/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "sollunga_verify_token",
            "hub.challenge": "12345678",
        },
    )
    assert res.status_code == 200
    assert res.text == "12345678"

    # Invalid verify token
    res_bad = client.get(
        "/whatsapp/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "wrong_token",
            "hub.challenge": "12345678",
        },
    )
    assert res_bad.status_code == 403


def test_parse_whatsapp_payload():
    sample_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [{"wa_id": "919876543210", "profile": {"name": "Ravi"}}],
                            "messages": [
                                {
                                    "from": "919876543210",
                                    "id": "wamid.123",
                                    "type": "text",
                                    "text": {"body": "2 kg rice venum"},
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }

    events = parse_whatsapp_webhook(sample_payload)
    assert len(events) == 1
    assert events[0]["from"] == "919876543210"
    assert events[0]["name"] == "Ravi"
    assert events[0]["type"] == "text"
    assert events[0]["text"] == "2 kg rice venum"


# ---------------------------------------------------------------------------
# Voice notes transcription parsing
# ---------------------------------------------------------------------------

def test_transcription_parser_confident():
    raw_json = json.dumps({
        "transcript": "2 kg arisi kudunga",
        "is_confident": True,
        "language": "tanglish",
        "clarification_needed": False,
    })
    result = _parse_transcription_response(raw_json)
    assert result.text == "2 kg arisi kudunga"
    assert result.is_confident is True
    assert result.clarification_prompt is None


def test_transcription_parser_unsure_clarification_prompt():
    raw_json = json.dumps({
        "transcript": "rendu kilo ...",
        "is_confident": False,
        "language": "tamil",
        "clarification_needed": True,
    })
    result = _parse_transcription_response(raw_json)
    assert result.text == "rendu kilo ..."
    assert result.is_confident is False
    assert result.clarification_prompt is not None
    assert "rendu kilo ..." in result.clarification_prompt
