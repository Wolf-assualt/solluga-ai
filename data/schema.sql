-- schema.sql: Sollunga DB schema

CREATE TABLE IF NOT EXISTS items (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    name     TEXT    NOT NULL UNIQUE,          -- canonical English name
    aliases  TEXT    NOT NULL DEFAULT '[]',    -- JSON array of alias strings
    unit     TEXT    NOT NULL,                 -- "kg", "litre", "piece", etc.
    price    REAL    NOT NULL,                 -- price per unit (INR)
    stock    REAL    NOT NULL DEFAULT 0        -- available stock in units
);

CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT    NOT NULL,              -- Telegram user_id as string
    status      TEXT    NOT NULL DEFAULT 'pending',  -- pending | confirmed | cancelled
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
