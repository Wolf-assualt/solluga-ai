"""
core/transcription.py — Voice note speech-to-text converter.

Uses Gemini API multimodal audio input (free tier via Google AI Studio)
to transcribe voice notes in Tamil, English, and Tanglish.
Includes confidence detection and fallback verification prompt logic.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Optional
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)

_BASE_URL = os.getenv("LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai/")
_API_KEY = os.getenv("LLM_API_KEY", "")
_MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")


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


def transcribe_audio_bytes(audio_bytes: bytes, mime_type: str = "audio/ogg") -> TranscriptionResult:
    """
    Transcribe raw audio bytes using Gemini API input.
    Supports audio/ogg, audio/mpeg, audio/wav, audio/m4a, audio/mp4, etc.
    """
    if not audio_bytes:
        return TranscriptionResult(
            text="",
            is_confident=False,
            detected_language="unknown",
            clarification_prompt="Empty audio recording.",
        )

    # Clean mime type
    clean_mime = mime_type.split(";")[0].strip() or "audio/ogg"

    # Normalize audio/ogg codecs if present
    b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
    data_uri = f"data:{clean_mime};base64,{b64_audio}"

    client = OpenAI(api_key=_API_KEY, base_url=_BASE_URL)
    models_to_try = [_MODEL, "gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash"]

    for model_name in models_to_try:
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _AUDIO_TRANSCRIPTION_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": data_uri},
                            },
                        ],
                    }
                ],
                temperature=0,
                max_tokens=512,
            )
            raw_text = response.choices[0].message.content or ""
            if raw_text:
                return _parse_transcription_response(raw_text)
        except Exception as exc:
            logger.warning("[transcription] Model '%s' failed: %s; trying next model", model_name, exc)

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
