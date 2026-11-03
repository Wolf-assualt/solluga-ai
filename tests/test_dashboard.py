"""
tests/test_dashboard.py — Tests for the /dashboard analytics page, its JSON API,
core/analytics.py aggregates, and the data/seed_demo.py sample-data guards.
"""

import importlib.util
import json
import sqlite3
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from core.analytics import get_dashboard_data
from web.app import app
from web.auth import get_dashboard_password

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = (ROOT / "data" / "schema.sql").read_text(encoding="utf-8")


def _insert_order(con, shop_id, status, lines, days_ago=0):
    """lines: [(item_id, qty, unit_price)] — total is computed here, like the app does."""
    total = sum(q * p for _, q, p in lines)
    cur = con.execute(
        "INSERT INTO orders (shop_id, customer_id, status, total, created_at) "
        "VALUES (?, 'c1', ?, ?, datetime('now', 'localtime', ?))",
        (shop_id, status, total, f"-{days_ago} days"),
    )
    for item_id, q, p in lines:
        con.execute(
            "INSERT INTO order_items (order_id, item_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
            (cur.lastrowid, item_id, q, p),
        )


@pytest.fixture
def full_db(tmp_path: Path) -> Iterator[str]:
    db_file = tmp_path / "dash.db"
    con = sqlite3.connect(str(db_file))
    con.executescript(SCHEMA)
    con.execute("INSERT INTO shops (id, name, slug) VALUES (1, 'Shop One', 'one'), (2, 'Shop Two', 'two')")
    con.executemany(
        "INSERT INTO items (id, shop_id, name, aliases, unit, price, stock) VALUES (?, ?, ?, '[]', ?, ?, ?)",
        [
            (1, 1, "rice", "kg", 50.0, 40.0),
            (2, 1, "oil", "litre", 150.0, 2.0),   # low stock
            (3, 2, "sugar", "kg", 40.0, 20.0),
        ],
    )
    _insert_order(con, 1, "delivered", [(1, 2, 50.0), (2, 1, 150.0)], days_ago=3)  # 250
    _insert_order(con, 1, "confirmed", [(1, 1, 50.0)], days_ago=0)                 # 50
    _insert_order(con, 1, "rejected", [(2, 5, 150.0)], days_ago=1)                 # not sold
    _insert_order(con, 2, "accepted", [(3, 3, 40.0)], days_ago=10)                 # 120
    _insert_order(con, 2, "pending", [(3, 1, 40.0)], days_ago=0)                   # not sold
    _insert_order(con, 1, "delivered", [(1, 10, 50.0)], days_ago=60)               # 500, outside window
    con.commit()
    con.close()
    with patch("core.db._DB_PATH", str(db_file)):
        yield str(db_file)


@pytest.fixture
def legacy_db(tmp_path: Path) -> Iterator[str]:
    """Pre-multi-shop schema: no shop_id columns and no shops table."""
    db_file = tmp_path / "legacy.db"
    con = sqlite3.connect(str(db_file))
    con.executescript(
        """
        CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT, aliases TEXT DEFAULT '[]',
                            unit TEXT, price REAL, stock REAL);
        CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id TEXT, status TEXT,
                             total REAL, created_at TEXT DEFAULT (datetime('now','localtime')));
        CREATE TABLE order_items (id INTEGER PRIMARY KEY, order_id INTEGER, item_id INTEGER,
                                  quantity REAL, unit_price REAL);
        INSERT INTO items VALUES (1, 'rice', '[]', 'kg', 55, 50);
        INSERT INTO orders (id, customer_id, status, total) VALUES (1, 'c', 'delivered', 110);
        INSERT INTO order_items VALUES (1, 1, 1, 2, 55);
        """
    )
    con.close()
    with patch("core.db._DB_PATH", str(db_file)):
        yield str(db_file)


@pytest.fixture
def empty_db(tmp_path: Path) -> Iterator[str]:
    db_file = tmp_path / "empty.db"
    con = sqlite3.connect(str(db_file))
    con.executescript(SCHEMA)
    con.close()
    with patch("core.db._DB_PATH", str(db_file)):
        yield str(db_file)


def _login(client: TestClient) -> TestClient:
    client.post("/login", data={"password": get_dashboard_password()})
    return client


# ---------------------------------------------------------------------------
# core/analytics.py
# ---------------------------------------------------------------------------

class TestAnalytics:
    def test_kpis_count_only_sold_statuses(self, full_db: str) -> None:
        k = get_dashboard_data()["kpis"]
        assert k["revenue_total"] == 920.0          # 250 + 50 + 120 + 500
        assert k["revenue_window"] == 420.0         # excludes the 60-day-old order
        assert k["orders_total"] == 6
        assert k["orders_sold"] == 4
        assert k["avg_order_value"] == 230.0
        assert k["low_stock_count"] == 1

    def test_revenue_by_day_is_zero_filled_window(self, full_db: str) -> None:
        rd = get_dashboard_data(days=30)["revenue_by_day"]
        assert len(rd["labels"]) == 30
        assert rd["labels"][-1] == date.today().isoformat()
        assert rd["labels"][0] == (date.today() - timedelta(days=29)).isoformat()
        assert rd["values"][-1] == 50.0
        assert rd["values"][-4] == 250.0
        assert sum(rd["values"]) == 420.0

    def test_orders_by_status(self, full_db: str) -> None:
        s = get_dashboard_data()["orders_by_status"]
        assert dict(zip(s["labels"], s["values"])) == {
            "pending": 1, "confirmed": 1, "accepted": 1, "delivered": 2, "rejected": 1,
        }

    def test_top_items_ranked_by_revenue(self, full_db: str) -> None:
        t = get_dashboard_data()["top_items"]
        assert t["labels"] == ["Rice", "Oil", "Sugar"]
        assert t["values"] == [650.0, 150.0, 120.0]   # rejected oil order excluded

    def test_shop_filter(self, full_db: str) -> None:
        d = get_dashboard_data(shop_id=2)
        assert d["kpis"]["revenue_total"] == 120.0
        assert d["kpis"]["orders_total"] == 2
        assert d["stock_levels"]["labels"] == ["Sugar"]

    def test_multi_shop_stock_labels_name_the_shop(self, full_db: str) -> None:
        labels = get_dashboard_data()["stock_levels"]["labels"]
        assert labels == ["Oil (S1)", "Rice (S1)", "Sugar (S2)"]

    def test_days_clamped(self, full_db: str) -> None:
        assert get_dashboard_data(days=1)["days"] == 7
        assert get_dashboard_data(days=1000)["days"] == 90

    def test_legacy_schema_does_not_crash(self, legacy_db: str) -> None:
        d = get_dashboard_data(shop_id=1)
        assert d["kpis"]["revenue_total"] == 110.0
        assert d["top_items"]["labels"] == ["Rice"]

    def test_empty_db(self, empty_db: str) -> None:
        d = get_dashboard_data()
        assert d["kpis"]["avg_order_value"] == 0.0
        assert d["kpis"]["orders_total"] == 0
        assert sum(d["revenue_by_day"]["values"]) == 0

    def test_dashboard_is_read_only(self, full_db: str) -> None:
        before = Path(full_db).read_bytes()
        get_dashboard_data()
        get_dashboard_data(shop_id=1)
        assert Path(full_db).read_bytes() == before


# ---------------------------------------------------------------------------
# Web routes
# ---------------------------------------------------------------------------

class TestDashboardRoutes:
    @pytest.mark.parametrize("path", ["/dashboard", "/api/dashboard"])
    def test_requires_auth(self, full_db: str, path: str) -> None:
        r = TestClient(app).get(path, follow_redirects=False)
        assert r.status_code == 303
        assert r.headers["location"] == "/login"

    def test_page_renders_charts(self, full_db: str) -> None:
        r = _login(TestClient(app)).get("/dashboard")
        assert r.status_code == 200
        for needle in ("Analytics", "revenueChart", "statusChart", "topItemsChart", "stockChart", "chart.umd.min.js"):
            assert needle in r.text
        payload = r.text.split('<script id="dash-data" type="application/json">')[1].split("</script>")[0]
        assert json.loads(payload)["kpis"]["revenue_total"] == 920.0

    def test_page_shop_filter_selected(self, full_db: str) -> None:
        r = _login(TestClient(app)).get("/dashboard?shop_id=2")
        assert r.status_code == 200
        assert '<option value="2" selected>' in r.text

    def test_api_json(self, full_db: str) -> None:
        r = _login(TestClient(app)).get("/api/dashboard?shop_id=1&days=14")
        assert r.status_code == 200
        body = r.json()
        assert set(body) >= {"kpis", "revenue_by_day", "orders_by_status", "top_items", "stock_levels", "shops"}
        assert body["days"] == 14
        assert body["kpis"]["revenue_total"] == 800.0

    def test_empty_state(self, empty_db: str) -> None:
        r = _login(TestClient(app)).get("/dashboard")
        assert r.status_code == 200
        assert "No sold orders yet" in r.text
        assert '<canvas id="revenueChart"' not in r.text

    def test_nav_link_present(self, full_db: str) -> None:
        r = _login(TestClient(app)).get("/")
        assert 'href="/dashboard"' in r.text


# ---------------------------------------------------------------------------
# data/seed_demo.py
# ---------------------------------------------------------------------------

def _load_seed_demo():
    spec = importlib.util.spec_from_file_location("seed_demo", ROOT / "data" / "seed_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSeedDemo:
    def test_creates_sample_orders(self, tmp_path: Path) -> None:
        out = tmp_path / "demo.db"
        result = _load_seed_demo().build_demo_db(str(out), days=10, seed=1)
        assert result["orders"] > 0
        con = sqlite3.connect(str(out))
        ids = [r[0] for r in con.execute("SELECT DISTINCT customer_id FROM orders")]
        con.close()
        assert ids and all(i.startswith("sample-cust-") for i in ids)

    def test_refuses_existing_file(self, tmp_path: Path) -> None:
        out = tmp_path / "exists.db"
        out.write_bytes(b"keep me")
        with pytest.raises(SystemExit):
            _load_seed_demo().build_demo_db(str(out))
        assert out.read_bytes() == b"keep me"

    def test_refuses_real_db(self) -> None:
        mod = _load_seed_demo()
        with pytest.raises(SystemExit):
            mod.build_demo_db(mod.REAL_DB)
