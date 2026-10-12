"""
tests/test_order.py — Unit tests for order processing logic.

These tests use a patched DB so no real database is needed.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

from core.order import LineItem, OrderDraft, process_message, confirm_order

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_ITEMS = [
    {"id": 1, "name": "rice",        "aliases": ["arisi", "rice", "chawal"],        "unit": "kg",    "price": 55.0,  "stock": 100.0},
    {"id": 2, "name": "sugar",       "aliases": ["sakkarai", "sugar"],              "unit": "kg",    "price": 45.0,  "stock": 50.0},
    {"id": 3, "name": "oil",         "aliases": ["ennai", "oil"],                   "unit": "litre", "price": 150.0, "stock": 5.0},   # low stock!
    {"id": 4, "name": "dal",         "aliases": ["paruppu", "dal"],                 "unit": "kg",    "price": 110.0, "stock": 40.0},
    {"id": 5, "name": "salt",        "aliases": ["uppu", "salt"],                   "unit": "kg",    "price": 20.0,  "stock": 60.0},
    {"id": 6, "name": "wheat flour", "aliases": ["maida", "atta", "wheat flour"],   "unit": "kg",    "price": 42.0,  "stock": 80.0},
]


def _mock_process(message: str, extracted: list[dict]) -> OrderDraft:
    """Run process_message with patched LLM and DB."""
    with (
        patch("core.order.extract_order_items", return_value=extracted),
        patch("core.order.get_all_items", return_value=SAMPLE_ITEMS),
    ):
        return process_message(message)


# ---------------------------------------------------------------------------
# Basic order tests
# ---------------------------------------------------------------------------

class TestBasicOrders:
    def test_simple_rice_order(self):
        draft = _mock_process("arisi 2 kg", [{"item": "arisi", "qty": 2, "unit": "kg"}])
        assert len(draft.lines) == 1
        assert draft.lines[0].item_name == "rice"
        assert draft.lines[0].offered_qty == 2
        assert draft.total == pytest.approx(110.0)

    def test_multi_item_order(self):
        extracted = [
            {"item": "arisi", "qty": 3, "unit": "kg"},
            {"item": "sakkarai", "qty": 1, "unit": "kg"},
        ]
        draft = _mock_process("test", extracted)
        assert len(draft.lines) == 2
        # 3*55 + 1*45 = 165 + 45 = 210
        assert draft.total == pytest.approx(210.0)

    def test_unknown_item_goes_to_unknown_list(self):
        extracted = [{"item": "potato", "qty": 1, "unit": "kg"}]
        draft = _mock_process("test", extracted)
        assert len(draft.lines) == 0
        assert "potato" in draft.unknown_items

    def test_empty_extraction(self):
        draft = _mock_process("hi how are you", [])
        assert draft.lines == []
        assert draft.unknown_items == []
        assert draft.total == 0.0


class TestStockChecks:
    def test_short_stock_caps_quantity(self):
        # Oil has stock=5, customer wants 10
        extracted = [{"item": "ennai", "qty": 10, "unit": "litre"}]
        draft = _mock_process("10 litre ennai", extracted)
        assert len(draft.lines) == 1
        line = draft.lines[0]
        assert line.stock_short is True
        assert line.offered_qty == 5.0
        assert line.requested_qty == 10.0

    def test_exact_stock_no_short(self):
        # Oil has stock=5, customer wants exactly 5
        extracted = [{"item": "ennai", "qty": 5, "unit": "litre"}]
        draft = _mock_process("5 litre ennai", extracted)
        assert draft.lines[0].stock_short is False
        assert draft.lines[0].offered_qty == 5.0

    def test_has_issues_with_short_stock(self):
        extracted = [{"item": "ennai", "qty": 10, "unit": "litre"}]
        draft = _mock_process("test", extracted)
        assert draft.has_issues() is True

    def test_no_issues_normal_order(self):
        extracted = [{"item": "arisi", "qty": 2, "unit": "kg"}]
        draft = _mock_process("test", extracted)
        assert draft.has_issues() is False


class TestTotalComputation:
    def test_total_matches_sum_of_lines(self):
        extracted = [
            {"item": "arisi", "qty": 2,   "unit": "kg"},    # 2*55 = 110
            {"item": "uppu",  "qty": 0.5, "unit": "kg"},    # 0.5*20 = 10
        ]
        draft = _mock_process("test", extracted)
        expected = sum(li.offered_qty * li.unit_price for li in draft.lines)
        assert draft.total == pytest.approx(expected)
        assert draft.total == pytest.approx(120.0)


class TestConfirmOrder:
    def test_confirm_calls_save(self):
        draft = OrderDraft(
            lines=[
                LineItem(
                    item_id=1,
                    item_name="rice",
                    unit="kg",
                    unit_price=55.0,
                    requested_qty=2,
                    offered_qty=2,
                )
            ],
            total=110.0,
        )
        with patch("core.order.save_confirmed_order", return_value=42) as mock_save:
            order_id = confirm_order("user123", draft)
        assert order_id == 42
        mock_save.assert_called_once()
        call_kwargs = mock_save.call_args
        assert call_kwargs.kwargs["total"] == pytest.approx(110.0)

    def test_confirm_empty_draft_raises(self):
        with pytest.raises(ValueError, match="empty"):
            confirm_order("user123", OrderDraft())
