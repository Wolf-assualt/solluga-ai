"""
core/llm.py — Thin LLM wrapper.

RESPONSIBILITY: Extract items + quantities from a customer message as JSON.
The LLM MUST NOT calculate prices, check stock, or compute totals.
All business logic stays in Python.
"""

import json
import os
import re
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
_API_KEY = os.getenv("LLM_API_KEY", "")
_MODEL = os.getenv("LLM_MODEL", "gemini-2.0-flash")

_SYSTEM_PROMPT = """You are a grocery order parser for a small Indian shop.

Your ONLY job is to extract item names and quantities from the customer's message and return a JSON array. Nothing else.

Rules:
- Output ONLY a valid JSON array, no prose, no markdown fences.
- Each element: {"item": "<name>", "qty": <number>, "unit": "<unit>"}
- Keep the item name exactly as the customer said it (Tamil, English, or Tanglish).
- If qty is ambiguous, default to 1.
- If unit is not specified, use "piece".
- Do NOT calculate prices. Do NOT mention stock. Do NOT greet or explain.
- If nothing can be extracted, return [].

Examples:
  Input:  "2 kg arisi venum, oru litre ennai"
  Output: [{"item": "arisi", "qty": 2, "unit": "kg"}, {"item": "ennai", "qty": 1, "unit": "litre"}]

  Input:  "Anna 3 kg sugar and 500g salt please"
  Output: [{"item": "sugar", "qty": 3, "unit": "kg"}, {"item": "salt", "qty": 0.5, "unit": "kg"}]

  Input:  "hi how are you"
  Output: []
"""


def _get_client() -> OpenAI:
    return OpenAI(api_key=_API_KEY, base_url=_BASE_URL)


def extract_order_items(message: str) -> list[dict]:
    """
    Call the LLM to extract order items from a customer message.

    Returns a list of dicts: [{"item": str, "qty": float, "unit": str}, ...]
    Returns [] if nothing could be extracted or on any error.
    """
    client = _get_client()

    try:
        response = client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": message},
            ],
            temperature=0,
            max_tokens=512,
        )
    except Exception as exc:
        print(f"[llm] API error: {exc}")
        return []

    raw = response.choices[0].message.content or ""
    return _parse_llm_response(raw)


def _parse_llm_response(raw: str) -> list[dict]:
    """
    Defensively parse the LLM output.
    Strips markdown fences if present, then JSON-decodes.
    """
    # Strip possible ```json ... ``` wrappers
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()

    # Try to find a JSON array in the response
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        return []

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return []

    if not isinstance(data, list):
        return []

    result = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        item = str(entry.get("item", "")).strip()
        if not item:
            continue
        try:
            qty = float(entry.get("qty", 1))
        except (TypeError, ValueError):
            qty = 1.0
        unit = str(entry.get("unit", "piece")).strip() or "piece"
        result.append({"item": item, "qty": qty, "unit": unit})

    return result
