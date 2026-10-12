"""
tests/test_matcher.py — Unit tests for item alias + fuzzy matching.
"""

import pytest
from core.matcher import match_item, match_all

# Minimal DB items fixture (no DB needed)
SAMPLE_ITEMS = [
    {"id": 1, "name": "rice",       "aliases": ["arisi", "ryce", "rice", "chawal"],                      "unit": "kg",     "price": 55.0,  "stock": 100.0},
    {"id": 2, "name": "sugar",      "aliases": ["sakkarai", "chini", "sugar", "shakkar"],                 "unit": "kg",     "price": 45.0,  "stock": 50.0},
    {"id": 3, "name": "oil",        "aliases": ["ennai", "oil", "tel", "sunflower oil", "nallennai"],      "unit": "litre",  "price": 150.0, "stock": 30.0},
    {"id": 4, "name": "dal",        "aliases": ["paruppu", "dal", "dhal", "toor dal", "moong dal"],       "unit": "kg",     "price": 110.0, "stock": 40.0},
    {"id": 5, "name": "salt",       "aliases": ["uppu", "salt", "namak"],                                  "unit": "kg",     "price": 20.0,  "stock": 60.0},
    {"id": 6, "name": "wheat flour","aliases": ["maida", "atta", "godhumai maavu", "wheat flour"],         "unit": "kg",     "price": 42.0,  "stock": 80.0},
]


class TestExactMatch:
    def test_canonical_english_name(self):
        assert match_item("rice", SAMPLE_ITEMS)["id"] == 1

    def test_tamil_alias_arisi(self):
        assert match_item("arisi", SAMPLE_ITEMS)["id"] == 1

    def test_tamil_alias_sakkarai(self):
        assert match_item("sakkarai", SAMPLE_ITEMS)["id"] == 2

    def test_tamil_alias_ennai(self):
        assert match_item("ennai", SAMPLE_ITEMS)["id"] == 3

    def test_tamil_alias_paruppu(self):
        assert match_item("paruppu", SAMPLE_ITEMS)["id"] == 4

    def test_tamil_alias_uppu(self):
        assert match_item("uppu", SAMPLE_ITEMS)["id"] == 5

    def test_hindi_alias_chawal(self):
        assert match_item("chawal", SAMPLE_ITEMS)["id"] == 1

    def test_case_insensitive(self):
        assert match_item("ARISI", SAMPLE_ITEMS)["id"] == 1

    def test_multiword_alias(self):
        assert match_item("toor dal", SAMPLE_ITEMS)["id"] == 4


class TestFuzzyMatch:
    def test_typo_ryce(self):
        # "ryce" is actually in aliases, so this is exact, but also tests that exact wins
        assert match_item("ryce", SAMPLE_ITEMS)["id"] == 1

    def test_fuzzy_arisii_typo(self):
        # "arisii" should fuzzy-match to "arisi"
        result = match_item("arisii", SAMPLE_ITEMS)
        assert result is not None
        assert result["id"] == 1

    def test_fuzzy_sakkari(self):
        result = match_item("sakkari", SAMPLE_ITEMS)
        assert result is not None
        assert result["id"] == 2

    def test_no_match_garbage(self):
        result = match_item("xyzabc123", SAMPLE_ITEMS)
        assert result is None

    def test_empty_string(self):
        assert match_item("", SAMPLE_ITEMS) is None


class TestMatchAll:
    def test_multiple_items(self):
        extracted = [
            {"item": "arisi", "qty": 2, "unit": "kg"},
            {"item": "ennai", "qty": 1, "unit": "litre"},
        ]
        results = match_all(extracted, SAMPLE_ITEMS)
        assert len(results) == 2
        assert results[0]["matched"]["id"] == 1
        assert results[1]["matched"]["id"] == 3

    def test_unknown_item_returns_none(self):
        extracted = [{"item": "potato", "qty": 1, "unit": "kg"}]
        results = match_all(extracted, SAMPLE_ITEMS)
        assert results[0]["matched"] is None

    def test_empty_extracted(self):
        results = match_all([], SAMPLE_ITEMS)
        assert results == []
