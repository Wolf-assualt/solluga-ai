"""
core/inventory.py — Owner-facing business logic.

All stock management, pricing, order/sales queries live here so they
can be reused by a web dashboard or WhatsApp adapter without change.
No Telegram-specific code belongs in this module.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

_LOW_STOCK_THRESHOLD: int = int(os.getenv("LOW_STOCK_THRESHOLD", "3"))


# ---------------------------------------------------------------------------
# Data classes returned by this module
# ---------------------------------------------------------------------------

@dataclass
class StockRow:
    """Single item as shown in the /stock command."""
    id: int
    name: str
    unit: str
    price: float
    stock: float
    aliases: list[str] = field(default_factory=list)

    @property
    def is_low(self) -> bool:
        return self.stock <= _LOW_STOCK_THRESHOLD


@dataclass
class OrderSummary:
    """Brief order info for /orders list and owner notification."""
    order_id: int
    customer_id: str
    status: str
    total: float
    created_at: str
    items: list[dict] = field(default_factory=list)  # [{name, qty, unit, unit_price}]


# ---------------------------------------------------------------------------
# Stock queries
# ---------------------------------------------------------------------------

def get_stock_list(shop_id: Optional[int] = None) -> list[StockRow]:
    """Return all items for a shop sorted by name, with low-stock flag."""
    from core.db import get_all_items  # local import avoids circular dep

    rows = get_all_items(shop_id=shop_id)
    return [
        StockRow(
            id=r["id"],
            name=r["name"],
            unit=r["unit"],
            price=r["price"],
            stock=r["stock"],
            aliases=r.get("aliases", []),
        )
        for r in sorted(rows, key=lambda x: x["name"])
    ]


def add_stock(item_name: str, qty: float) -> StockRow:
    """
    Add *qty* units to the named item's stock.
    Raises ValueError if item not found or qty <= 0.
    Returns the updated StockRow.
    """
    if qty <= 0:
        raise ValueError(f"Quantity must be positive, got {qty}")

    from core.db import get_conn, get_all_items
    from core.matcher import match_item

    items = get_all_items()
    item = match_item(item_name, items)
    if item is None:
        raise ValueError(f"Item not found: '{item_name}'")

    with get_conn() as con:
        con.execute(
            "UPDATE items SET stock = stock + ? WHERE id = ?",
            (qty, item["id"]),
        )
        updated = con.execute(
            "SELECT * FROM items WHERE id = ?", (item["id"],)
        ).fetchone()

    d = dict(updated)
    return StockRow(
        id=d["id"],
        name=d["name"],
        unit=d["unit"],
        price=d["price"],
        stock=d["stock"],
        aliases=json.loads(d["aliases"]),
    )


def set_price(item_name: str, new_price: float) -> StockRow:
    """
    Update the price of a named item.
    Raises ValueError if item not found or price <= 0.
    Returns the updated StockRow.
    """
    if new_price <= 0:
        raise ValueError(f"Price must be positive, got {new_price}")

    from core.db import get_conn, get_all_items
    from core.matcher import match_item

    items = get_all_items()
    item = match_item(item_name, items)
    if item is None:
        raise ValueError(f"Item not found: '{item_name}'")

    with get_conn() as con:
        con.execute(
            "UPDATE items SET price = ? WHERE id = ?",
            (new_price, item["id"]),
        )
        updated = con.execute(
            "SELECT * FROM items WHERE id = ?", (item["id"],)
        ).fetchone()

    d = dict(updated)
    return StockRow(
        id=d["id"],
        name=d["name"],
        unit=d["unit"],
        price=d["price"],
        stock=d["stock"],
        aliases=json.loads(d["aliases"]),
    )


def add_new_item(
    name: str,
    unit: str,
    price: float,
    stock: float,
    aliases: list[str],
    shop_id: int = 1,
) -> StockRow:
    """
    Insert a brand-new item into the DB for a specific shop.
    Raises ValueError on duplicate name or bad values.
    Returns the created StockRow.
    """
    name = name.strip().lower()
    if not name:
        raise ValueError("Item name cannot be empty")
    if price <= 0:
        raise ValueError(f"Price must be positive, got {price}")
    if stock < 0:
        raise ValueError(f"Stock cannot be negative, got {stock}")

    # Always include the canonical name as an alias
    alias_list = list({a.strip().lower() for a in aliases if a.strip()})
    if name not in alias_list:
        alias_list.insert(0, name)

    from core.db import get_conn

    with get_conn() as con:
        has_shop_col = any(col["name"] == "shop_id" for col in con.execute("PRAGMA table_info(items)").fetchall())
        try:
            if has_shop_col:
                cur = con.execute(
                    "INSERT INTO items (shop_id, name, aliases, unit, price, stock) VALUES (?, ?, ?, ?, ?, ?)",
                    (shop_id, name, json.dumps(alias_list), unit.strip(), price, stock),
                )
            else:
                cur = con.execute(
                    "INSERT INTO items (name, aliases, unit, price, stock) VALUES (?, ?, ?, ?, ?)",
                    (name, json.dumps(alias_list), unit.strip(), price, stock),
                )
            row_id = cur.lastrowid
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise ValueError(f"Item '{name}' already exists in this shop") from exc
            raise

        updated = con.execute(
            "SELECT * FROM items WHERE id = ?", (row_id,)
        ).fetchone()

    d = dict(updated)
    return StockRow(
        id=d["id"],
        name=d["name"],
        unit=d["unit"],
        price=d["price"],
        stock=d["stock"],
        aliases=json.loads(d["aliases"]),
    )


# ---------------------------------------------------------------------------
# Low-stock detection
# ---------------------------------------------------------------------------

def get_low_stock_items(threshold: Optional[int] = None, shop_id: Optional[int] = None) -> list[StockRow]:
    """Return items at or below the low-stock threshold for a shop."""
    t = threshold if threshold is not None else _LOW_STOCK_THRESHOLD
    return [r for r in get_stock_list(shop_id=shop_id) if r.stock <= t]


# ---------------------------------------------------------------------------
# Order management
# ---------------------------------------------------------------------------

def get_todays_orders(shop_id: Optional[int] = None) -> list[OrderSummary]:
    """Return all orders created today (local time), newest first."""
    from core.db import get_conn

    with get_conn() as con:
        has_shop_col = any(col["name"] == "shop_id" for col in con.execute("PRAGMA table_info(orders)").fetchall())
        if has_shop_col and shop_id is not None:
            rows = con.execute(
                """
                SELECT o.id, o.customer_id, o.status, o.total, o.created_at
                FROM orders o
                WHERE date(o.created_at) = date('now', 'localtime')
                  AND o.shop_id = ?
                ORDER BY o.id DESC
                """,
                (shop_id,),
            ).fetchall()
        else:
            rows = con.execute(
                """
                SELECT o.id, o.customer_id, o.status, o.total, o.created_at
                FROM orders o
                WHERE date(o.created_at) = date('now', 'localtime')
                ORDER BY o.id DESC
                """
            ).fetchall()

        summaries = []
        for row in rows:
            item_rows = con.execute(
                """
                SELECT i.name, oi.quantity, i.unit, oi.unit_price
                FROM order_items oi
                JOIN items i ON i.id = oi.item_id
                WHERE oi.order_id = ?
                """,
                (row["id"],),
            ).fetchall()
            summaries.append(
                OrderSummary(
                    order_id=row["id"],
                    customer_id=row["customer_id"],
                    status=row["status"],
                    total=row["total"],
                    created_at=row["created_at"],
                    items=[
                        {
                            "name": ir["name"],
                            "qty": ir["quantity"],
                            "unit": ir["unit"],
                            "unit_price": ir["unit_price"],
                        }
                        for ir in item_rows
                    ],
                )
            )
    return summaries


def get_todays_sales_total(shop_id: Optional[int] = None) -> float:
    """Return the sum of totals for all *confirmed/accepted/delivered* orders today."""
    from core.db import get_conn

    with get_conn() as con:
        has_shop_col = any(col["name"] == "shop_id" for col in con.execute("PRAGMA table_info(orders)").fetchall())
        if has_shop_col and shop_id is not None:
            row = con.execute(
                """
                SELECT COALESCE(SUM(total), 0) AS daily_total
                FROM orders
                WHERE date(created_at) = date('now', 'localtime')
                  AND status IN ('confirmed', 'accepted', 'delivered')
                  AND shop_id = ?
                """,
                (shop_id,),
            ).fetchone()
        else:
            row = con.execute(
                """
                SELECT COALESCE(SUM(total), 0) AS daily_total
                FROM orders
                WHERE date(created_at) = date('now', 'localtime')
                  AND status IN ('confirmed', 'accepted', 'delivered')
                """
            ).fetchone()
    return float(row["daily_total"])


def get_order_detail(order_id: int) -> Optional[OrderSummary]:
    """Fetch a single order with its line items."""
    from core.db import get_conn

    with get_conn() as con:
        row = con.execute(
            "SELECT id, customer_id, status, total, created_at FROM orders WHERE id = ?",
            (order_id,),
        ).fetchone()
        if row is None:
            return None

        item_rows = con.execute(
            """
            SELECT i.name, oi.quantity, i.unit, oi.unit_price
            FROM order_items oi
            JOIN items i ON i.id = oi.item_id
            WHERE oi.order_id = ?
            """,
            (order_id,),
        ).fetchall()

    return OrderSummary(
        order_id=row["id"],
        customer_id=row["customer_id"],
        status=row["status"],
        total=row["total"],
        created_at=row["created_at"],
        items=[
            {
                "name": ir["name"],
                "qty": ir["quantity"],
                "unit": ir["unit"],
                "unit_price": ir["unit_price"],
            }
            for ir in item_rows
        ],
    )


def update_order_status(order_id: int, new_status: str) -> bool:
    """
    Update an order's status. Returns True if a row was updated, False otherwise.
    Valid statuses: confirmed, accepted, rejected, delivered, cancelled.
    Restores stock if order is rejected or cancelled.
    """
    valid = {"confirmed", "accepted", "rejected", "delivered", "cancelled"}
    if new_status not in valid:
        raise ValueError(f"Invalid status '{new_status}'. Must be one of {valid}")

    from core.db import get_conn

    with get_conn() as con:
        prev = con.execute("SELECT status FROM orders WHERE id = ?", (order_id,)).fetchone()
        if prev is None:
            return False

        old_status = prev["status"]
        cur = con.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (new_status, order_id),
        )

        # Restore stock if transitioning to rejected or cancelled
        if new_status in ("rejected", "cancelled") and old_status not in ("rejected", "cancelled"):
            item_rows = con.execute(
                "SELECT item_id, quantity FROM order_items WHERE order_id = ?",
                (order_id,),
            ).fetchall()
            for ir in item_rows:
                con.execute(
                    "UPDATE items SET stock = stock + ? WHERE id = ?",
                    (ir["quantity"], ir["item_id"]),
                )

    return cur.rowcount > 0


def update_item(
    item_id: int,
    price: float,
    stock: float,
    aliases: Optional[list[str]] = None,
    unit: Optional[str] = None,
) -> StockRow:
    """
    Update an item's price, stock, and optionally aliases and unit.
    Raises ValueError if item not found or bad values.
    """
    if price <= 0:
        raise ValueError(f"Price must be positive, got {price}")
    if stock < 0:
        raise ValueError(f"Stock cannot be negative, got {stock}")

    from core.db import get_conn, get_item_by_id

    current = get_item_by_id(item_id)
    if not current:
        raise ValueError(f"Item #{item_id} not found")

    new_unit = unit.strip() if unit else current["unit"]
    if aliases is not None:
        alias_list = list({a.strip().lower() for a in aliases if a.strip()})
        if current["name"].lower() not in alias_list:
            alias_list.insert(0, current["name"].lower())
        alias_json = json.dumps(alias_list)
    else:
        alias_json = json.dumps(current["aliases"])

    with get_conn() as con:
        con.execute(
            "UPDATE items SET price = ?, stock = ?, unit = ?, aliases = ? WHERE id = ?",
            (price, stock, new_unit, alias_json, item_id),
        )
        updated = con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()

    d = dict(updated)
    return StockRow(
        id=d["id"],
        name=d["name"],
        unit=d["unit"],
        price=d["price"],
        stock=d["stock"],
        aliases=json.loads(d["aliases"]),
    )


def delete_item(item_id: int) -> bool:
    """Delete an item by id. Returns True if deleted."""
    from core.db import get_conn

    with get_conn() as con:
        cur = con.execute("DELETE FROM items WHERE id = ?", (item_id,))
    return cur.rowcount > 0


def get_orders_list(
    status_filter: Optional[str] = None,
    date_filter: Optional[str] = None,
    shop_id: Optional[int] = None,
) -> list[OrderSummary]:
    """
    Fetch orders with optional status, date filter ('today', 'all', or YYYY-MM-DD),
    and optional shop_id filter. Returns list of OrderSummary, newest first.
    """
    from core.db import get_conn

    query = "SELECT id, customer_id, status, total, created_at FROM orders WHERE 1=1"
    params: list = []

    if shop_id is not None:
        has_shop_col = any(col["name"] == "shop_id" for col in get_conn().__enter__().execute("PRAGMA table_info(orders)").fetchall())
        if has_shop_col:
            query += " AND shop_id = ?"
            params.append(shop_id)

    if status_filter and status_filter.lower() != "all":
        query += " AND status = ?"
        params.append(status_filter.lower())

    if date_filter == "today":
        query += " AND date(created_at) = date('now', 'localtime')"
    elif date_filter and date_filter.lower() != "all":
        query += " AND date(created_at) = ?"
        params.append(date_filter)

    query += " ORDER BY id DESC"

    with get_conn() as con:
        rows = con.execute(query, params).fetchall()
        summaries = []
        for r in rows:
            item_rows = con.execute(
                """
                SELECT i.name, oi.quantity, i.unit, oi.unit_price
                FROM order_items oi
                JOIN items i ON i.id = oi.item_id
                WHERE oi.order_id = ?
                """,
                (r["id"],),
            ).fetchall()
            summaries.append(
                OrderSummary(
                    order_id=r["id"],
                    customer_id=r["customer_id"],
                    status=r["status"],
                    total=r["total"],
                    created_at=r["created_at"],
                    items=[
                        {
                            "name": ir["name"],
                            "qty": ir["quantity"],
                            "unit": ir["unit"],
                            "unit_price": ir["unit_price"],
                        }
                        for ir in item_rows
                    ],
                )
            )
    return summaries

