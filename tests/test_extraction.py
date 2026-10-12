"""
tests/test_extraction.py — Tests for LLM extraction output parsing.

These tests use 10 sample Tanglish / Tamil / English messages and verify
that _parse_llm_response and the overall extraction pipeline behave
correctly WITHOUT making real LLM calls.

Two layers of tests:
  1. _parse_llm_response — unit tests on the JSON parser directly.
  2. extract_order_items — integration tests with a mocked API client.
"""

import pytest
from unittest.mock import MagicMock, patch

from core.llm import _parse_llm_response, extract_order_items

# ---------------------------------------------------------------------------
# 10 sample Tanglish messages and their expected LLM JSON output
# ---------------------------------------------------------------------------

SAMPLE_CASES = [
    # (message, llm_raw_output, expected_parsed_items)
    (
        "Anna 2 kg arisi, 1 litre ennai venum",
        '[{"item": "arisi", "qty": 2, "unit": "kg"}, {"item": "ennai", "qty": 1, "unit": "litre"}]',
        [{"item": "arisi", "qty": 2.0, "unit": "kg"}, {"item": "ennai", "qty": 1.0, "unit": "litre"}],
    ),
    (
        "3 kg sakkarai kudunga",
        '[{"item": "sakkarai", "qty": 3, "unit": "kg"}]',
        [{"item": "sakkarai", "qty": 3.0, "unit": "kg"}],
    ),
    (
        "Rice 5 kilo and sugar 2 kilo please",
        '[{"item": "Rice", "qty": 5, "unit": "kg"}, {"item": "sugar", "qty": 2, "unit": "kg"}]',
        [{"item": "Rice", "qty": 5.0, "unit": "kg"}, {"item": "sugar", "qty": 2.0, "unit": "kg"}],
    ),
    (
        "oru litre ennai, randu kg uppu",
        '[{"item": "ennai", "qty": 1, "unit": "litre"}, {"item": "uppu", "qty": 2, "unit": "kg"}]',
        [{"item": "ennai", "qty": 1.0, "unit": "litre"}, {"item": "uppu", "qty": 2.0, "unit": "kg"}],
    ),
    (
        "I want 500 grams of salt and 1 kg of dal",
        '[{"item": "salt", "qty": 0.5, "unit": "kg"}, {"item": "dal", "qty": 1, "unit": "kg"}]',
        [{"item": "salt", "qty": 0.5, "unit": "kg"}, {"item": "dal", "qty": 1.0, "unit": "kg"}],
    ),
    (
        "paruppu 2 kg, maida 1 kg venum bro",
        '[{"item": "paruppu", "qty": 2, "unit": "kg"}, {"item": "maida", "qty": 1, "unit": "kg"}]',
        [{"item": "paruppu", "qty": 2.0, "unit": "kg"}, {"item": "maida", "qty": 1.0, "unit": "kg"}],
    ),
    (
        "anna 10 kg arisi, 5 kg sakkarai, 2 litre ennai venum",
        '[{"item": "arisi", "qty": 10, "unit": "kg"}, {"item": "sakkarai", "qty": 5, "unit": "kg"}, {"item": "ennai", "qty": 2, "unit": "litre"}]',
        [{"item": "arisi", "qty": 10.0, "unit": "kg"}, {"item": "sakkarai", "qty": 5.0, "unit": "kg"}, {"item": "ennai", "qty": 2.0, "unit": "litre"}],
    ),
    (
        "Give me wheat flour 2 kg and rice 1 kg",
        '[{"item": "wheat flour", "qty": 2, "unit": "kg"}, {"item": "rice", "qty": 1, "unit": "kg"}]',
        [{"item": "wheat flour", "qty": 2.0, "unit": "kg"}, {"item": "rice", "qty": 1.0, "unit": "kg"}],
    ),
    (
        "hi",
        '[]',
        [],
    ),
    (
        "nallennai 3 litre, chawal 4 kg, chini 2 kg",
        '[{"item": "nallennai", "qty": 3, "unit": "litre"}, {"item": "chawal", "qty": 4, "unit": "kg"}, {"item": "chini", "qty": 2, "unit": "kg"}]',
        [{"item": "nallennai", "qty": 3.0, "unit": "litre"}, {"item": "chawal", "qty": 4.0, "unit": "kg"}, {"item": "chini", "qty": 2.0, "unit": "kg"}],
    ),
]


# ---------------------------------------------------------------------------
# Tests for _parse_llm_response
# ---------------------------------------------------------------------------

class TestParseLlmResponse:
    @pytest.mark.parametrize("message,llm_raw,expected", SAMPLE_CASES)
    def test_parse_correct_json(self, message, llm_raw, expected):
        result = _parse_llm_response(llm_raw)
        assert result == expected, f"Failed for: {message}"

    def test_strips_markdown_fences(self):
        raw = '```json\n[{"item": "arisi", "qty": 2, "unit": "kg"}]\n```'
        result = _parse_llm_response(raw)
        assert result == [{"item": "arisi", "qty": 2.0, "unit": "kg"}]

    def test_strips_plain_code_fence(self):
        raw = '```[{"item": "rice", "qty": 1, "unit": "kg"}]```'
        result = _parse_llm_response(raw)
        assert result == [{"item": "rice", "qty": 1.0, "unit": "kg"}]

    def test_returns_empty_on_invalid_json(self):
        assert _parse_llm_response("not json at all") == []

    def test_returns_empty_on_empty_string(self):
        assert _parse_llm_response("") == []

    def test_skips_entries_without_item_key(self):
        raw = '[{"qty": 2, "unit": "kg"}, {"item": "rice", "qty": 1, "unit": "kg"}]'
        result = _parse_llm_response(raw)
        assert len(result) == 1
        assert result[0]["item"] == "rice"

    def test_defaults_qty_to_1_when_missing(self):
        raw = '[{"item": "rice", "unit": "kg"}]'
        result = _parse_llm_response(raw)
        assert result[0]["qty"] == 1.0

    def test_defaults_unit_to_piece_when_missing(self):
        raw = '[{"item": "bread", "qty": 2}]'
        result = _parse_llm_response(raw)
        assert result[0]["unit"] == "piece"


# ---------------------------------------------------------------------------
# Integration tests for extract_order_items (mocked API)
# ---------------------------------------------------------------------------

def _make_mock_response(content: str):
    """Create a minimal mock OpenAI response object."""
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


class TestExtractOrderItems:
    @pytest.mark.parametrize("message,llm_raw,expected", SAMPLE_CASES)
    def test_extract_with_mock_api(self, message, llm_raw, expected):
        mock_response = _make_mock_response(llm_raw)
        with patch("core.llm._get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = mock_response
            mock_get_client.return_value = mock_client

            result = extract_order_items(message)

        assert result == expected, f"Failed for: {message}"

    def test_returns_empty_on_api_error(self):
        with patch("core.llm._get_client") as mock_get_client:
            mock_client = MagicMock()
            mock_client.chat.completions.create.side_effect = Exception("API down")
            mock_get_client.return_value = mock_client

            result = extract_order_items("any message")
        assert result == []
