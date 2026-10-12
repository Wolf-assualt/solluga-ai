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
# Item queries
# ---------------------------------------------------------------------------

def get_all_items() -> list[dict]:
    """Return all items as plain dicts (aliases decoded from JSON)."""
    with get_conn() as con:
        rows = con.execute("SELECT * FROM items").fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["aliases"] = json.loads(d["aliases"])
        result.append(d)
    return result


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

def create_order(customer_id: str) -> int:
    """Create a pending order and return its ID."""
    with get_conn() as con:
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
) -> int:
    """
    Atomically create an order, insert line items, update stock, and mark confirmed.
    Returns the new order_id.
    """
    with get_conn() as con:
        cur = con.execute(
            "INSERT INTO orders (customer_id, status, total) VALUES (?, 'confirmed', ?)",
            (customer_id, total),
        )
        order_id = cur.lastrowid

        for li in line_items:
            # Verify stock
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
