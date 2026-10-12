"""
core/order.py — Order processing: stock check, total computation, confirmation.

ALL price and stock logic lives here. The LLM never touches this.
"""

from dataclasses import dataclass, field
from typing import Optional

from core.db import get_all_items, save_confirmed_order
from core.llm import extract_order_items
from core.matcher import match_all


@dataclass
class LineItem:
    """A single resolved line in a customer order."""
    item_id: int
    item_name: str
    unit: str
    unit_price: float
    requested_qty: float
    offered_qty: float          # may be less than requested if stock is low
    stock_short: bool = False   # True if we had to cap the qty


@dataclass
class OrderDraft:
    """Intermediate state after processing a customer message."""
    lines: list[LineItem] = field(default_factory=list)
    unknown_items: list[str] = field(default_factory=list)   # names LLM found but DB doesn't know
    total: float = 0.0

    def compute_total(self) -> float:
        self.total = sum(li.offered_qty * li.unit_price for li in self.lines)
        return self.total

    def has_issues(self) -> bool:
        return bool(self.unknown_items) or any(li.stock_short for li in self.lines)


def process_message(message: str, shop_id: Optional[int] = None) -> OrderDraft:
    """
    Full pipeline for a customer message:
      1. Extract items via LLM
      2. Match to DB items for this specific shop
      3. Check stock
      4. Compute totals

    Returns an OrderDraft (never raises — errors surface as unknown_items).
    """
    draft = OrderDraft()

    # Step 1: Extract
    extracted = extract_order_items(message)
    if not extracted:
        return draft  # nothing to process

    # Step 2: Load DB items for target shop and match
    db_items = get_all_items(shop_id=shop_id)
    matches = match_all(extracted, db_items)

    # Step 3 & 4: Stock check + total
    for m in matches:
        ext = m["extracted"]
        db_item = m["matched"]

        if db_item is None:
            draft.unknown_items.append(ext["item"])
            continue

        requested_qty = ext["qty"]
        available = db_item["stock"]

        if available <= 0:
            # Completely out of stock — treat as short
            draft.unknown_items.append(ext["item"])  # will trigger "out of stock" message
            continue

        offered_qty = min(requested_qty, available)
        short = offered_qty < requested_qty

        draft.lines.append(
            LineItem(
                item_id=db_item["id"],
                item_name=db_item["name"],
                unit=db_item["unit"],
                unit_price=db_item["price"],
                requested_qty=requested_qty,
                offered_qty=offered_qty,
                stock_short=short,
            )
        )

    draft.compute_total()
    return draft


def confirm_order(customer_id: str, draft: OrderDraft, shop_id: int = 1) -> int:
    """
    Persist the confirmed order and deduct stock for the shop.
    Returns the saved order_id.
    """
    if not draft.lines:
        raise ValueError("Cannot confirm an empty order")

    line_items = [
        {
            "item_id": li.item_id,
            "quantity": li.offered_qty,
            "unit_price": li.unit_price,
        }
        for li in draft.lines
    ]
    order_id = save_confirmed_order(
        customer_id=customer_id,
        line_items=line_items,
        total=draft.total,
        shop_id=shop_id,
    )
    return order_id

