"""
tests/test_inventory.py — Unit tests for Phase 2 owner inventory & order management logic.
"""

import json
import sqlite3
import tempfile
import pytest
from datetime import date
from unittest.mock import patch

from core.inventory import (
    StockRow,
    add_new_item,
    add_stock,
    clear_sales_history,
    get_low_stock_items,
    get_order_detail,
    get_sales_for_date,
    get_sales_reset_at,
    get_sales_summary,
    get_stock_list,
    get_todays_orders,
    get_todays_sales_total,
    reset_sales,
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


class TestSalesReporting:
    def _insert_order(self, db, total, status="confirmed", created_at=None):
        con = sqlite3.connect(db)
        if created_at:
            con.execute(
                "INSERT INTO orders (customer_id, status, total, created_at) VALUES ('1', ?, ?, ?)",
                (status, total, created_at),
            )
        else:
            con.execute(
                "INSERT INTO orders (customer_id, status, total) VALUES ('1', ?, ?)",
                (status, total),
            )
        con.commit()
        con.close()

    def test_summary_counts_only_sold_statuses(self, temp_db):
        self._insert_order(temp_db, 150.0, "confirmed")
        self._insert_order(temp_db, 250.0, "delivered")
        self._insert_order(temp_db, 999.0, "rejected")
        self._insert_order(temp_db, 42.0, "pending")

        s = get_sales_summary()
        assert s["today"] == pytest.approx(400.0)
        assert s["week"] == pytest.approx(400.0)
        assert s["month"] == pytest.approx(400.0)
        assert s["total_all_time"] == pytest.approx(400.0)
        assert s["total_since_reset"] == pytest.approx(400.0)
        assert s["reset_at"] is None

    def test_reset_zeroes_all_summary_but_keeps_history(self, temp_db):
        self._insert_order(temp_db, 200.0, "confirmed")
        before = get_sales_summary()
        assert before["total_since_reset"] == pytest.approx(200.0)
        assert before["today"] == pytest.approx(200.0)

        ts = reset_sales()
        assert ts

        after = get_sales_summary()
        # Every summary window is zeroed...
        assert after["today"] == pytest.approx(0.0)
        assert after["week"] == pytest.approx(0.0)
        assert after["month"] == pytest.approx(0.0)
        assert after["total_since_reset"] == pytest.approx(0.0)
        # ...but history is never lost.
        assert after["total_all_time"] == pytest.approx(200.0)
        assert after["reset_at"] == ts
        assert get_sales_reset_at() == ts
        # The home-page "Today's Sales" figure respects the reset too.
        assert get_todays_sales_total() == pytest.approx(0.0)

    def test_new_sales_after_reset_count_again(self, temp_db):
        from core.db import set_setting
        from core.inventory import SALES_RESET_KEY

        # Deterministic baseline at a fixed moment today.
        today = date.today().isoformat()
        set_setting(SALES_RESET_KEY, f"{today} 00:00:01")

        # Before baseline -> excluded.
        self._insert_order(temp_db, 100.0, "confirmed", f"{today} 00:00:00")
        # After baseline -> counted.
        self._insert_order(temp_db, 60.0, "confirmed", f"{today} 12:00:00")

        after = get_sales_summary()
        assert after["today"] == pytest.approx(60.0)
        assert after["week"] == pytest.approx(60.0)
        assert after["month"] == pytest.approx(60.0)
        assert after["total_since_reset"] == pytest.approx(60.0)
        assert after["total_all_time"] == pytest.approx(160.0)

    def test_orders_before_reset_are_excluded(self, temp_db):
        self._insert_order(temp_db, 500.0, "confirmed", "2020-01-01 09:00:00")
        reset_sales()
        s = get_sales_summary()
        assert s["today"] == pytest.approx(0.0)
        assert s["total_since_reset"] == pytest.approx(0.0)
        assert s["total_all_time"] == pytest.approx(500.0)

    def test_sales_for_date_with_items(self, temp_db):
        con = sqlite3.connect(temp_db)
        con.execute(
            "INSERT INTO orders (customer_id, status, total, created_at) "
            "VALUES ('1', 'confirmed', 110.0, '2026-02-10 12:00:00')"
        )
        order_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.execute(
            "INSERT INTO order_items (order_id, item_id, quantity, unit_price) VALUES (?, 1, 2.0, 55.0)",
            (order_id,),
        )
        con.commit()
        con.close()

        report = get_sales_for_date("2026-02-10")
        assert report["date"] == "2026-02-10"
        assert report["total"] == pytest.approx(110.0)
        assert report["order_count"] == 1
        assert len(report["items"]) == 1
        assert report["items"][0]["name"] == "rice"
        assert report["items"][0]["qty"] == pytest.approx(2.0)
        assert report["items"][0]["amount"] == pytest.approx(110.0)

    def test_sales_for_date_empty(self, temp_db):
        report = get_sales_for_date("1999-01-01")
        assert report["total"] == 0.0
        assert report["order_count"] == 0
        assert report["items"] == []

    def test_clear_sales_history_keeps_items(self, temp_db):
        # Two orders, one with a line item.
        con = sqlite3.connect(temp_db)
        con.execute("INSERT INTO orders (customer_id, status, total) VALUES ('1', 'confirmed', 100.0)")
        oid = con.execute("SELECT last_insert_rowid()").fetchone()[0]
        con.execute(
            "INSERT INTO order_items (order_id, item_id, quantity, unit_price) VALUES (?, 1, 2.0, 50.0)",
            (oid,),
        )
        con.commit()
        con.close()
        self._insert_order(temp_db, 50.0, "delivered")
        reset_sales()
        assert get_sales_reset_at() is not None

        result = clear_sales_history()

        assert result["orders_deleted"] == 2
        assert result["order_items_deleted"] == 1
        # Baseline cleared -> brand-new state.
        assert get_sales_reset_at() is None
        summary = get_sales_summary()
        assert summary["today"] == 0.0
        assert summary["total_all_time"] == 0.0
        assert get_todays_orders() == []
        # Catalog is untouched.
        assert len(get_stock_list()) == 3

        # Order numbering restarts at 1.
        self._insert_order(temp_db, 20.0, "confirmed")
        assert get_todays_orders()[0].order_id == 1
