-- schema.sql: Sollunga DB schema (Multi-shop ready)

CREATE TABLE IF NOT EXISTS shops (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,              -- e.g. "Karthik Maligai Store"
    slug        TEXT    NOT NULL UNIQUE,       -- e.g. "karthik-kirana"
    owner_id    TEXT    NOT NULL DEFAULT '',   -- Telegram or WhatsApp owner user ID
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS items (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id  INTEGER NOT NULL DEFAULT 1,       -- Multi-shop support (defaults to shop 1)
    name     TEXT    NOT NULL,                 -- canonical English name
    aliases  TEXT    NOT NULL DEFAULT '[]',    -- JSON array of alias strings
    unit     TEXT    NOT NULL,                 -- "kg", "litre", "piece", etc.
    price    REAL    NOT NULL,                 -- price per unit (INR)
    stock    REAL    NOT NULL DEFAULT 0,       -- available stock in units
    UNIQUE(shop_id, name)
);

CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    shop_id     INTEGER NOT NULL DEFAULT 1,    -- Multi-shop support (defaults to shop 1)
    customer_id TEXT    NOT NULL,              -- Telegram/WhatsApp user_id as string
    status      TEXT    NOT NULL DEFAULT 'pending',  -- pending | confirmed | accepted | rejected | delivered | cancelled
    total       REAL    NOT NULL DEFAULT 0,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS order_items (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id   INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    item_id    INTEGER NOT NULL REFERENCES items(id),
    quantity   REAL    NOT NULL,
    unit_price REAL    NOT NULL               -- snapshot of price at order time
);

CREATE TABLE IF NOT EXISTS customer_shops (
    customer_id TEXT PRIMARY KEY,              -- Telegram or WhatsApp user ID
    shop_id     INTEGER NOT NULL REFERENCES shops(id),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Simple key-value store for dashboard/owner settings.
-- e.g. key='sales_reset_at' holds the baseline for the resettable
-- "total sold" counter (orders before this moment are excluded).
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

