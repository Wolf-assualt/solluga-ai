# AGENTS.md — Sollunga AI Order Bot

## Project Overview

**Sollunga** ("Tell me" in Tamil) is an AI-powered order-taking bot for local Indian shops, accessible via Telegram. Customers can place orders in Tamil, English, or Tanglish and get instant price + stock confirmations.

---

## Rules & Constraints

### LLM Rules (CRITICAL)
- The LLM **ONLY** extracts items and quantities as JSON: `[{"item": "...", "qty": 2, "unit": "kg"}]`
- The LLM **MUST NEVER** calculate prices, check stock, or compute totals
- All price and stock logic is **plain Python only**
- LLM output must be validated and parsed defensively

### Matching Rules
- Match extracted item names to DB using aliases (arisi→rice, sakkarai→sugar, ennai/oil→oil, etc.)
- Use fuzzy matching as fallback (difflib or rapidfuzz)
- Unknown item: ask the customer to clarify
- Short stock: offer available quantity to the customer

### Language Rules
- Detect and reply in the same language style the customer used (Tamil, English, Tanglish)
- Be friendly and conversational

---

## Project Structure

```
Solluga AI/
├── AGENTS.md                  # This file — rules and structure
├── README.md                  # Setup and run instructions
├── .env.example               # Template for environment variables
├── .gitignore                 # Excludes .env and other secrets
├── requirements.txt           # Python dependencies
├── run.sh                     # Launch both Telegram bot & Web dashboard
│
├── bot/
│   ├── __init__.py
│   ├── main.py                # Telegram bot entry point
│   ├── handlers.py            # Telegram customer handlers & voice note support
│   ├── owner_handlers.py      # Telegram owner handlers & callbacks (Phase 2)
│   ├── keyboards.py           # Inline keyboard builders (Confirm/Cancel, Accept/Reject/Delivered)
│   ├── session.py             # Per-user conversation state
│   └── messages.py            # Message templates (multilingual + owner)
│
├── core/
│   ├── __init__.py
│   ├── channel.py             # Channel abstraction interface & FakeChannel (Phase 4)
│   ├── service.py             # Channel-independent order service (Phase 4)
│   ├── whatsapp.py            # WhatsApp Cloud API client & webhook parser (Phase 4)
│   ├── transcription.py       # Voice note speech-to-text with Gemini (Phase 4)
│   ├── telegram_channel.py    # Telegram Channel adapter (Phase 4)
│   ├── llm.py                 # LLM wrapper — extraction only
│   ├── matcher.py             # Alias + fuzzy item matching
│   ├── order.py               # Order logic: stock check, total, confirm
│   ├── inventory.py           # Inventory, pricing, sales & reporting logic (Phase 2)
│   └── db.py                  # DB connection and queries
│
├── web/
│   ├── __init__.py
│   ├── app.py                 # FastAPI dashboard & WhatsApp webhook routes (Phase 3 & 4)
│   ├── auth.py                # Session authentication helper (Phase 3)
│   └── templates/             # Jinja2 templates (mobile-first PicoCSS)
│       ├── base.html
│       ├── login.html
│       ├── home.html
│       ├── items.html
│       ├── item_new.html
│       ├── item_edit.html
│       ├── orders.html
│       └── sales.html
│
├── data/
│   ├── schema.sql             # Table definitions
│   └── seed.py                # Seed script with 6 sample items
│
└── tests/
    ├── __init__.py
    ├── test_matcher.py        # Tests for item matching
    ├── test_order.py          # Tests for order logic
    ├── test_inventory.py      # Tests for inventory & owner logic (Phase 2)
    ├── test_web.py            # Tests for web dashboard routes & auth (Phase 3)
    ├── test_channels.py       # Tests for Channel abstraction, WhatsApp, & Voice (Phase 4)
    └── test_extraction.py     # Tests for LLM extraction (10 Tanglish samples)
```

---

## Database Schema

| Table            | Key Columns                                              |
|------------------|----------------------------------------------------------|
| `shops`          | id, name, slug, owner_id, is_active, created_at          |
| `items`          | id, shop_id, name, aliases (JSON), unit, price, stock    |
| `orders`         | id, shop_id, customer_id, status, total, created_at      |
| `order_items`    | id, order_id, item_id, quantity, unit_price              |
| `customer_shops` | customer_id, shop_id, updated_at                         |

---

## LLM Provider

Configured via `.env`:
- `LLM_BASE_URL` — OpenAI-compatible endpoint (default: Gemini free tier)
- `LLM_API_KEY` — API key
- `LLM_MODEL` — Model name (default: `gemini-3.1-flash-lite`, verified fast on the free tier)
- `LLM_FALLBACK_BASE_URL` — Secondary fallback endpoint
- `LLM_FALLBACK_API_KEY` — Secondary fallback API key

---

## Phase Roadmap

- **Phase 1** ✅ — Core order bot (Telegram)
- **Phase 2** ✅ — Shop owner bot & alerts
- **Phase 3** ✅ — Web dashboard
- **Phase 4** ✅ — WhatsApp & voice notes
- **Phase 5** ✅ — Multi-shop support, reliability & demo-ready

