"""
core/matcher.py — Match extracted item names to DB items.

Strategy:
1. Exact match on name or any alias (case-insensitive).
2. Prefix match on name / alias tokens.
3. Fuzzy match using rapidfuzz (WRatio scorer), threshold 70.
"""

import json
from typing import Optional

from rapidfuzz import fuzz, process


def _build_lookup(items: list[dict]) -> dict[str, dict]:
    """
    Build a flat alias → item mapping from a list of item dicts.
    Each item dict has: id, name, aliases (list[str]), unit, price, stock.
    """
    lookup: dict[str, dict] = {}
    for item in items:
        lookup[item["name"].lower()] = item
        for alias in item.get("aliases", []):
            lookup[alias.lower()] = item
    return lookup


def match_item(
    extracted_name: str,
    items: list[dict],
    fuzzy_threshold: int = 70,
) -> Optional[dict]:
    """
    Match an extracted item name to the best DB item.

    Args:
        extracted_name: The item name as extracted by the LLM.
        items: List of all item dicts from the DB.
        fuzzy_threshold: Minimum rapidfuzz score (0-100) to accept a match.

    Returns:
        The matched item dict, or None if no match found.
    """
    if not extracted_name or not items:
        return None

    query = extracted_name.lower().strip()

    # Build alias lookup
    lookup = _build_lookup(items)

    # 1. Exact match
    if query in lookup:
        return lookup[query]

    # 2. Prefix match — query is a prefix of any alias (e.g. "enn" → "ennai")
    for alias, item in lookup.items():
        if alias.startswith(query) or query.startswith(alias):
            return item

    # 3. Fuzzy match against all aliases
    all_aliases = list(lookup.keys())
    result = process.extractOne(
        query,
        all_aliases,
        scorer=fuzz.WRatio,
        score_cutoff=fuzzy_threshold,
    )
    if result:
        best_alias = result[0]
        return lookup[best_alias]

    return None


def match_all(
    extracted_items: list[dict],
    db_items: list[dict],
    fuzzy_threshold: int = 70,
) -> list[dict]:
    """
    Match a list of extracted items to DB items.

    Returns a list of result dicts:
    {
        "extracted": {"item": str, "qty": float, "unit": str},
        "matched": <item dict> | None,
    }
    """
    results = []
    for extracted in extracted_items:
        matched = match_item(
            extracted["item"], db_items, fuzzy_threshold=fuzzy_threshold
        )
        results.append({"extracted": extracted, "matched": matched})
    return results
