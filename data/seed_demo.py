"""
data/seed_demo.py — Generate SAMPLE order history for demos and screenshots.

*** SAMPLE DATA — NOT REAL ORDERS ***

Creates a brand-new SQLite database (default: data/demo.db) containing the
shops + items from data/seed.py and ~30 days of synthetic, reproducible orders
so the /dashboard charts have something to show. Customer IDs are prefixed
``sample-cust-`` so they can never be mistaken for real customers.

Safety:
  * It never writes to the real database (data/sollunga.db).
  * It refuses to touch a file that already exists — pass a new --db path.

Usage:
    python data/seed_demo.py                      # -> data/demo.db
    python data/seed_demo.py --db data/demo2.db --days 45 --seed 7

Then run the dashboard against it:
    DB_PATH=data/demo.db uvicorn web.app:app --port 2627
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL_DB = os.path.join(ROOT, "data", "sollunga.db")
DEFAULT_DEMO_DB = os.path.join(ROOT, "data", "demo.db")


def _load_seed_module():
    """Import data/seed.py (data/ is not a package) to reuse its catalogue."""
    spec = importlib.util.spec_from_file_location("sollunga_seed", os.path.join(ROOT, "data", "seed.py"))
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


# Weighted status mix for historical orders (today's orders lean "open").
_STATUS_WEIGHTS = [
    ("delivered", 55), ("confirmed", 10), ("accepted", 10),
    ("pending", 8), ("rejected", 9), ("cancelled", 8),
]
_TODAY_WEIGHTS = [
    ("pending", 30), ("confirmed", 35), ("accepted", 20),
    ("delivered", 10), ("cancelled", 5),
]

# Popular staples get picked more often.
_ITEM_POPULARITY = {
    "rice": 10, "milk": 9, "sugar": 7, "oil": 6, "tea powder": 6,
    "coffee powder": 4, "chilli powder": 3,
}


def _qty_for(unit: str, rng: random.Random) -> float:
    if unit == "kg":
        return rng.choice([0.5, 1, 1, 2, 2, 3, 5])
    if unit == "litre":
        return float(rng.choice([1, 1, 2, 3]))
    if unit == "packet":
        return float(rng.choice([1, 1, 2, 2, 3, 4]))
    return float(rng.randint(1, 6))


def _pick(weights: list[tuple[str, int]], rng: random.Random) -> str:
    return rng.choices([w[0] for w in weights], weights=[w[1] for w in weights])[0]


def build_demo_db(db_path: str, days: int = 30, seed: int = 42) -> dict:
    """Create *db_path* from scratch and fill it with sample data. Returns counts."""
    db_path = os.path.abspath(db_path)
    if os.path.abspath(db_path) == os.path.abspath(REAL_DB):
        raise SystemExit("Refusing to write sample data into the real database (data/sollunga.db).")
    if os.path.exists(db_path):
        raise SystemExit(
            f"{db_path} already exists — refusing to overwrite it. "
            "Pass a new path with --db (nothing was changed)."
        )

    seed_mod = _load_seed_module()
    rng = random.Random(seed)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        with open(seed_mod.SCHEMA_PATH, encoding="utf-8") as f:
            con.executescript(f.read())

        for s in seed_mod.SHOPS:
            con.execute(
                "INSERT INTO shops (id, name, slug, owner_id, is_active) VALUES (?, ?, ?, ?, ?)",
                (s["id"], s["name"], s["slug"], s["owner_id"], s["is_active"]),
            )
        for it in seed_mod.DEMO_ITEMS_SHOP_1 + seed_mod.DEMO_ITEMS_SHOP_2:
            con.execute(
                "INSERT INTO items (shop_id, name, aliases, unit, price, stock) VALUES (?, ?, ?, ?, ?, ?)",
                (it["shop_id"], it["name"], json.dumps(it["aliases"]), it["unit"], it["price"], it["stock"]),
            )

        items_by_shop: dict[int, list[sqlite3.Row]] = {}
        for row in con.execute("SELECT id, shop_id, name, unit, price FROM items"):
            items_by_shop.setdefault(row["shop_id"], []).append(row)

        today = date.today()
        now = datetime.now()
        n_orders = n_lines = 0
        for offset in range(days - 1, -1, -1):
            day = today - timedelta(days=offset)
            is_today = offset == 0
            base = rng.randint(3, 9) + (2 if day.weekday() >= 5 else 0)
            # Gentle upward trend so the line chart shows growth.
            count = base + (days - offset) // 10
            for _ in range(count):
                shop_id = 1 if rng.random() < 0.65 else 2
                hour = rng.randint(8, 20)
                ts = datetime(day.year, day.month, day.day, hour, rng.randint(0, 59), rng.randint(0, 59))
                if is_today and ts > now:
                    ts = now - timedelta(minutes=rng.randint(1, 120))
                    if ts.date() != day:
                        continue
                status = _pick(_TODAY_WEIGHTS if is_today else _STATUS_WEIGHTS, rng)

                pool = items_by_shop[shop_id]
                weights = [_ITEM_POPULARITY.get(i["name"], 2) for i in pool]
                chosen: dict[int, sqlite3.Row] = {}
                for _ in range(rng.randint(1, 4)):
                    it = rng.choices(pool, weights=weights)[0]
                    chosen[it["id"]] = it

                lines = [(it, _qty_for(it["unit"], rng)) for it in chosen.values()]
                total = round(sum(q * it["price"] for it, q in lines), 2)  # pure Python pricing
                cur = con.execute(
                    "INSERT INTO orders (shop_id, customer_id, status, total, created_at) VALUES (?, ?, ?, ?, ?)",
                    (shop_id, f"sample-cust-{rng.randint(1, 40):02d}", status, total,
                     ts.strftime("%Y-%m-%d %H:%M:%S")),
                )
                for it, q in lines:
                    con.execute(
                        "INSERT INTO order_items (order_id, item_id, quantity, unit_price) VALUES (?, ?, ?, ?)",
                        (cur.lastrowid, it["id"], q, it["price"]),
                    )
                    n_lines += 1
                n_orders += 1

        con.execute("INSERT INTO settings (key, value) VALUES ('demo_data', '1')")
        con.commit()
    finally:
        con.close()

    return {"shops": len(seed_mod.SHOPS), "orders": n_orders, "order_items": n_lines, "path": db_path}


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description="Create a SAMPLE-data SQLite DB for demos/screenshots.")
    parser.add_argument("--db", default=DEFAULT_DEMO_DB, help="new DB file to create (default: data/demo.db)")
    parser.add_argument("--days", type=int, default=30, help="days of order history (default: 30)")
    parser.add_argument("--seed", type=int, default=42, help="random seed for reproducible data")
    args = parser.parse_args(argv)

    result = build_demo_db(args.db, days=args.days, seed=args.seed)
    print("⚠️  SAMPLE DATA — for screenshots/demos only, not real orders.")
    print(f"✅ Created {result['path']}: {result['shops']} shops, {result['orders']} orders, "
          f"{result['order_items']} order lines over {args.days} days.")
    print(f"   Run: DB_PATH={os.path.relpath(result['path'], ROOT)} uvicorn web.app:app --port 2627")
    return result


if __name__ == "__main__":
    sys.path.insert(0, ROOT)
    main()
