"""
core/db.py — SQLite database connection and query helpers.
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Generator, Optional

from dotenv import load_dotenv

load_dotenv()

_DB_PATH: str = os.getenv("DB_PATH", "data/sollunga.db")


def _make_root_absolute(path: str) -> str:
    """Convert a relative path to absolute based on project root."""
    if os.path.isabs(path):
        return path
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(root, path)


def get_db_path() -> str:
    return _make_root_absolute(_DB_PATH)


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    """Context manager that yields a connected, row-factory-enabled connection."""
    path = get_db_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


# ---------------------------------------------------------------------------
# Shop queries (Phase 5: Multi-shop)
# ---------------------------------------------------------------------------

def get_all_shops() -> list[dict]:
    """Return all active shops."""
    with get_conn() as con:
        # Check if shops table exists
        cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shops'")
        if not cur.fetchone():
            return [{"id": 1, "name": "Default Kirana Store", "slug": "default", "owner_id": "", "is_active": 1}]
        rows = con.execute("SELECT * FROM shops WHERE is_active = 1 ORDER BY id").fetchall()
        if not rows:
            return [{"id": 1, "name": "Default Kirana Store", "slug": "default", "owner_id": "", "is_active": 1}]
        return [dict(r) for r in rows]


def get_shop_by_id(shop_id: int = 1) -> Optional[dict]:
    """Return shop details by shop_id."""
    with get_conn() as con:
        cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='shops'")
        if not cur.fetchone():
            return {"id": 1, "name": "Default Kirana Store", "slug": "default", "owner_id": "", "is_active": 1}
        row = con.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        if row is None:
            return {"id": 1, "name": "Default Kirana Store", "slug": "default", "owner_id": "", "is_active": 1}
        return dict(row)


def get_customer_shop_id(customer_id: str) -> int:
    """Get the shop_id linked to this customer, defaulting to 1."""
    with get_conn() as con:
        cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='customer_shops'")
        if not cur.fetchone():
            return 1
        row = con.execute("SELECT shop_id FROM customer_shops WHERE customer_id = ?", (customer_id,)).fetchone()
        return row["shop_id"] if row else 1


def set_customer_shop_id(customer_id: str, shop_id: int) -> None:
    """Link customer to a selected shop."""
    with get_conn() as con:
        con.execute(
            """
            INSERT INTO customer_shops (customer_id, shop_id, updated_at)
            VALUES (?, ?, datetime('now', 'localtime'))
            ON CONFLICT(customer_id) DO UPDATE SET
                shop_id = excluded.shop_id,
                updated_at = excluded.updated_at
            """,
            (customer_id, shop_id),
        )


# ---------------------------------------------------------------------------
# Item queries
# ---------------------------------------------------------------------------

def get_all_items(shop_id: Optional[int] = None) -> list[dict]:
    """Return all items for a shop (or all items if shop_id is None)."""
    with get_conn() as con:
        # Check if shop_id column exists
        has_shop_col = False
        pragma = con.execute("PRAGMA table_info(items)").fetchall()
        for col in pragma:
            if col["name"] == "shop_id":
                has_shop_col = True
                break

        if has_shop_col and shop_id is not None:
            rows = con.execute("SELECT * FROM items WHERE shop_id = ?", (shop_id,)).fetchall()
        else:
            rows = con.execute("SELECT * FROM items").fetchall()

    result = []
    for row in rows:
        d = dict(row)
        d["aliases"] = json.loads(d["aliases"])
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Settings (simple key-value store, e.g. sales reset baseline)
# ---------------------------------------------------------------------------

_SETTINGS_DDL = """
    CREATE TABLE IF NOT EXISTS settings (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
    )
"""


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    """Read a settings value by key. Creates the settings table if missing."""
    with get_conn() as con:
        con.execute(_SETTINGS_DDL)
        row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    """Write a settings value (insert or update). Creates the table if missing."""
    with get_conn() as con:
        con.execute(_SETTINGS_DDL)
        con.execute(
            """
            INSERT INTO settings (key, value, updated_at)
            VALUES (?, ?, datetime('now', 'localtime'))
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value),
        )


def delete_setting(key: str) -> None:
    """Remove a settings value by key. Creates the table if missing (no-op)."""
    with get_conn() as con:
        con.execute(_SETTINGS_DDL)
        con.execute("DELETE FROM settings WHERE key = ?", (key,))


def get_item_by_id(item_id: int) -> Optional[dict]:
    with get_conn() as con:
        row = con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["aliases"] = json.loads(d["aliases"])
    return d


def deduct_stock(item_id: int, quantity: float) -> None:
    """Reduce stock for an item. Raises ValueError if insufficient stock."""
    with get_conn() as con:
        row = con.execute(
            "SELECT stock FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Item {item_id} not found")
        if row["stock"] < quantity:
            raise ValueError(
                f"Insufficient stock: have {row['stock']}, need {quantity}"
            )
        con.execute(
            "UPDATE items SET stock = stock - ? WHERE id = ?",
            (quantity, item_id),
        )


# ---------------------------------------------------------------------------
# Order queries
# ---------------------------------------------------------------------------

def create_order(customer_id: str, shop_id: int = 1) -> int:
    """Create a pending order and return its ID."""
    with get_conn() as con:
        has_shop_col = any(col["name"] == "shop_id" for col in con.execute("PRAGMA table_info(orders)").fetchall())
        if has_shop_col:
            cur = con.execute(
                "INSERT INTO orders (customer_id, shop_id, status, total) VALUES (?, ?, 'pending', 0)",
                (customer_id, shop_id),
            )
        else:
            cur = con.execute(
                "INSERT INTO orders (customer_id, status, total) VALUES (?, 'pending', 0)",
                (customer_id,),
            )
        return cur.lastrowid


def add_order_item(order_id: int, item_id: int, quantity: float, unit_price: float) -> None:
    with get_conn() as con:
        con.execute(
            "INSERT INTO order_items (order_id, item_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
            (order_id, item_id, quantity, unit_price),
        )


def update_order_status(order_id: int, status: str, total: float = 0.0) -> None:
    with get_conn() as con:
        con.execute(
            "UPDATE orders SET status = ?, total = ? WHERE id = ?",
            (status, total, order_id),
        )


def save_confirmed_order(
    customer_id: str,
    line_items: list[dict],  # [{"item_id", "quantity", "unit_price"}, ...]
    total: float,
    shop_id: int = 1,
) -> int:
    """
    Atomically create an order, insert line items, update stock, and mark confirmed.
    Returns the new order_id.
    """
    with get_conn() as con:
        has_shop_col = any(col["name"] == "shop_id" for col in con.execute("PRAGMA table_info(orders)").fetchall())
        if has_shop_col:
            cur = con.execute(
                "INSERT INTO orders (customer_id, shop_id, status, total) VALUES (?, ?, 'confirmed', ?)",
                (customer_id, shop_id, total),
            )
        else:
            cur = con.execute(
                "INSERT INTO orders (customer_id, status, total) VALUES (?, 'confirmed', ?)",
                (customer_id, total),
            )
        order_id = cur.lastrowid

        for li in line_items:
            row = con.execute(
                "SELECT stock FROM items WHERE id = ?", (li["item_id"],)
            ).fetchone()
            if row is None:
                raise ValueError(f"Item {li['item_id']} not found during save")
            if row["stock"] < li["quantity"]:
                raise ValueError(
                    f"Insufficient stock for item {li['item_id']}: "
                    f"have {row['stock']}, need {li['quantity']}"
                )

            con.execute(
                "INSERT INTO order_items (order_id, item_id, quantity, unit_price) "
                "VALUES (?, ?, ?, ?)",
                (order_id, li["item_id"], li["quantity"], li["unit_price"]),
            )
            con.execute(
                "UPDATE items SET stock = stock - ? WHERE id = ?",
                (li["quantity"], li["item_id"]),
            )

    return order_id

