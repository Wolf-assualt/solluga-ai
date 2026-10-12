# Sollunga — AI Order Bot for Local Indian Shops

> **"Sollunga"** means *"Tell me"* in Tamil.

A Telegram bot that lets customers order groceries in Tamil, English, or Tanglish. It understands natural language, checks stock, shows prices, and confirms orders — all powered by Gemini (free tier).

---

## Features

- 🗣️ **Multilingual** — Tamil, English, Tanglish
- 🤖 **AI extraction** — Gemini extracts items/quantities; Python handles all pricing and stock
- 📦 **Stock awareness** — automatically caps quantities if stock is low
- ✅ **One-tap confirm** — inline Confirm / Cancel buttons
- 🗄️ **SQLite** — zero-config database with persistent orders

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey) (free)

### 2. Clone and set up

```bash
git clone <repo-url>
cd "Solluga AI"

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Edit .env and fill in your keys:
#   TELEGRAM_BOT_TOKEN=...
#   LLM_API_KEY=...        (Gemini API key)
#   LLM_MODEL=gemini-2.0-flash
```

### 4. Seed the database

```bash
python data/seed.py
```

You'll see 6 items seeded: rice, sugar, oil, dal, salt, wheat flour.

### 5. Run the bot

```bash
python -m bot.main
```

Open Telegram, find your bot, and send:
> `Anna 2 kg arisi, 1 litre ennai venum`

---

## Running Tests

```bash
# All tests (no LLM calls — everything is mocked)
pytest tests/ -v

# Specific test files
pytest tests/test_matcher.py -v
pytest tests/test_order.py -v
pytest tests/test_extraction.py -v
```

---

## Project Structure

```
Solluga AI/
├── AGENTS.md          # AI agent rules and architecture
├── .env.example       # Environment variable template
├── requirements.txt
│
├── bot/               # Telegram bot layer
│   ├── main.py        # Entry point
│   ├── handlers.py    # Message & callback handlers
│   ├── keyboards.py   # Inline Confirm/Cancel buttons
│   ├── session.py     # Per-user draft storage
│   └── messages.py    # Multilingual message formatters
│
├── core/              # Business logic (no Telegram here)
│   ├── llm.py         # LLM wrapper — extraction only
│   ├── matcher.py     # Alias + fuzzy item matching
│   ├── order.py       # Order pipeline: stock check, totals
│   └── db.py          # SQLite queries
│
├── data/
│   ├── schema.sql     # Table definitions
│   └── seed.py        # Sample data seeder
│
└── tests/
    ├── test_matcher.py    # Alias + fuzzy matching tests
    ├── test_order.py      # Order logic tests
    └── test_extraction.py # LLM parsing tests (10 Tanglish samples)
```

---

## Switching LLM Providers

Edit `.env` — any OpenAI-compatible endpoint works:

```env
# OpenAI
LLM_BASE_URL=https://api.openai.com/v1/
LLM_MODEL=gpt-4o-mini

# Groq
LLM_BASE_URL=https://api.groq.com/openai/v1/
LLM_MODEL=llama-3.1-8b-instant

# Ollama (local)
LLM_BASE_URL=http://localhost:11434/v1/
LLM_MODEL=llama3.2
LLM_API_KEY=ollama
```

---

## Sample Orders to Try

| Message | Language |
|---------|----------|
| `Anna 2 kg arisi, 1 litre ennai venum` | Tanglish |
| `3 kg sakkarai kudunga` | Tamil |
| `I need 5 kg rice and 2 kg sugar please` | English |
| `oru litre ennai, randu kg uppu` | Tamil |
| `paruppu 2 kg, maida 1 kg venum bro` | Tanglish |
