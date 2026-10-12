"""
data/seed.py — Seed the Sollunga database with realistic demo shops and inventory.

Usage:
    python data/seed.py
"""

import json
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB_PATH = os.path.join(ROOT, "data", "sollunga.db")
SCHEMA_PATH = os.path.join(ROOT, "data", "schema.sql")

SHOPS = [
    {
        "id": 1,
        "name": "Karthik Maligai Store (Adyar)",
        "slug": "karthik-adyar",
        "owner_id": "",
        "is_active": 1,
    },
    {
        "id": 2,
        "name": "Murugan Provisions (T. Nagar)",
        "slug": "murugan-tnagar",
        "owner_id": "",
        "is_active": 1,
    },
]

DEMO_ITEMS_SHOP_1 = [
    {
        "shop_id": 1,
        "name": "rice",
        "aliases": ["arisi", "ryce", "rice", "chawal", "ponni arisi", "basmati"],
        "unit": "kg",
        "price": 55.0,
        "stock": 100.0,
    },
    {
        "shop_id": 1,
        "name": "sugar",
        "aliases": ["sakkarai", "chini", "sugar", "shakkar", "white sugar"],
        "unit": "kg",
        "price": 45.0,
        "stock": 50.0,
    },
    {
        "shop_id": 1,
        "name": "oil",
        "aliases": ["ennai", "oil", "tel", "sunflower oil", "gingelly oil", "nallennai"],
        "unit": "litre",
        "price": 150.0,
        "stock": 3.0,  # LOW STOCK FOR DEMO ALERT
    },
    {
        "shop_id": 1,
        "name": "dal",
        "aliases": ["paruppu", "dal", "dhal", "toor dal", "moong dal", "urad dal"],
        "unit": "kg",
        "price": 110.0,
        "stock": 40.0,
    },
    {
        "shop_id": 1,
        "name": "salt",
        "aliases": ["uppu", "salt", "namak", "kallu uppu", "thool uppu"],
        "unit": "kg",
        "price": 20.0,
        "stock": 60.0,
    },
    {
        "shop_id": 1,
        "name": "wheat flour",
        "aliases": ["maida", "atta", "godhumai maavu", "wheat flour", "chakki atta"],
        "unit": "kg",
        "price": 42.0,
        "stock": 80.0,
    },
    {
        "shop_id": 1,
        "name": "tea powder",
        "aliases": ["tea", "kaapi", "chaya", "theila", "tea packet", "red label"],
        "unit": "packet",
        "price": 35.0,
        "stock": 25.0,
    },
    {
        "shop_id": 1,
        "name": "coffee powder",
        "aliases": ["coffee", "filter coffee", "bru", "sunrise", "kappi thool"],
        "unit": "packet",
        "price": 45.0,
        "stock": 18.0,
    },
    {
        "shop_id": 1,
        "name": "chilli powder",
        "aliases": ["milagai thool", "chilli powder", "mirchi", "chilli"],
        "unit": "packet",
        "price": 28.0,
        "stock": 30.0,
    },
    {
        "shop_id": 1,
        "name": "milk",
        "aliases": ["paal", "milk", "doodh", "aavin milk", "half litre milk"],
        "unit": "packet",
        "price": 30.0,
        "stock": 20.0,
    },
]

DEMO_ITEMS_SHOP_2 = [
    {
        "shop_id": 2,
        "name": "rice",
        "aliases": ["arisi", "rice", "ponni arisi"],
        "unit": "kg",
        "price": 58.0,
        "stock": 80.0,
    },
    {
        "shop_id": 2,
        "name": "sugar",
        "aliases": ["sakkarai", "sugar"],
        "unit": "kg",
        "price": 46.0,
        "stock": 40.0,
    },
    {
        "shop_id": 2,
        "name": "oil",
        "aliases": ["ennai", "oil"],
        "unit": "litre",
        "price": 155.0,
        "stock": 25.0,
    },
]


def seed():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Apply schema
    with open(SCHEMA_PATH, "r") as f:
        cur.executescript(f.read())

    # Insert / Upsert Shops
    for s in SHOPS:
        cur.execute(
            """
            INSERT INTO shops (id, name, slug, owner_id, is_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                slug = excluded.slug
            """,
            (s["id"], s["name"], s["slug"], s["owner_id"], s["is_active"]),
        )

    # Insert Items
    all_items = DEMO_ITEMS_SHOP_1 + DEMO_ITEMS_SHOP_2
    for item in all_items:
        cur.execute(
            """
            INSERT INTO items (shop_id, name, aliases, unit, price, stock)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(shop_id, name) DO UPDATE SET
                aliases = excluded.aliases,
                unit    = excluded.unit,
                price   = excluded.price,
                stock   = excluded.stock
            """,
            (
                item["shop_id"],
                item["name"],
                json.dumps(item["aliases"]),
                item["unit"],
                item["price"],
                item["stock"],
            ),
        )

    con.commit()
    con.close()

    print(f"✅ Seeded {len(SHOPS)} shops and {len(all_items)} grocery items into {DB_PATH}")
    for s in SHOPS:
        print(f"🏪 Shop #{s['id']}: {s['name']}")
    print("\n📦 Demo Shop 1 Highlights (Karthik Maligai Store):")
    for item in DEMO_ITEMS_SHOP_1[:5]:
        low_flag = " (⚠️ LOW STOCK)" if item["stock"] <= 3 else ""
        print(f"   • {item['name'].title():15s} — ₹{item['price']:.2f}/{item['unit']} | stock: {item['stock']}{low_flag}")


if __name__ == "__main__":
    seed()
