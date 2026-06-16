"""
Process-wide OpenAI clients keyed by purpose (SDK is thread-safe).

Env vars (each falls back to OPENAI_API_KEY when unset):
  OPENAI_API_KEY              — master / fallback (ATS, OCR, embeddings, etc.)
  OPENAI_TTS_API_KEY          — text-to-speech (/candidate/tts)
  OPENAI_QUESTION_API_KEY     — question generation & follow-ups
  OPENAI_EVAL_API_KEY         — interview evaluation & per-question scoring
  OPENAI_TRANSCRIBE_API_KEY   — voice-to-text (/candidate/transcribe)

Aliases (same purpose, either name works):
  OPENAI_API_KEY_TTS, OPENAI_API_KEY_QUESTIONS, OPENAI_API_KEY_EVALUATION,
  OPENAI_API_KEY_TRANSCRIBE
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any, Literal

from openai import OpenAI

OpenAIPurpose = Literal["default", "tts", "question", "eval", "transcribe"]

_PURPOSE_ENV: dict[OpenAIPurpose, tuple[str, ...]] = {
    "default": ("OPENAI_API_KEY",),
    "tts": ("OPENAI_TTS_API_KEY", "OPENAI_API_KEY_TTS"),
    "question": ("OPENAI_QUESTION_API_KEY", "OPENAI_API_KEY_QUESTIONS"),
    "eval": ("OPENAI_EVAL_API_KEY", "OPENAI_API_KEY_EVALUATION"),
    "transcribe": ("OPENAI_TRANSCRIBE_API_KEY", "OPENAI_API_KEY_TRANSCRIBE"),
}


def _first_env(*names: str) -> str:
    for name in names:
        value = (os.getenv(name) or "").strip()
        if value and value != "your_key_here":
            return value
    return ""


def _resolve_api_key(purpose: OpenAIPurpose) -> str:
    specific = _first_env(*_PURPOSE_ENV[purpose])
    if specific:
        return specific
    return _first_env("OPENAI_API_KEY")


def openai_key_configured(purpose: OpenAIPurpose = "default") -> bool:
    key = _resolve_api_key(purpose)
    return bool(key and key != "your_key_here")


@lru_cache(maxsize=8)
def get_openai_client(purpose: OpenAIPurpose = "default") -> OpenAI:
    api_key = _resolve_api_key(purpose)
    base_url = (os.getenv("OPENAI_BASE_URL") or "").strip()
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return OpenAI(**kwargs)
