"""
tests/test_phase5.py — Tests for Phase 5 features:
- Multi-shop database support and routing
- Multi-shop customer shop selection via service
- Health endpoint (/health)
- LLM resilience (retries, fallback provider, bad input defense)
"""

import json
import sqlite3
import pytest
from unittest.mock import MagicMock, patch

from core import db, inventory, order
from core.channel import FakeChannel
from core.service import handle_customer_text
from core.llm import extract_order_items
from fastapi.testclient import TestClient
from web.app import app


@pytest.fixture
def test_db(monkeypatch, tmp_path):
    """Create a temporary multi-shop database for testing."""
    db_file = str(tmp_path / "test_phase5.db")
    monkeypatch.setattr(db, "_DB_PATH", db_file)
    monkeypatch.setenv("DB_PATH", db_file)

    conn = sqlite3.connect(db_file)
    with open("data/schema.sql") as f:
        conn.executescript(f.read())

    # Insert two test shops
    cursor = conn.cursor()
    cursor.execute("INSERT INTO shops (id, name, slug, owner_id, is_active) VALUES (1, 'Shop One', 'shop-one', '111', 1)")
    cursor.execute("INSERT INTO shops (id, name, slug, owner_id, is_active) VALUES (2, 'Shop Two', 'shop-two', '222', 1)")

    # Insert items for each shop
    cursor.execute(
        "INSERT INTO items (id, shop_id, name, aliases, unit, price, stock) VALUES (1, 1, 'Rice', '[\"arisi\"]', 'kg', 60.0, 50)"
    )
    cursor.execute(
        "INSERT INTO items (id, shop_id, name, aliases, unit, price, stock) VALUES (2, 2, 'Wheat', '[\"godhumai\"]', 'kg', 40.0, 30)"
    )
    conn.commit()
    conn.close()
    return db_file


def test_multi_shop_db_queries(test_db):
    """Test db helpers for multi-shop operations."""
    shops = db.get_all_shops()
    assert len(shops) == 2
    assert shops[0]["name"] == "Shop One"
    assert shops[1]["name"] == "Shop Two"

    shop1 = db.get_shop_by_id(1)
    assert shop1["name"] == "Shop One"

    # Default shop for customer
    customer_shop = db.get_customer_shop_id("cust123")
    assert customer_shop == 1

    # Switch shop
    db.set_customer_shop_id("cust123", 2)
    assert db.get_customer_shop_id("cust123") == 2


def test_items_isolated_by_shop(test_db):
    """Verify items are isolated between shops."""
    items_shop1 = db.get_all_items(shop_id=1)
    assert len(items_shop1) == 1
    assert items_shop1[0]["name"] == "Rice"

    items_shop2 = db.get_all_items(shop_id=2)
    assert len(items_shop2) == 1
    assert items_shop2[0]["name"] == "Wheat"


def test_order_creation_per_shop(test_db):
    """Verify order creation and totals respect shop_id."""
    draft = order.OrderDraft(
        lines=[
            order.LineItem(
                item_id=1,
                item_name="Rice",
                unit="kg",
                unit_price=60.0,
                requested_qty=2.0,
                offered_qty=2.0,
            )
        ],
        total=120.0,
    )

    order_id = order.confirm_order("cust123", draft, shop_id=1)
    assert order_id > 0

    todays_orders = inventory.get_todays_orders(shop_id=1)
    assert len(todays_orders) == 1
    assert todays_orders[0].order_id == order_id

    # Shop 2 has no orders
    assert len(inventory.get_todays_orders(shop_id=2)) == 0


@pytest.mark.asyncio
async def test_service_shop_switching(test_db):
    """Test switching shops via OrderService / handle_customer_text."""
    channel = FakeChannel()

    # 1. Ask for shops list
    await handle_customer_text(channel, "cust_abc", "/shops")
    assert len(channel.sent_messages) == 1
    assert "Sollunga Shops" in channel.sent_messages[0]["text"]
    assert "Shop One" in channel.sent_messages[0]["text"]
    assert "Shop Two" in channel.sent_messages[0]["text"]

    # 2. Switch to shop 2
    await handle_customer_text(channel, "cust_abc", "/shop 2")
    assert len(channel.sent_messages) == 2
    assert "Shop Two" in channel.sent_messages[1]["text"]
    assert db.get_customer_shop_id("cust_abc") == 2


def test_health_endpoint(test_db):
    """Test /health API endpoint returns system readiness."""
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"
    assert data["total_shops"] == 2
    assert data["total_items"] == 2
    assert "channels" in data


def test_llm_resilience_fallback(monkeypatch):
    """Verify primary failure triggers secondary fallback provider."""
    # Mock primary client to throw exception
    primary_client = MagicMock()
    primary_client.chat.completions.create.side_effect = Exception("Primary quota exhausted / timeout")

    # Mock fallback client to succeed
    fallback_client = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = '[{"item": "sugar", "qty": 1, "unit": "kg"}]'
    fallback_resp = MagicMock()
    fallback_resp.choices = [fake_choice]
    fallback_client.chat.completions.create.return_value = fallback_resp

    monkeypatch.setattr("core.llm._get_client", lambda: primary_client)
    monkeypatch.setattr("core.llm._get_fallback_client", lambda: fallback_client)
    monkeypatch.setattr("core.llm._FALLBACK_BASE_URL", "https://fallback.api")
    monkeypatch.setattr("core.llm._FALLBACK_API_KEY", "fallback_key")
    monkeypatch.setattr("core.llm._MAX_RETRIES", 1)

    result = extract_order_items("oru kg sugar venum")
    assert len(result) == 1
    assert result[0]["item"] == "sugar"
    assert result[0]["qty"] == 1.0


def test_llm_defense_on_malformed_output(monkeypatch):
    """Verify unexpected non-JSON output returns empty list without crashing."""
    primary_client = MagicMock()
    fake_choice = MagicMock()
    fake_choice.message.content = "Sorry I cannot help with that request!"
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    primary_client.chat.completions.create.return_value = fake_resp

    monkeypatch.setattr("core.llm._get_client", lambda: primary_client)
    monkeypatch.setattr("core.llm._get_fallback_client", lambda: None)
    monkeypatch.setattr("core.llm._MAX_RETRIES", 1)

    result = extract_order_items("random bad output")
    assert result == []
