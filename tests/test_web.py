"""
tests/test_web.py — Unit tests for Phase 3 web dashboard routes and authentication.
"""

import json
import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

from web.app import app
from web.auth import get_dashboard_password


@pytest.fixture
def temp_db(tmp_path: Path) -> Iterator[str]:
    """Set up an isolated temporary SQLite DB with test schema and seed items."""
    db_file = tmp_path / "test_sollunga_web.db"
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

    # Seed
    items = [
        ("rice", json.dumps(["arisi", "rice"]), "kg", 55.0, 50.0),
        ("sugar", json.dumps(["sakkarai"]), "kg", 45.0, 2.0),  # Low stock
    ]
    con.executemany(
        "INSERT INTO items (name, aliases, unit, price, stock) VALUES (?, ?, ?, ?, ?)",
        items,
    )
    con.commit()
    con.close()

    with patch("core.db._DB_PATH", str(db_file)):
        yield str(db_file)


@pytest.fixture
def client(temp_db: str) -> TestClient:
    """Test client with mocked database."""
    assert Path(temp_db).is_file()
    return TestClient(app)


@pytest.fixture
def auth_client(client: TestClient) -> TestClient:
    """Test client pre-authenticated with valid session cookie."""
    client.post("/login", data={"password": get_dashboard_password()})
    return client


class TestAuthentication:
    def test_unauthenticated_redirects_to_login(self, client: TestClient) -> None:
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_login_page_renders(self, client: TestClient) -> None:
        response = client.get("/login")
        assert response.status_code == 200
        assert "Owner Password" in response.text

    def test_login_invalid_password(self, client: TestClient) -> None:
        response = client.post("/login", data={"password": "wrongpassword"})
        assert response.status_code == 401
        assert "Invalid owner password" in response.text

    def test_login_valid_password(self, client: TestClient) -> None:
        valid_pwd = get_dashboard_password()
        response = client.post(
            "/login",
            data={"password": valid_pwd},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/"
        assert response.headers.get("set-cookie")


class TestDashboardPages:
    def test_home_page_renders_with_stats(self, auth_client: TestClient) -> None:
        response = auth_client.get("/")
        assert response.status_code == 200
        assert "Today&#39;s Orders" in response.text or "Today's Orders" in response.text
        assert "Today&#39;s Sales" in response.text or "Today's Sales" in response.text
        assert "Sugar" in response.text  # Sugar is low stock

    def test_items_page_list(self, auth_client: TestClient) -> None:
        response = auth_client.get("/items")
        assert response.status_code == 200
        assert "Rice" in response.text
        assert "Sugar" in response.text

    def test_add_new_item_flow(self, auth_client: TestClient) -> None:
        # Render form
        resp_form = auth_client.get("/items/new")
        assert resp_form.status_code == 200

        # Post new item
        resp_post = auth_client.post(
            "/items/new",
            data={
                "name": "coffee",
                "unit": "packet",
                "price": 35.0,
                "stock": 10.0,
                "aliases": "kaapi, filter coffee",
            },
            follow_redirects=True,
        )
        assert resp_post.status_code == 200
        assert "Coffee" in resp_post.text

    def test_edit_item_flow(self, auth_client: TestClient) -> None:
        # Post edit for rice (id 1)
        resp_edit = auth_client.post(
            "/items/edit/1",
            data={
                "price": 62.0,
                "stock": 80.0,
                "unit": "kg",
                "aliases": "arisi, ponni rice",
            },
            follow_redirects=True,
        )
        assert resp_edit.status_code == 200
        assert "62.00" in resp_edit.text

    def test_delete_item_flow(self, auth_client: TestClient) -> None:
        resp_delete = auth_client.post("/items/delete/2", follow_redirects=True)
        assert resp_delete.status_code == 200
        # Sugar should no longer be listed
        assert "Sugar" not in resp_delete.text


class TestOrdersManagement:
    def test_orders_page_and_status_transition(self, auth_client: TestClient, temp_db: str) -> None:
        con = sqlite3.connect(temp_db)
        cur = con.cursor()
        cur.execute("INSERT INTO orders (customer_id, status, total) VALUES ('98765', 'confirmed', 110.0)")
        ord_id = cur.lastrowid
        cur.execute("INSERT INTO order_items (order_id, item_id, quantity, unit_price) VALUES (?, 1, 2.0, 55.0)", (ord_id,))
        con.commit()
        con.close()

        # View orders
        resp = auth_client.get("/orders")
        assert resp.status_code == 200
        assert f"#{ord_id}" in resp.text
        assert "confirmed" in resp.text

        # Change status to accepted
        resp_status = auth_client.post(
            f"/orders/{ord_id}/status",
            data={"status": "accepted"},
            follow_redirects=True,
        )
        assert resp_status.status_code == 200
        assert "accepted" in resp_status.text


class TestSalesReports:
    def _insert_order(
        self,
        db: str,
        total: float,
        status: str = "confirmed",
        created_at: str | None = None,
    ) -> None:
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

    def test_sales_page_requires_auth(self, client: TestClient) -> None:
        response = client.get("/sales", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_sales_page_renders(self, auth_client: TestClient) -> None:
        response = auth_client.get("/sales")
        assert response.status_code == 200
        assert "Total Sold" in response.text
        assert "This Week" in response.text
        assert "This Month" in response.text
        assert "Single-Day Report" in response.text

    def test_reset_button_zeroes_total(self, auth_client: TestClient, temp_db: str) -> None:
        self._insert_order(temp_db, 200.0, "confirmed")

        before = auth_client.get("/sales")
        assert "200.00" in before.text

        reset = auth_client.post("/sales/reset", follow_redirects=False)
        assert reset.status_code == 303
        assert reset.headers["location"] == "/sales?reset=1"

        after = auth_client.get("/sales?reset=1")
        assert "Sales reset to" in after.text
        assert "200.00" in after.text  # all-time history is still shown

        # Every summary figure (incl. today/week/month) is zeroed.
        from core.inventory import get_sales_summary
        s = get_sales_summary()
        assert s["today"] == 0.0
        assert s["week"] == 0.0
        assert s["month"] == 0.0
        assert s["total_since_reset"] == 0.0
        assert s["total_all_time"] == 200.0

    def test_single_day_lookup(self, auth_client: TestClient, temp_db: str) -> None:
        self._insert_order(temp_db, 120.0, "confirmed", "2026-01-15 10:00:00")
        self._insert_order(temp_db, 80.0, "confirmed", "2026-01-16 10:00:00")

        response = auth_client.get("/sales?day=2026-01-15")
        assert response.status_code == 200
        assert "2026-01-15" in response.text
        assert "120.00" in response.text

    def test_invalid_day_shows_error(self, auth_client: TestClient) -> None:
        response = auth_client.get("/sales?day=not-a-date")
        assert response.status_code == 200
        assert "not a valid date" in response.text

    def test_clear_history_requires_auth(self, client: TestClient) -> None:
        response = client.post("/sales/clear-history", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_clear_history_wipes_orders_and_keeps_items(
        self,
        auth_client: TestClient,
        temp_db: str,
    ) -> None:
        self._insert_order(temp_db, 100.0, "confirmed")
        self._insert_order(temp_db, 250.0, "delivered")

        response = auth_client.post("/sales/clear-history", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/sales?cleared=1"

        page = auth_client.get("/sales?cleared=1")
        assert "All sales history cleared" in page.text

        con = sqlite3.connect(temp_db)
        assert con.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM order_items").fetchone()[0] == 0
        # Items catalog survives.
        assert con.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2
        con.close()
