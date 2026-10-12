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
│
├── bot/
│   ├── __init__.py
│   ├── main.py                # Telegram bot entry point
│   ├── handlers.py            # Telegram message/callback handlers
│   ├── keyboards.py           # Inline keyboard builders (Confirm/Cancel)
│   ├── session.py             # Per-user conversation state
│   └── messages.py            # Message templates (multilingual)
│
├── core/
│   ├── __init__.py
│   ├── llm.py                 # LLM wrapper — extraction only
│   ├── matcher.py             # Alias + fuzzy item matching
│   ├── order.py               # Order logic: stock check, total, confirm
│   └── db.py                  # DB connection and queries
│
├── data/
│   ├── schema.sql             # Table definitions
│   └── seed.py                # Seed script with 6 sample items
│
└── tests/
    ├── __init__.py
    ├── test_matcher.py        # Tests for item matching
    ├── test_order.py          # Tests for order logic
    └── test_extraction.py     # Tests for LLM extraction (10 Tanglish samples)
```

---

## Database Schema

| Table        | Key Columns                                              |
|--------------|----------------------------------------------------------|
| `items`      | id, name, aliases (JSON), unit, price, stock             |
| `orders`     | id, customer_id, status, total, created_at               |
| `order_items`| id, order_id, item_id, quantity, unit_price              |

---

## LLM Provider

Configured via `.env`:
- `LLM_BASE_URL` — OpenAI-compatible endpoint (default: Gemini free tier)
- `LLM_API_KEY` — API key
- `LLM_MODEL` — Model name (default: `gemini-2.0-flash`)

---

## Phase Roadmap

- **Phase 1** ✅ — Core order bot (this phase)
- **Phase 2** — Shop owner dashboard
- **Phase 3** — Multi-shop support
