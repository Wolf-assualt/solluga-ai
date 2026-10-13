"""
core/inventory.py — Owner-facing business logic.

All stock management, pricing, order/sales queries live here so they
can be reused by a web dashboard or WhatsApp adapter without change.
No Telegram-specific code belongs in this module.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
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
    """
    Return today's sales total for confirmed/accepted/delivered orders.

    Respects the resettable sales baseline: if the owner reset the counter
    today, only orders placed *after* that moment are counted.
    """
    from core.db import get_conn

    today_s = date.today().isoformat()
    reset_at = get_sales_reset_at()
    with get_conn() as con:
        return _sum_sales(
            con,
            start_date=today_s,
            end_date=today_s,
            since_ts=reset_at,
            shop_id=shop_id,
        )


# ---------------------------------------------------------------------------
# Sales reporting: totals, windows, single day, and a resettable counter
# ---------------------------------------------------------------------------

#: Sales statuses counted as "sold" everywhere in this module.
_SOLD_STATUSES = ("confirmed", "accepted", "delivered")

#: settings key holding the "total sold" reset baseline timestamp.
SALES_RESET_KEY = "sales_reset_at"


def get_sales_reset_at() -> Optional[str]:
    """Return the timestamp the shop owner last reset the total-sold counter."""
    from core.db import get_setting

    return get_setting(SALES_RESET_KEY)


def reset_sales() -> str:
    """
    Zero every sales figure on the dashboard (total, today, week, month)
    *without deleting any orders*.

    Works by recording the current time as a baseline: only orders placed
    after this moment count toward sales again. Returns the new baseline
    timestamp (``YYYY-MM-DD HH:MM:SS``).
    """
    from core.db import get_conn, set_setting

    # Use the database clock so the baseline shares the exact same time
    # source as orders.created_at.
    with get_conn() as con:
        now = con.execute("SELECT datetime('now', 'localtime') AS t").fetchone()["t"]
    set_setting(SALES_RESET_KEY, now)
    return now


def _orders_have_shop_col(con) -> bool:
    return any(c["name"] == "shop_id" for c in con.execute("PRAGMA table_info(orders)").fetchall())


def clear_sales_history(shop_id: Optional[int] = None) -> dict:
    """
    Permanently delete every order and order line (the whole sales history)
    and clear the reset baseline, leaving items, prices and stock untouched.

    This is destructive and cannot be undone. Returns a summary dict with
    ``orders_deleted`` and ``order_items_deleted``.

    Pass ``shop_id`` to clear a single shop only; ``None`` clears everything.
    """
    from core.db import delete_setting, get_conn

    with get_conn() as con:
        has_shop_col = _orders_have_shop_col(con)

        if shop_id is not None and has_shop_col:
            item_cur = con.execute(
                "DELETE FROM order_items WHERE order_id IN "
                "(SELECT id FROM orders WHERE shop_id = ?)",
                (shop_id,),
            )
            order_cur = con.execute("DELETE FROM orders WHERE shop_id = ?", (shop_id,))
        else:
            item_cur = con.execute("DELETE FROM order_items")
            order_cur = con.execute("DELETE FROM orders")
            # Restart order numbering at #1 so the dashboard looks brand new.
            try:
                con.execute("DELETE FROM sqlite_sequence WHERE name IN ('orders', 'order_items')")
            except sqlite3.OperationalError:
                pass

        orders_deleted = order_cur.rowcount if order_cur.rowcount is not None else 0
        items_deleted = item_cur.rowcount if item_cur.rowcount is not None else 0

    delete_setting(SALES_RESET_KEY)
    return {"orders_deleted": orders_deleted, "order_items_deleted": items_deleted}


def _sum_sales(
    con,
    *,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    since_ts: Optional[str] = None,
    shop_id: Optional[int] = None,
) -> float:
    """Sum order totals for sold orders matching the given filters."""
    where = ["status IN ({})".format(", ".join("?" * len(_SOLD_STATUSES)))]
    params: list = list(_SOLD_STATUSES)
    if start_date:
        where.append("date(created_at) >= date(?)")
        params.append(start_date)
    if end_date:
        where.append("date(created_at) <= date(?)")
        params.append(end_date)
    if since_ts:
        where.append("created_at > ?")
        params.append(since_ts)
    if shop_id is not None and _orders_have_shop_col(con):
        where.append("shop_id = ?")
        params.append(shop_id)
    sql = "SELECT COALESCE(SUM(total), 0) AS s FROM orders WHERE " + " AND ".join(where)
    return float(con.execute(sql, params).fetchone()["s"])


def get_sales_summary(shop_id: Optional[int] = None) -> dict:
    """
    Return sales figures for the dashboard.

    Every figure respects the resettable baseline: once the owner hits
    "Reset", each window counts only orders placed *after* the reset moment.

    Keys:
        ``today``             – sales placed today (since reset, if reset today)
        ``week``              – sales since Monday of the current week
        ``month``             – sales since the 1st of the current month
        ``total_since_reset`` – sales since the last reset (the resettable total)
        ``total_all_time``    – every sold order ever recorded (never reset)
        ``reset_at``          – baseline timestamp, or ``None`` if never reset
    """
    from core.db import get_conn

    today = date.today()
    today_s = today.isoformat()
    week_start_s = (today - timedelta(days=today.weekday())).isoformat()
    month_start_s = today.replace(day=1).isoformat()
    reset_at = get_sales_reset_at()

    with get_conn() as con:
        return {
            "today": _sum_sales(
                con, start_date=today_s, end_date=today_s, since_ts=reset_at, shop_id=shop_id
            ),
            "week": _sum_sales(con, start_date=week_start_s, end_date=today_s, since_ts=reset_at, shop_id=shop_id),
            "month": _sum_sales(con, start_date=month_start_s, end_date=today_s, since_ts=reset_at, shop_id=shop_id),
            "total_since_reset": _sum_sales(con, since_ts=reset_at, shop_id=shop_id),
            "total_all_time": _sum_sales(con, shop_id=shop_id),
            "reset_at": reset_at,
        }


def get_sales_for_date(day: str, shop_id: Optional[int] = None) -> dict:
    """
    Detailed sales for a single day (``YYYY-MM-DD``).

    Returns ``total``, ``order_count`` and a per-item ``items`` breakdown.
    """
    from core.db import get_conn

    with get_conn() as con:
        if shop_id is not None and _orders_have_shop_col(con):
            tb = con.execute(
                f"SELECT COALESCE(SUM(total), 0) AS s, COUNT(*) AS n FROM orders "
                f"WHERE date(created_at) = date(?) AND status IN ({', '.join('?' * len(_SOLD_STATUSES))}) "
                f"AND shop_id = ?",
                [day, *_SOLD_STATUSES, shop_id],
            ).fetchone()
            item_rows = con.execute(
                f"""
                SELECT i.name, i.unit, SUM(oi.quantity) AS qty,
                       SUM(oi.quantity * oi.unit_price) AS amount
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                JOIN items i ON i.id = oi.item_id
                WHERE date(o.created_at) = date(?)
                  AND o.status IN ({', '.join('?' * len(_SOLD_STATUSES))})
                  AND o.shop_id = ?
                GROUP BY i.id
                ORDER BY amount DESC
                """,
                [day, *_SOLD_STATUSES, shop_id],
            ).fetchall()
        else:
            tb = con.execute(
                f"SELECT COALESCE(SUM(total), 0) AS s, COUNT(*) AS n FROM orders "
                f"WHERE date(created_at) = date(?) AND status IN ({', '.join('?' * len(_SOLD_STATUSES))})",
                [day, *_SOLD_STATUSES],
            ).fetchone()
            item_rows = con.execute(
                f"""
                SELECT i.name, i.unit, SUM(oi.quantity) AS qty,
                       SUM(oi.quantity * oi.unit_price) AS amount
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                JOIN items i ON i.id = oi.item_id
                WHERE date(o.created_at) = date(?)
                  AND o.status IN ({', '.join('?' * len(_SOLD_STATUSES))})
                GROUP BY i.id
                ORDER BY amount DESC
                """,
                [day, *_SOLD_STATUSES],
            ).fetchall()

    return {
        "date": day,
        "total": float(tb["s"]),
        "order_count": int(tb["n"]),
        "items": [
            {"name": r["name"], "unit": r["unit"], "qty": float(r["qty"]), "amount": float(r["amount"])}
            for r in item_rows
        ],
    }


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

