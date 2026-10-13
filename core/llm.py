"""
core/llm.py — Resilient LLM client with retries, timeouts, and fallback provider.

RESPONSIBILITY: Extract items + quantities from a customer message as JSON.
The LLM MUST NOT calculate prices, check stock, or compute totals.
All business logic stays in Python.

RELIABILITY:
- Configurable timeout (default: 8s)
- Automatic retry on rate limits / network blips
- Fallback to secondary OpenAI-compatible provider (LLM_FALLBACK_BASE_URL, LLM_FALLBACK_API_KEY)
- Defensively handles malformed or unexpected responses without crashing
"""

import json
import logging
import os
import re
import time
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)

# Primary LLM provider
# NOTE: model chosen from verified-working free models for this API key.
# gemini-3.5-flash-lite / gemini-3.8-flash hang or return 429 quota errors on
# the free tier, so default to gemini-3.1-flash-lite which is fast & reliable.
_BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
_API_KEY = os.getenv("LLM_API_KEY", "")
_MODEL = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")

# Fallback LLM provider (optional)
_FALLBACK_BASE_URL = os.getenv("LLM_FALLBACK_BASE_URL", "").strip()
_FALLBACK_API_KEY = os.getenv("LLM_FALLBACK_API_KEY", "").strip()
_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL", "gemini-3.8-flash").strip()

_REQUEST_TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "25.0"))
_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "1"))

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


def _create_client(base_url: str, api_key: str) -> OpenAI:
    return OpenAI(api_key=api_key, base_url=base_url, timeout=_REQUEST_TIMEOUT)


def _get_client() -> OpenAI:
    """Return configured primary OpenAI client (mockable by test suite)."""
    return _create_client(_BASE_URL, _API_KEY)



# Verified working free Gemini models for this project's API key.
# (gemini-3.5-flash-lite / 3.6 / 3.7 / 3.8 hang or hit free-tier quota,
#  gemini-2.5-flash-lite returns 404, gemini-flash-*-latest time out.)
_DEFAULT_FREE_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-3.1-flash-lite-preview",
]


def _get_primary_models() -> list[str]:
    """Return ordered list of models to try on the primary provider."""
    raw = os.getenv("LLM_MODELS", "").strip()
    if raw:
        custom = [m.strip() for m in raw.split(",") if m.strip()]
        if custom:
            return custom
    primary = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite").strip()
    result = [primary]
    for m in _DEFAULT_FREE_MODELS:
        if m not in result:
            result.append(m)
    return result


def _is_gemini_3x(model: str) -> bool:
    """Gemini 3.x models accept reasoning_effort='low' to cut thinking time."""
    return model.startswith("gemini-3") or model.startswith("models/gemini-3")


def _call_provider(client: OpenAI, model: str, message: str) -> Optional[str]:
    """Execute chat completion with given client and model."""
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        "temperature": 0,
        "max_tokens": 512,
    }
    # Only use Gemini-specific thinking control on Google's endpoint to avoid
    # breaking third-party OpenAI-compatible fallback providers.
    if "generativelanguage.googleapis.com" in _BASE_URL and _is_gemini_3x(model):
        kwargs["reasoning_effort"] = "low"
    response = client.chat.completions.create(**kwargs)
    if response and response.choices and len(response.choices) > 0:
        return response.choices[0].message.content or ""
    return None


def _get_fallback_client() -> Optional[OpenAI]:
    """Return configured fallback OpenAI client if configured."""
    if _FALLBACK_BASE_URL and _FALLBACK_API_KEY:
        return _create_client(_FALLBACK_BASE_URL, _FALLBACK_API_KEY)
    return None


def extract_order_items(message: str) -> list[dict]:
    """
    Call the LLM to extract order items from a customer message.
    Cascades across multiple free models on rate limits/429/quota,
    then fails over to secondary fallback provider.

    Returns a list of dicts: [{"item": str, "qty": float, "unit": str}, ...]
    Returns [] if nothing could be extracted or on exhaustion of retries.
    """
    if not message or not message.strip():
        return []

    # 1. Try Primary Provider across pool of models
    primary_client = _get_client()
    models_to_try = _get_primary_models()

    for model_name in models_to_try:
        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                raw = _call_provider(primary_client, model_name, message)
                if raw is not None:
                    parsed = _parse_llm_response(raw)
                    return parsed
            except Exception as exc:
                err_str = str(exc).lower()
                logger.warning(
                    "[llm] Model '%s' attempt %d failed: %s", model_name, attempt, exc
                )
                # If rate-limited (429), quota exceeded, or model not found (404),
                # instantly advance to next fallback model without wasting time
                if any(k in err_str for k in ("429", "quota", "rate", "404", "exhausted", "resource_exhausted")):
                    logger.info("[llm] Rate limit/quota hit on '%s', immediately trying next fallback model...", model_name)
                    break
                if attempt < _MAX_RETRIES:
                    time.sleep(0.2 * attempt)

    # 2. Try Secondary Fallback Provider (e.g. secondary API key or backup provider)
    fallback_client = _get_fallback_client()
    if fallback_client is not None:
        logger.info("[llm] Attempting secondary fallback LLM provider: %s", _FALLBACK_BASE_URL)
        fallback_models = [m.strip() for m in os.getenv("LLM_FALLBACK_MODELS", _FALLBACK_MODEL).split(",") if m.strip()]
        for fb_model in fallback_models:
            try:
                raw = _call_provider(fallback_client, fb_model, message)
                if raw is not None:
                    return _parse_llm_response(raw)
            except Exception as exc:
                logger.error("[llm] Fallback model '%s' failed: %s", fb_model, exc)

    return []


def _parse_llm_response(raw: str) -> list[dict]:
    """
    Defensively parse the LLM output.
    Strips markdown fences if present, then JSON-decodes.
    """
    if not raw or not raw.strip():
        return []

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
