"""
data/seed.py — Seed the Sollunga database with 6 sample items.

Usage:
    python data/seed.py
"""

import json
import os
import sqlite3
import sys

# Allow running from any directory
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

DB_PATH = os.path.join(ROOT, "data", "sollunga.db")
SCHEMA_PATH = os.path.join(ROOT, "data", "schema.sql")

ITEMS = [
    {
        "name": "rice",
        "aliases": ["arisi", "ryce", "rice", "chawal"],
        "unit": "kg",
        "price": 55.0,
        "stock": 100.0,
    },
    {
        "name": "sugar",
        "aliases": ["sakkarai", "chini", "sugar", "shakkar"],
        "unit": "kg",
        "price": 45.0,
        "stock": 50.0,
    },
    {
        "name": "oil",
        "aliases": ["ennai", "oil", "tel", "sunflower oil", "gingelly oil", "nallennai"],
        "unit": "litre",
        "price": 150.0,
        "stock": 30.0,
    },
    {
        "name": "dal",
        "aliases": ["paruppu", "dal", "dhal", "toor dal", "moong dal", "urad dal"],
        "unit": "kg",
        "price": 110.0,
        "stock": 40.0,
    },
    {
        "name": "salt",
        "aliases": ["uppu", "salt", "namak"],
        "unit": "kg",
        "price": 20.0,
        "stock": 60.0,
    },
    {
        "name": "wheat flour",
        "aliases": ["maida", "atta", "godhumai maavu", "wheat flour", "chakki atta"],
        "unit": "kg",
        "price": 42.0,
        "stock": 80.0,
    },
]


def seed():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    # Apply schema
    with open(SCHEMA_PATH, "r") as f:
        cur.executescript(f.read())

    # Insert items (upsert by name)
    for item in ITEMS:
        cur.execute(
            """
            INSERT INTO items (name, aliases, unit, price, stock)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                aliases = excluded.aliases,
                unit    = excluded.unit,
                price   = excluded.price,
                stock   = excluded.stock
            """,
            (
                item["name"],
                json.dumps(item["aliases"]),
                item["unit"],
                item["price"],
                item["stock"],
            ),
        )

    con.commit()
    con.close()

    print(f"✅ Seeded {len(ITEMS)} items into {DB_PATH}")
    for item in ITEMS:
        print(
            f"   • {item['name']:15s} — ₹{item['price']:.2f}/{item['unit']}"
            f"  | stock: {item['stock']} {item['unit']}"
            f"  | aliases: {', '.join(item['aliases'])}"
        )


if __name__ == "__main__":
    seed()
