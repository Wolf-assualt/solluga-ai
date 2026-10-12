# DEMO.md — 2-Minute Sollunga AI Demo Script

This document provides a minute-by-minute live presentation script and 5-message demo sequence showcasing **Sollunga AI** ("Tell me" in Tamil) — the multilingual grocery order bot and shop management system.

---

## ⏱️ 2-Minute Demo Rundown

| Timestamp | Screen / Channel | What to Show & Narrate |
|-----------|------------------|------------------------|
| **0:00 - 0:25** | Telegram / WhatsApp | **Multi-Shop Selection & Tanglish Text Order**: Customer sends `/shops` to browse nearby kirana stores, selects "Karthik Maligai Store", and texts in natural Tanglish: `"Anna 2 kg arisi and 1 kg sakkarai venum"`. |
| **0:25 - 0:50** | Telegram / WhatsApp | **Python-Guarded Pricing & Stock Protection**: Sollunga extracts items via LLM, matches aliases (`arisi` → rice, `sakkarai` → sugar), calculates exact INR prices in Python, and presents an interactive Confirmation card. |
| **0:50 - 1:15** | Telegram / WhatsApp | **Low Stock Capping & Voice Note**: Customer asks for `"5 litre ennai"` (oil has only 3 in stock). Bot caps to available 3 litres with a polite explanation. Customer sends a Tamil voice note: `"Rendu packet tea podi kudunga"`. Voice is transcribed via Gemini and added. |
| **1:15 - 1:40** | Shop Owner Telegram | **Instant Owner Notification & Action Buttons**: Customer confirms order. Shop owner receives an immediate notification with customer details, item breakdown, total (`₹...`), and interactive buttons (`Accept`, `Delivered`, `Reject`). Low-stock alert triggers for oil. |
| **1:40 - 2:00** | Web Dashboard | **Live Web Dashboard (Mobile-First)**: Open `http://localhost:8000`. Show today's sales counter, order management with live status toggles, and instant inventory editing without reloading. |

---

## 💬 5-Message Showcase Flow

Follow these exact 5 messages to demonstrate all core capabilities in under 2 minutes:

### 1. Shop Discovery & Selection
* **Channel:** Customer Telegram or WhatsApp
* **Send:**
  ```text
  /shops
  ```
* **Expected Output:**
  ```text
  🏪 Sollunga Shops
  Current Shop: Karthik Maligai Store (Adyar)

  Change shop by replying with /shop <number>:
  • 1 - Karthik Maligai Store (Adyar) ✅
  • 2 - Murugan Provisions (T. Nagar)
  ```
* **Action:** Send `/shop 1` (or tap `[Shop 1]`) to lock in Karthik Maligai Store.

---

### 2. Tanglish Multilingual Ordering
* **Channel:** Customer Telegram or WhatsApp
* **Send:**
  ```text
  Anna 2 kg ponni arisi and 1 kg sakkarai venum
  ```
* **Bot Response:**
  ```text
  🛒 Order Summary:
  • rice (2.0 kg) — ₹110.00
  • sugar (1.0 kg) — ₹45.00

  Total: ₹155.00
  [Confirm Order] [Cancel]
  ```
* **Talking Point:** LLM extracts ONLY the entities. All prices (`₹55 * 2`, `₹45 * 1`) and calculations are executed in plain Python — zero LLM hallucination risk.

---

### 3. Smart Stock Handling (Short Stock Cap)
* **Channel:** Customer Telegram or WhatsApp
* **Send:**
  ```text
  Oru 5 litre oil venum
  ```
* **Bot Response:**
  ```text
  🛒 Order Summary:
  • oil (3.0 litre) — ₹450.00  (⚠️ only 3.0 litre available)

  Total: ₹450.00
  [Confirm Order] [Cancel]
  ```
* **Talking Point:** Database has 3 litres in stock. Sollunga caps the requested 5 litres to 3, alerts the customer transparently in Tanglish, and computes the exact total (`3 × ₹150 = ₹450`).

---

### 4. Tamil Voice Note Order
* **Channel:** Customer Telegram or WhatsApp
* **Send:** Record a short audio or voice message saying:
  > *"Oru packet tea podi kudunga"* (or in English: *"Give me one packet of tea powder"*)
* **Bot Response:**
  ```text
  🎤 Heard: "Oru packet tea podi kudunga"

  🛒 Order Summary:
  • tea dust (1.0 packet) — ₹85.00

  Total: ₹85.00
  [Confirm Order] [Cancel]
  ```
* **Action:** Tap `[✅ Confirm Order]`.
* **Bot Confirmation to Customer:**
  ```text
  🎉 Order #1 Confirmed!
  Your order has been sent to the shop owner. We will notify you once accepted.
  ```

---

### 5. Owner Real-Time Management & Dashboard
* **Step A (Owner Telegram):** Check the owner's Telegram chat (`OWNER_TELEGRAM_ID`).
  * Received alert:
    ```text
    🔔 New Order #1!
    Customer: 9876543210
    • tea dust: 1.0 packet @ ₹85.00

    Total: ₹85.00

    [Accept] [Delivered] [Reject]
    ```
  * Tap `[Delivered]` → Customer receives instant update: *"Your order #1 has been marked as Delivered!"*
* **Step B (Web Dashboard):**
  * Open `http://localhost:8000` in browser (or phone).
  * Log in with password: `sollunga123` (from `.env`).
  * Point out:
    1. **Today's Sales**: Live revenue total updated.
    2. **Low-Stock Alert**: Shows Oil (3 litres remaining).
    3. **Orders Table**: Displays Order #1 with status `delivered`.
    4. **Items Manager**: Click `Items` to adjust prices or stock in 1 click.

---

## 🛠️ Pre-Demo Checklist

1. **Database:** Seed fresh data:
   ```bash
   python data/seed.py
   ```
2. **Start Services:** Run the single launcher:
   ```bash
   ./run.sh
   ```
3. **Verify Health:** Open `http://localhost:8000/health` and verify `"status": "healthy"`.
4. **Owner Setup:** Confirm `OWNER_TELEGRAM_ID` is set to your Telegram ID in `.env`.
