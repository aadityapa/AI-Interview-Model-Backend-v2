"""OpenAI-backed answer completion analysis for smart auto-advance."""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

FILLER_RE = re.compile(
    r"\b(um+|uh+|er+|ah+|like|you know|let me think|actually|hold on|one moment|give me a (second|moment))\b",
    re.I,
)
EXPLICIT_DONE_RE = re.compile(
    r"\b(that'?s all|i'?m done|i am done|that is my answer|finished|move on|next question)\b",
    re.I,
)


def _clamp_confidence(val: Any) -> float:
    try:
        n = float(val)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, n))


def heuristic_answer_completion(
    transcript: str,
    *,
    silence_duration_sec: float,
    is_still_speaking: bool,
    silence_threshold_sec: float,
) -> dict[str, Any]:
    text = str(transcript or "").strip()
    if is_still_speaking:
        return {"status": "ANSWER_IN_PROGRESS", "confidence": 0.85}
    if not text:
        return {"status": "ANSWER_IN_PROGRESS", "confidence": 0.6}
    if EXPLICIT_DONE_RE.search(text):
        return {"status": "ANSWER_COMPLETE", "confidence": 0.9}
    if FILLER_RE.search(text):
        trailing = text[-80:]
        if FILLER_RE.search(trailing):
            return {"status": "ANSWER_IN_PROGRESS", "confidence": 0.8}
    if text.rstrip().endswith((",", ":", "-", "…", "...")):
        return {"status": "ANSWER_IN_PROGRESS", "confidence": 0.75}
    words = [w for w in text.split() if w]
    if len(words) < 3:
        return {"status": "ANSWER_IN_PROGRESS", "confidence": 0.7}
    if silence_duration_sec >= silence_threshold_sec:
        return {"status": "ANSWER_COMPLETE", "confidence": 0.82}
    return {"status": "ANSWER_IN_PROGRESS", "confidence": 0.7}


def analyze_answer_completion(
    *,
    question_text: str,
    transcript: str,
    silence_duration_sec: float = 0.0,
    is_still_speaking: bool = False,
    silence_threshold_sec: float = 2.5,
) -> dict[str, Any]:
    """
    Determine whether the candidate has finished answering.

    Returns {"status": "ANSWER_COMPLETE"|"ANSWER_IN_PROGRESS", "confidence": float}.
    """
    text = str(transcript or "").strip()
    silence = max(0.0, float(silence_duration_sec or 0))
    threshold = max(1.0, min(10.0, float(silence_threshold_sec or 2.5)))

    try:
        from openai_client import openai_key_configured

        if not openai_key_configured("eval"):
            raise RuntimeError("OpenAI eval key not configured")
        from services.openai.chat import chat_completion_with_retry

        model = (os.getenv("OPENAI_ANSWER_COMPLETION_MODEL") or os.getenv("OPENAI_EVAL_MODEL") or "gpt-4o-mini").strip()
        system = (
            "You are an interview answer-completion detector. Reply with JSON only: "
            '{"status":"ANSWER_COMPLETE"|"ANSWER_IN_PROGRESS","confidence":0.0-1.0}. '
            "Rules:\n"
            "- ANSWER_COMPLETE: candidate explicitly signals done (that's all, I'm done, finished, move on); "
            "OR they stopped speaking with a grammatically complete thought/sentence AND "
            f"silence_duration_sec >= {threshold}.\n"
            "- ANSWER_IN_PROGRESS: is_still_speaking is true; transcript ends mid-sentence or with "
            "trailing comma/dash/ellipsis; filler words at the end (um, uh, er, like, you know, "
            "let me think, actually, hold on, one moment); very short fragment (<3 words); "
            f"or silence_duration_sec < {threshold}.\n"
            "Natural mid-answer pauses are IN_PROGRESS until silence meets the threshold with a complete thought."
        )
        user = json.dumps(
            {
                "question": str(question_text or "")[:1200],
                "transcript": text[:4000],
                "silence_duration_sec": round(silence, 2),
                "is_still_speaking": bool(is_still_speaking),
                "silence_threshold_sec": threshold,
            },
            ensure_ascii=False,
        )
        raw = chat_completion_with_retry(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            model=model,
            temperature=0.1,
            call_type="answer_completion",
            purpose="eval",
        )
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            if cleaned.endswith("```"):
                cleaned = cleaned.rsplit("```", 1)[0]
            cleaned = cleaned.strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        parsed = json.loads(cleaned)
        status = str(parsed.get("status") or "").upper()
        if status not in ("ANSWER_COMPLETE", "ANSWER_IN_PROGRESS"):
            raise ValueError(f"unexpected status: {status}")
        result = {
            "status": status,
            "confidence": _clamp_confidence(parsed.get("confidence")),
            "source": "openai",
        }
        logger.info(
            "answer_completion.decision",
            extra={
                "event": "answer_completion.decision",
                "status": result["status"],
                "confidence": result["confidence"],
                "source": "openai",
                "transcript_len": len(text),
                "silence_duration_sec": round(silence, 2),
                "is_still_speaking": bool(is_still_speaking),
            },
        )
        return result
    except Exception as exc:
        logger.info(
            "answer_completion.fallback",
            extra={
                "event": "answer_completion.fallback",
                "reason": str(exc)[:120],
                "transcript_len": len(text),
            },
        )
        result = heuristic_answer_completion(
            text,
            silence_duration_sec=silence,
            is_still_speaking=is_still_speaking,
            silence_threshold_sec=threshold,
        )
        result["source"] = "heuristic"
        logger.info(
            "answer_completion.decision",
            extra={
                "event": "answer_completion.decision",
                "status": result["status"],
                "confidence": result["confidence"],
                "source": "heuristic",
                "transcript_len": len(text),
                "silence_duration_sec": round(silence, 2),
                "is_still_speaking": bool(is_still_speaking),
            },
        )
        return result
