"""
tests/test_inventory.py — Unit tests for Phase 2 owner inventory & order management logic.
"""

import json
import sqlite3
import tempfile
import pytest
from unittest.mock import patch

from core.inventory import (
    StockRow,
    add_new_item,
    add_stock,
    get_low_stock_items,
    get_order_detail,
    get_stock_list,
    get_todays_orders,
    get_todays_sales_total,
    set_price,
    update_order_status,
)


@pytest.fixture
def temp_db(tmp_path):
    """Set up an isolated temporary SQLite DB with test schema and seed items."""
    db_file = tmp_path / "test_sollunga.db"
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

    # Seed data
    items = [
        ("rice", json.dumps(["arisi", "rice"]), "kg", 55.0, 20.0),
        ("sugar", json.dumps(["sakkarai", "sugar"]), "kg", 45.0, 2.0),  # Low stock
        ("oil", json.dumps(["ennai", "oil"]), "litre", 150.0, 3.0),    # Low stock
    ]
    con.executemany(
        "INSERT INTO items (name, aliases, unit, price, stock) VALUES (?, ?, ?, ?, ?)",
        items,
    )
    con.commit()
    con.close()

    with patch("core.db._DB_PATH", str(db_file)):
        yield str(db_file)


class TestStockListAndAlerts:
    def test_get_stock_list(self, temp_db):
        stocks = get_stock_list()
        assert len(stocks) == 3
        names = [s.name for s in stocks]
        assert names == ["oil", "rice", "sugar"]  # sorted alphabetically

    def test_low_stock_detection(self, temp_db):
        low_items = get_low_stock_items(threshold=3)
        assert len(low_items) == 2
        low_names = {s.name for s in low_items}
        assert low_names == {"sugar", "oil"}  # sugar has 2, oil has 3


class TestAddStockAndSetPrice:
    def test_add_stock_success(self, temp_db):
        updated = add_stock("rice", 15.0)
        assert updated.name == "rice"
        assert updated.stock == 35.0  # 20 + 15

    def test_add_stock_using_alias(self, temp_db):
        updated = add_stock("arisi", 10.0)
        assert updated.name == "rice"
        assert updated.stock == 30.0

    def test_add_stock_negative_raises(self, temp_db):
        with pytest.raises(ValueError, match="positive"):
            add_stock("rice", -5.0)

    def test_add_stock_unknown_item_raises(self, temp_db):
        with pytest.raises(ValueError, match="not found"):
            add_stock("biscuits", 10.0)

    def test_set_price_success(self, temp_db):
        updated = set_price("sugar", 52.0)
        assert updated.name == "sugar"
        assert updated.price == 52.0

    def test_set_price_using_alias(self, temp_db):
        updated = set_price("ennai", 160.0)
        assert updated.name == "oil"
        assert updated.price == 160.0

    def test_set_price_invalid_raises(self, temp_db):
        with pytest.raises(ValueError, match="positive"):
            set_price("sugar", 0)


class TestAddNewItem:
    def test_add_new_item_success(self, temp_db):
        new_row = add_new_item(
            name="tea powder",
            unit="packet",
            price=30.0,
            stock=15.0,
            aliases=["tea", "chaya"],
        )
        assert new_row.name == "tea powder"
        assert new_row.unit == "packet"
        assert new_row.price == 30.0
        assert new_row.stock == 15.0
        assert "tea powder" in new_row.aliases
        assert "tea" in new_row.aliases

    def test_add_duplicate_item_raises(self, temp_db):
        with pytest.raises(ValueError, match="already exists"):
            add_new_item(
                name="rice",
                unit="kg",
                price=60.0,
                stock=10.0,
                aliases=["rice"],
            )

    def test_add_item_invalid_values(self, temp_db):
        with pytest.raises(ValueError, match="Price must be positive"):
            add_new_item("soap", "piece", -10.0, 5.0, [])
        with pytest.raises(ValueError, match="Stock cannot be negative"):
            add_new_item("soap", "piece", 25.0, -1.0, [])


class TestOrderManagement:
    def test_order_status_update_and_detail(self, temp_db):
        con = sqlite3.connect(temp_db)
        cur = con.cursor()
        cur.execute(
            "INSERT INTO orders (customer_id, status, total) VALUES ('12345', 'confirmed', 110.0)"
        )
        order_id = cur.lastrowid
        cur.execute(
            "INSERT INTO order_items (order_id, item_id, quantity, unit_price) VALUES (?, 1, 2.0, 55.0)",
            (order_id,),
        )
        con.commit()
        con.close()

        detail = get_order_detail(order_id)
        assert detail is not None
        assert detail.order_id == order_id
        assert detail.customer_id == "12345"
        assert detail.status == "confirmed"
        assert detail.total == 110.0
        assert len(detail.items) == 1
        assert detail.items[0]["name"] == "rice"

        # Update status to accepted
        res = update_order_status(order_id, "accepted")
        assert res is True
        updated_detail = get_order_detail(order_id)
        assert updated_detail.status == "accepted"

        # Update status to delivered
        res2 = update_order_status(order_id, "delivered")
        assert res2 is True
        assert get_order_detail(order_id).status == "delivered"

    def test_todays_orders_and_sales(self, temp_db):
        con = sqlite3.connect(temp_db)
        cur = con.cursor()
        cur.execute(
            "INSERT INTO orders (customer_id, status, total) VALUES ('111', 'confirmed', 150.0)"
        )
        cur.execute(
            "INSERT INTO orders (customer_id, status, total) VALUES ('222', 'delivered', 250.0)"
        )
        cur.execute(
            "INSERT INTO orders (customer_id, status, total) VALUES ('333', 'rejected', 50.0)"
        )
        con.commit()
        con.close()

        orders = get_todays_orders()
        assert len(orders) == 3

        # Sales should only count confirmed, accepted, delivered (150 + 250 = 400), not rejected
        sales = get_todays_sales_total()
        assert sales == pytest.approx(400.0)
