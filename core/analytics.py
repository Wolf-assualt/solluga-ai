"""
core/analytics.py — Read-only aggregates for the /dashboard analytics page.

Plain SQL + Python only (no LLM involvement). Every query is a SELECT, so
opening the dashboard never mutates the database. Works on both the current
multi-shop schema and the legacy single-shop schema (no ``shop_id`` column).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

from core.db import get_all_items, get_all_shops, get_conn
from core.inventory import _LOW_STOCK_THRESHOLD, _SOLD_STATUSES

#: Every order status the app can produce, in lifecycle order.
ORDER_STATUSES = ("pending", "confirmed", "accepted", "delivered", "rejected", "cancelled")

_SOLD_PLACEHOLDERS = ", ".join("?" * len(_SOLD_STATUSES))


def _has_column(con, table: str, column: str) -> bool:
    return any(r["name"] == column for r in con.execute(f"PRAGMA table_info({table})").fetchall())


def _shop_filter(con, shop_id: Optional[int], alias: str = "") -> tuple[str, list]:
    """Return an ``AND shop_id = ?`` clause when filtering is possible."""
    if shop_id is None or not _has_column(con, "orders", "shop_id"):
        return "", []
    col = f"{alias}.shop_id" if alias else "shop_id"
    return f" AND {col} = ?", [shop_id]


def _kpis(con, shop_id: Optional[int], window_start: str) -> dict:
    shop_sql, shop_params = _shop_filter(con, shop_id)
    sold = con.execute(
        f"SELECT COUNT(*) AS n, COALESCE(SUM(total), 0) AS s FROM orders "
        f"WHERE status IN ({_SOLD_PLACEHOLDERS}){shop_sql}",
        [*_SOLD_STATUSES, *shop_params],
    ).fetchone()
    window = con.execute(
        f"SELECT COALESCE(SUM(total), 0) AS s FROM orders "
        f"WHERE status IN ({_SOLD_PLACEHOLDERS}) AND date(created_at) >= date(?){shop_sql}",
        [*_SOLD_STATUSES, window_start, *shop_params],
    ).fetchone()
    all_orders = con.execute(
        f"SELECT COUNT(*) AS n FROM orders WHERE 1=1{shop_sql}", shop_params
    ).fetchone()

    revenue_total = round(float(sold["s"]), 2)
    orders_sold = int(sold["n"])
    return {
        "revenue_total": revenue_total,
        "revenue_window": round(float(window["s"]), 2),
        "orders_total": int(all_orders["n"]),
        "orders_sold": orders_sold,
        "avg_order_value": round(revenue_total / orders_sold, 2) if orders_sold else 0.0,
    }


def _revenue_by_day(con, shop_id: Optional[int], start: date, days: int) -> dict:
    shop_sql, shop_params = _shop_filter(con, shop_id)
    rows = con.execute(
        f"SELECT date(created_at) AS d, COALESCE(SUM(total), 0) AS s, COUNT(*) AS n FROM orders "
        f"WHERE status IN ({_SOLD_PLACEHOLDERS}) AND date(created_at) >= date(?){shop_sql} "
        f"GROUP BY date(created_at)",
        [*_SOLD_STATUSES, start.isoformat(), *shop_params],
    ).fetchall()
    by_day = {r["d"]: (float(r["s"]), int(r["n"])) for r in rows}
    labels = [(start + timedelta(days=i)).isoformat() for i in range(days)]
    return {
        "labels": labels,
        "values": [round(by_day.get(d, (0.0, 0))[0], 2) for d in labels],
        "orders": [by_day.get(d, (0.0, 0))[1] for d in labels],
    }


def _orders_by_status(con, shop_id: Optional[int]) -> dict:
    shop_sql, shop_params = _shop_filter(con, shop_id)
    rows = con.execute(
        f"SELECT status, COUNT(*) AS n FROM orders WHERE 1=1{shop_sql} GROUP BY status",
        shop_params,
    ).fetchall()
    counts = {r["status"]: int(r["n"]) for r in rows}
    labels = [s for s in ORDER_STATUSES if counts.get(s)]
    labels += sorted(s for s in counts if s not in ORDER_STATUSES)
    return {"labels": labels, "values": [counts[s] for s in labels]}


def _top_items(con, shop_id: Optional[int], limit: int = 8) -> dict:
    shop_sql, shop_params = _shop_filter(con, shop_id, alias="o")
    rows = con.execute(
        f"""
        SELECT i.name AS name, i.unit AS unit,
               SUM(oi.quantity) AS qty,
               SUM(oi.quantity * oi.unit_price) AS amount
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id
        JOIN items  i ON i.id = oi.item_id
        WHERE o.status IN ({_SOLD_PLACEHOLDERS}){shop_sql}
        GROUP BY i.name, i.unit
        ORDER BY amount DESC
        LIMIT ?
        """,
        [*_SOLD_STATUSES, *shop_params, limit],
    ).fetchall()
    return {
        "labels": [r["name"].title() for r in rows],
        "values": [round(float(r["amount"]), 2) for r in rows],
        "qty": [round(float(r["qty"]), 2) for r in rows],
        "units": [r["unit"] for r in rows],
    }


def _stock_levels(shop_id: Optional[int]) -> dict:
    items = get_all_items(shop_id=shop_id)
    multi_shop = shop_id is None and len({i.get("shop_id", 1) for i in items}) > 1
    items.sort(key=lambda i: (i.get("shop_id", 1), i["name"]))
    labels = []
    for i in items:
        label = i["name"].title()
        if multi_shop:
            label += f" (S{i.get('shop_id', 1)})"
        labels.append(label)
    return {
        "labels": labels,
        "values": [float(i["stock"]) for i in items],
        "units": [i["unit"] for i in items],
        "low": [float(i["stock"]) <= _LOW_STOCK_THRESHOLD for i in items],
    }


def get_dashboard_data(shop_id: Optional[int] = None, days: int = 30) -> dict:
    """
    Aggregate everything the analytics dashboard renders.

    Revenue counts orders whose status is in ``_SOLD_STATUSES`` (confirmed,
    accepted, delivered) across all time — it does not apply the Sales page's
    resettable baseline.
    """
    days = max(7, min(int(days), 90))
    today = date.today()
    start = today - timedelta(days=days - 1)
    shops = get_all_shops()

    with get_conn() as con:
        kpis = _kpis(con, shop_id, start.isoformat())
        revenue_by_day = _revenue_by_day(con, shop_id, start, days)
        orders_by_status = _orders_by_status(con, shop_id)
        top_items = _top_items(con, shop_id)

    stock = _stock_levels(shop_id)
    kpis["low_stock_count"] = sum(stock["low"])
    kpis["item_count"] = len(stock["labels"])

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "shop_id": shop_id,
        "days": days,
        "low_stock_threshold": _LOW_STOCK_THRESHOLD,
        "shops": [{"id": s["id"], "name": s["name"]} for s in shops],
        "kpis": kpis,
        "revenue_by_day": revenue_by_day,
        "orders_by_status": orders_by_status,
        "top_items": top_items,
        "stock_levels": stock,
    }
