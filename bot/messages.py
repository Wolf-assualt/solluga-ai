"""
bot/messages.py — Multilingual message formatters.

Detects whether the customer used Tamil/Tanglish or plain English and
replies accordingly. All formatting logic lives here — handlers just call
these functions.
"""

import re
from typing import Optional
from core.order import LineItem, OrderDraft

# ---------------------------------------------------------------------------
# Language detection (very lightweight heuristic)
# ---------------------------------------------------------------------------

_TAMIL_KEYWORDS = {
    "venum", "vendum", "kudunga", "anna", "akka", "enna", "edhu",
    "arisi", "ennai", "sakkarai", "uppu", "paruppu", "maavu",
    "litre", "kilo", "kг",
}


def _is_tanglish(text: str) -> bool:
    """Return True if the message contains Tamil/Tanglish words."""
    words = set(text.lower().split())
    return bool(words & _TAMIL_KEYWORDS)


# ---------------------------------------------------------------------------
# Order summary
# ---------------------------------------------------------------------------

def format_order_summary(draft: OrderDraft, user_text: str = "") -> str:
    """
    Format the order summary with per-item prices and total.
    Includes a note if any items were short or unknown.
    """
    tanglish = _is_tanglish(user_text)
    lines_text = []

    for li in draft.lines:
        subtotal = li.offered_qty * li.unit_price
        qty_str = (
            f"{li.offered_qty:g} {li.unit}"
            if li.offered_qty == int(li.offered_qty)
            else f"{li.offered_qty:.3g} {li.unit}"
        )
        line = f"  • {li.item_name.title():15s} {qty_str:12s} @ ₹{li.unit_price:.2f} = ₹{subtotal:.2f}"
        if li.stock_short:
            if tanglish:
                line += f" ⚠️ (only {li.offered_qty:g} {li.unit} irukku)"
            else:
                line += f" ⚠️ (only {li.offered_qty:g} {li.unit} available)"
        lines_text.append(line)

    unknown_section = ""
    if draft.unknown_items:
        items_str = ", ".join(f'"{x}"' for x in draft.unknown_items)
        if tanglish:
            unknown_section = f"\n\n❓ Ithu puriyala: {items_str}. Correct ah sollunga!"
        else:
            unknown_section = f"\n\n❓ I don't recognise: {items_str}. Could you clarify?"

    body = "\n".join(lines_text)

    if tanglish:
        header = "📋 *Ungal order:*\n"
        footer = f"\n\n💰 *Total: ₹{draft.total:.2f}*\n\nConfirm pannalama? 👇"
    else:
        header = "📋 *Your order:*\n"
        footer = f"\n\n💰 *Total: ₹{draft.total:.2f}*\n\nShall I confirm this? 👇"

    return header + body + unknown_section + footer


def format_confirmed(order_id: int, total: float, user_text: str = "") -> str:
    tanglish = _is_tanglish(user_text)
    if tanglish:
        return (
            f"✅ Order #{order_id} confirm aagiduchi!\n"
            f"💰 Total: ₹{total:.2f}\n"
            f"Nandri! 🙏"
        )
    return (
        f"✅ Order #{order_id} confirmed!\n"
        f"💰 Total: ₹{total:.2f}\n"
        f"Thank you! 🙏"
    )


def format_cancelled(user_text: str = "") -> str:
    tanglish = _is_tanglish(user_text)
    if tanglish:
        return "❌ Order cancel aagiduchi. Vera enna venum?"
    return "❌ Order cancelled. What else can I help you with?"


def format_empty_order(user_text: str = "") -> str:
    tanglish = _is_tanglish(user_text)
    if tanglish:
        return "🤔 Order puriyala. Meendum sollunga!"
    return "🤔 I couldn't find any items in your message. Please try again!"


def format_only_unknowns(unknown_items: list[str], user_text: str = "") -> str:
    tanglish = _is_tanglish(user_text)
    items_str = ", ".join(f'"{x}"' for x in unknown_items)
    if tanglish:
        return f"❓ {items_str} — ithu kadasiyil illai. Vera enna venum?"
    return f"❓ Sorry, {items_str} — not found in stock. Anything else?"


def format_welcome() -> str:
    return (
        "👋 *Vanakkam! Sollunga — AI Order Bot*\n\n"
        "Tamil, English, or Tanglish la order sollunga!\n\n"
        "Example:\n"
        "  • *'2 kg arisi, 1 litre ennai venum'*\n"
        "  • *'Anna 3 kg sugar and 1 kg salt please'*\n\n"
        "💡 *Tip:* Type *'stock'* to see all available items & prices.\n"
        "Type your order below 👇"
    )


_STOCK_INQUIRY_PATTERNS = [
    r"\bstock\b",
    r"\bstocks\b",
    r"\bitems\b",
    r"\bmenu\b",
    r"\blist\b",
    r"\bavailable\b",
    r"enna.*iruk+u",
    r"kadayila.*enna",
    r"what.*do you have",
    r"what.*items",
    r"what.*available",
    r"what.*in stock",
    r"what.*products",
    r"price.*list",
    r"item.*list",
    r"stock.*iruk+a",
    r"porul.*iruk+u",
    r"porul.*list",
]


def is_stock_inquiry(text: str) -> bool:
    """Detect if customer is asking about stock or available items."""
    t = text.lower().strip()
    if not t:
        return False
    if t in ("/stock", "stock", "/stocks", "stocks", "/items", "items", "/menu", "menu", "list", "/list"):
        return True
    if any(re.search(p, t) for p in _STOCK_INQUIRY_PATTERNS):
        # Don't intercept if user specified clear order quantities with desire verb
        order_match = re.search(r"\b\d+\s*(?:kg|litre|liter|g|packet|packets|piece|pieces)\b", t)
        wants_word = re.search(r"\b(?:venum|kudunga|kodu|please|send)\b", t)
        if order_match and wants_word:
            return False
        return True
    return False


def format_customer_stock_list(items: list, shop_name: str = "") -> str:
    """Format available items for a customer in a friendly Tanglish style."""
    available = []
    for it in items:
        stock_val = it["stock"] if isinstance(it, dict) else getattr(it, "stock", 0)
        if stock_val > 0:
            available.append(it)

    if not available:
        return "📦 Ippo items ethuvum stock la illai. Please check back later!"

    header = f"🏪 *{shop_name} — Available Items & Prices:*\n" if shop_name else "🏪 *Available Items & Prices:*\n"
    lines = [header]

    for it in available:
        name = (it["name"] if isinstance(it, dict) else getattr(it, "name", "")).title()
        unit = it["unit"] if isinstance(it, dict) else getattr(it, "unit", "")
        price = it["price"] if isinstance(it, dict) else getattr(it, "price", 0.0)
        stock = it["stock"] if isinstance(it, dict) else getattr(it, "stock", 0.0)
        lines.append(f"• *{name}* — ₹{price:.2f} / {unit}  _(In Stock: {stock:g} {unit})_")

    lines.append("\n🛒 *Order panna:* Type your order below 👇")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Owner message formatters (Phase 2)
# ---------------------------------------------------------------------------

def format_stock_list(stock_rows: list) -> str:
    """Format inventory list with price and stock levels."""
    if not stock_rows:
        return "📦 No items in inventory."

    lines = ["📦 *Current Stock & Prices:*"]
    for row in stock_rows:
        status_badge = " ⚠️ *LOW*" if row.is_low else ""
        lines.append(
            f"• *{row.name.title()}*: {row.stock:g} {row.unit} | ₹{row.price:.2f}/{row.unit}{status_badge}"
        )
    return "\n".join(lines)


def format_owner_new_order(order_summary, customer_name: str = "") -> str:
    """Format notification sent to owner when customer confirms an order."""
    cust_display = customer_name if customer_name else f"Customer `{order_summary.customer_id}`"
    lines = [
        f"🔔 *New Confirmed Order #{order_summary.order_id}*",
        f"👤 *Customer:* {cust_display}",
        f"🕒 *Time:* {order_summary.created_at}",
        "\n*Items:*",
    ]
    for it in order_summary.items:
        lines.append(f"  • {it['name'].title()}: {it['qty']:g} {it['unit']} @ ₹{it['unit_price']:.2f}")

    lines.append(f"\n💰 *Total: ₹{order_summary.total:.2f}*")
    lines.append(f"📌 *Status:* `{order_summary.status.upper()}`")
    return "\n".join(lines)


def format_low_stock_alert(low_items: list) -> str:
    """Format low-stock alert for the owner."""
    if not low_items:
        return ""
    lines = ["🚨 *Low Stock Alert!*"]
    for item in low_items:
        lines.append(f"• *{item.name.title()}*: only {item.stock:g} {item.unit} remaining!")
    lines.append("\nPlease restock soon using `/addstock <item> <qty>`.")
    return "\n".join(lines)


def format_todays_orders(orders: list) -> str:
    """Format list of orders created today."""
    if not orders:
        return "📋 No orders placed today yet."

    lines = [f"📋 *Today's Orders ({len(orders)}):*"]
    for o in orders:
        items_summary = ", ".join(f"{it['qty']:g} {it['unit']} {it['name']}" for it in o.items)
        lines.append(
            f"• *#{o.order_id}* ({o.status}) - ₹{o.total:.2f}\n"
            f"   Customer: `{o.customer_id}` | {items_summary or 'No items'}"
        )
    return "\n".join(lines)


def format_todays_sales(total_sales: float, order_count: int) -> str:
    """Format total sales for today."""
    return (
        f"📊 *Today's Sales Summary*\n\n"
        f"• Total Orders (confirmed/accepted/delivered): *{order_count}*\n"
        f"• Total Sales Amount: *₹{total_sales:.2f}*"
    )


def format_qr_payment_caption(order_id: int, total: float) -> str:
    """Caption sent along with the payment QR after the owner confirms an order."""
    return (
        f"🧾 *Order #{order_id}* — Total: *₹{total:.2f}*\n\n"
        f"Scan & pay with any UPI app (GPay / PhonePe / Paytm).\n"
        f"Payment confirm aana udane order prepare pannuvom. Nandri! 🙏"
    )


def format_customer_status_update(order_id: int, new_status: str) -> str:
    """Notification sent to customer when owner changes order status."""
    if new_status == "accepted":
        return f"🎉 *Order Update:* Your order #{order_id} has been *ACCEPTED* by the shop owner! It is being prepared."
    elif new_status == "rejected":
        return f"⚠️ *Order Update:* Your order #{order_id} has been *CANCELLED / REJECTED* by the shop. Please contact the shop if you have questions."
    elif new_status == "delivered":
        return f"🚚 *Order Update:* Your order #{order_id} has been *DELIVERED*! Thank you for ordering with us! 🙏"
    return f"ℹ️ *Order Update:* Order #{order_id} status changed to *{new_status.upper()}*."

