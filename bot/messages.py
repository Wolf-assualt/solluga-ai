"""
bot/messages.py — Multilingual message formatters.

Detects whether the customer used Tamil/Tanglish or plain English and
replies accordingly. All formatting logic lives here — handlers just call
these functions.
"""

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
        return (
            "🤔 Order puriyala. Meendum sollunga!\n"
            "Example: *'2 kg arisi, 1 litre ennai venum'*"
        )
    return (
        "🤔 I couldn't find any items in your message. Please try again!\n"
        "Example: *'2 kg rice, 1 litre oil please'*"
    )


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
        "Type your order below 👇"
    )
