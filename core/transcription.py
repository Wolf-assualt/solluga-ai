"""
core/transcription.py — Voice note speech-to-text converter.

Transcribes voice notes (Tamil / English / Tanglish) using Gemini.

Telegram voice notes are OGG/Opus. Gemini's OpenAI-compatible `input_audio`
endpoint rejects that format (it only allows `wav` and `mp3`), which used to
make every voice note fail. The primary path here therefore uses Gemini's
native `generateContent` REST API with `inline_data`, which accepts
ogg/opus, mp3, wav, aac, flac and aiff directly — no transcoding, no external
binaries. The OpenAI-compatible path is kept as a fallback for wav/mp3 audio
and non-Gemini providers.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)

_BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
_API_KEY = os.getenv("LLM_API_KEY", "")
# Default to a model verified to work on this key's free tier.
_MODEL = os.getenv("LLM_MODEL", "gemini-3.1-flash-lite")
_REQUEST_TIMEOUT = float(os.getenv("LLM_TIMEOUT_SECONDS", "25.0"))
_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "1"))

# Order matters: first is the primary, second is the only fallback.
_TRANSCRIPTION_MODELS = [
    _MODEL,
    "gemini-3.1-flash-lite-preview",
]


def _derive_native_base(openai_base: str) -> str:
    """Derive the Gemini native REST base URL from an OpenAI-compatible base URL."""
    base = (openai_base or "").strip().rstrip("/")
    if base.endswith("/openai"):
        base = base[: -len("/openai")]
    return base or "https://generativelanguage.googleapis.com/v1beta"


# Native Gemini REST endpoint (accepts ogg/opus etc. via inline_data).
_NATIVE_BASE_URL = os.getenv("LLM_NATIVE_BASE_URL", "").strip().rstrip("/") or _derive_native_base(_BASE_URL)

# Mime types accepted by Gemini's native inline_data API, keyed by the cleaned
# mime type that Telegram / WhatsApp actually send.
_NATIVE_MIME = {
    "audio/ogg": "audio/ogg",
    "audio/opus": "audio/ogg",
    "audio/mpeg": "audio/mp3",
    "audio/mp3": "audio/mp3",
    "audio/wav": "audio/wav",
    "audio/x-wav": "audio/wav",
    "audio/aac": "audio/aac",
    "audio/m4a": "audio/aac",
    "audio/mp4": "audio/aac",
    "audio/aiff": "audio/aiff",
    "audio/x-aiff": "audio/aiff",
    "audio/flac": "audio/flac",
    "audio/x-flac": "audio/flac",
}

# Map Telegram / WhatsApp audio mime types to Gemini's input_audio format names.
# NOTE: the OpenAI-compatible endpoint only accepts "wav" and "mp3".
_MIME_TO_FORMAT = {
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/m4a": "m4a",
    "audio/mp4": "mp4",
    "audio/aac": "aac",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
}

# Formats the OpenAI-compatible input_audio endpoint will accept.
_COMPAT_FORMATS = {"wav", "mp3"}


@dataclass
class TranscriptionResult:
    text: str
    is_confident: bool
    detected_language: str
    clarification_prompt: Optional[str] = None


_AUDIO_TRANSCRIPTION_PROMPT = """You are a speech-to-text transcriber for grocery store customer voice messages in India.
The customer may speak in Tamil, English, or Tanglish (colloquial Tamil mixed with English).

Listen to the audio and return ONLY a JSON object with this exact structure:
{
  "transcript": "<verbatim transcription of what was said in original language/script or latin Tanglish>",
  "is_confident": true/false,
  "language": "tamil" | "english" | "tanglish",
  "clarification_needed": true/false
}

Guidelines:
- If audio is clear and grocery items or requests are recognizable, set "is_confident": true, "clarification_needed": false.
- If audio is muffled, noisy, incomplete, or item quantities are ambiguous, set "is_confident": false, "clarification_needed": true.
- Do NOT output any markdown tags or text outside of the JSON.
"""


def _clean_mime(mime_type: str) -> str:
    return (mime_type or "").split(";")[0].strip().lower()


def _pick_format(mime_type: str) -> str:
    """Return a Gemini input_audio format for the given mime type."""
    return _MIME_TO_FORMAT.get(_clean_mime(mime_type), "ogg")


def _native_transcribe(audio_bytes: bytes, mime_type: str, model_name: str) -> Optional[str]:
    """
    Transcribe via Gemini's native generateContent REST API using inline_data.
    Supports ogg/opus (Telegram), mp3, wav, aac, flac and aiff without transcoding.
    """
    native_mime = _NATIVE_MIME.get(_clean_mime(mime_type), "audio/ogg")
    b64_audio = base64.b64encode(audio_bytes).decode("utf-8")

    url = f"{_NATIVE_BASE_URL}/models/{model_name}:generateContent"
    body = {
        "contents": [
            {
                "parts": [
                    {"text": _AUDIO_TRANSCRIPTION_PROMPT},
                    {"inline_data": {"mime_type": native_mime, "data": b64_audio}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 1024},
    }

    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = httpx.post(
                url,
                params={"key": _API_KEY},
                json=body,
                timeout=_REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            candidates = data.get("candidates") or []
            if not candidates:
                return None
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(
                p.get("text", "") for p in parts if isinstance(p, dict) and p.get("text")
            )
            return text or None
        except Exception as exc:  # noqa: BLE001 - retried below, re-raised on last try
            last_exc = exc
            if attempt < _MAX_RETRIES:
                time.sleep(0.2 * (attempt + 1))
                continue
            raise
    if last_exc:
        raise last_exc
    return None


def _compat_transcribe(audio_bytes: bytes, mime_type: str, model_name: str) -> Optional[str]:
    """
    Fallback: OpenAI-compatible input_audio endpoint. Only accepts wav/mp3,
    so other formats return None without making a doomed request.
    """
    fmt = _pick_format(mime_type)
    if fmt not in _COMPAT_FORMATS:
        return None

    b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
    client = OpenAI(api_key=_API_KEY, base_url=_BASE_URL, timeout=_REQUEST_TIMEOUT)

    kwargs: dict = {
        "model": model_name,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _AUDIO_TRANSCRIPTION_PROMPT},
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": b64_audio,
                            "format": fmt,
                        },
                    },
                ],
            }
        ],
        "temperature": 0,
        "max_tokens": 512,
    }
    # Cut thinking time on Gemini 3.x when talking to Google's endpoint.
    if "generativelanguage.googleapis.com" in _BASE_URL and model_name.startswith("gemini-3"):
        kwargs["reasoning_effort"] = "low"

    response = client.chat.completions.create(**kwargs)
    if response and response.choices:
        return response.choices[0].message.content or None
    return None


def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> TranscriptionResult:
    """
    Transcribe raw audio bytes (Tamil / English / Tanglish).

    Tries Gemini's native inline_data path first (accepts Telegram's ogg/opus),
    then the OpenAI-compatible input_audio path for wav/mp3, across the model pool.
    """
    if not audio_bytes:
        return TranscriptionResult(
            text="",
            is_confident=False,
            detected_language="unknown",
            clarification_prompt="Empty audio recording.",
        )

    for model_name in _TRANSCRIPTION_MODELS:
        # Primary: native Gemini inline_data (ogg/opus, mp3, wav, aac, flac, aiff).
        try:
            raw = _native_transcribe(audio_bytes, mime_type, model_name)
            if raw:
                return _parse_transcription_response(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[transcription] Native model '%s' failed: %s", model_name, exc)

        # Fallback: OpenAI-compatible input_audio (wav/mp3 only).
        try:
            raw = _compat_transcribe(audio_bytes, mime_type, model_name)
            if raw:
                return _parse_transcription_response(raw)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[transcription] Compat model '%s' failed: %s", model_name, exc)

    return TranscriptionResult(
        text="",
        is_confident=False,
        detected_language="unknown",
        clarification_prompt="Voice note processing failed. Please send your order as a text message.",
    )


def _parse_transcription_response(raw: str) -> TranscriptionResult:
    """Safely parse transcription JSON response."""
    cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        # Fallback to entire text if plain
        return TranscriptionResult(
            text=cleaned,
            is_confident=bool(cleaned),
            detected_language="unknown",
        )

    try:
        data = json.loads(match.group())
        transcript = str(data.get("transcript", "")).strip()
        is_confident = bool(data.get("is_confident", True))
        lang = str(data.get("language", "unknown"))
        clarification_needed = bool(data.get("clarification_needed", False))

        prompt = None
        if clarification_needed or not is_confident:
            if lang in ("tamil", "tanglish"):
                prompt = f"🎤 Ungal voice note la: *\"{transcript}\"* nu kettuchu. Ithu sariya? Meendum sollunga!"
            else:
                prompt = f"🎤 In your voice note, I heard: *\"{transcript}\"*. Is this correct? Please clarify!"

        return TranscriptionResult(
            text=transcript,
            is_confident=is_confident and not clarification_needed,
            detected_language=lang,
            clarification_prompt=prompt,
        )
    except Exception:
        return TranscriptionResult(
            text=cleaned,
            is_confident=False,
            detected_language="unknown",
        )
