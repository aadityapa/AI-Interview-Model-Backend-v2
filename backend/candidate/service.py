from __future__ import annotations

from utils.auto_advance import auto_advance_api_payload
from utils.question_uniqueness import ensure_unique_served_question, record_question_registry, remember_asked_question
from utils.time_warnings import time_warnings_api_payload
from utils.warmup import (
    QUESTION_TYPE_INTRODUCTION,
    WARMUP_LABEL,
    WARMUP_NOTE,
    is_warmup_index,
    question_type_for_index,
)

def _evaluated_total(session: dict) -> int:
    """Total questions excluding the (optional) warmup, for UI progress display.

    Count-mode interviews use template ``meta.num_q`` so progress shows 10/10
    even when a legacy session prefetched a larger time-mode pool.
    """
    meta = session.get("meta", {}) or {}
    timing = str(meta.get("timing_mode") or "count").strip().lower() or "count"
    if timing == "count":
        try:
            nq = int(meta.get("num_q") or 0)
        except (TypeError, ValueError):
            nq = 0
        if nq > 0:
            return nq
    warm = meta.get("warmup_indices") or []
    return max(0, len(session.get("questions") or []) - len(warm))


def _evaluated_index(session: dict) -> int:
    """1-based index over evaluated questions (skips warmup positions)."""
    meta = session.get("meta", {}) or {}
    warm = {int(i) for i in (meta.get("warmup_indices") or []) if isinstance(i, (int, float, str)) and str(i).lstrip("-").isdigit()}
    cur = int(session.get("current") or 0)
    seen = 0
    for i in range(cur + 1):
        if i in warm:
            continue
        seen += 1
    return seen


def _count_mode_question_cap(session: dict) -> int | None:
    """Max session index (warmup + scored) for count-mode templates."""
    meta = session.get("meta", {}) or {}
    if str(meta.get("timing_mode") or "count").strip().lower() != "count":
        return None
    try:
        nq = int(meta.get("num_q") or 0)
    except (TypeError, ValueError):
        return None
    if nq <= 0:
        return None
    warm = meta.get("warmup_indices") or []
    return nq + len(warm)


def next_question_payload(session: dict) -> dict:
    meta = session.get("meta", {})
    skills = meta.get("jd_skills", []) or []
    cap = _count_mode_question_cap(session)
    cur = int(session.get("current") or 0)
    if cap is not None and cur >= cap:
        session["completed"] = True
        out = {
            "message": "Interview completed",
            "skills": skills,
            "index": _evaluated_total(session),
            "total": _evaluated_total(session),
            "show_spoken_text": bool(meta.get("show_spoken_text", False)),
            "enable_transcript_input": bool(meta.get("enable_transcript_input", meta.get("show_spoken_text", False))),
            "mic_always_on": bool(meta.get("mic_always_on", False)),
            "timing_mode": str(meta.get("timing_mode") or "count"),
            "time_limit_sec": int(meta.get("time_limit_sec") or 0),
            "time_warnings": time_warnings_api_payload(meta),
            "session_difficulty": str(meta.get("session_difficulty") or meta.get("difficulty") or "medium"),
            "auto_advance": auto_advance_api_payload(meta),
        }
        if meta.get("last_turn_score") is not None:
            out["last_turn_score"] = meta.get("last_turn_score")
            out["last_turn_feedback"] = str(meta.get("last_turn_feedback") or "")[:500]
        return out
    if session["current"] >= len(session["questions"]):
        session["completed"] = True
        out = {
            "message": "Interview completed",
            "skills": skills,
            "index": _evaluated_total(session),
            "total": _evaluated_total(session),
            "show_spoken_text": bool(meta.get("show_spoken_text", False)),
            "enable_transcript_input": bool(meta.get("enable_transcript_input", meta.get("show_spoken_text", False))),
            "mic_always_on": bool(meta.get("mic_always_on", False)),
            "timing_mode": str(meta.get("timing_mode") or "count"),
            "time_limit_sec": int(meta.get("time_limit_sec") or 0),
            "time_warnings": time_warnings_api_payload(meta),
            "session_difficulty": str(meta.get("session_difficulty") or meta.get("difficulty") or "medium"),
            "auto_advance": auto_advance_api_payload(meta),
        }
        if meta.get("last_turn_score") is not None:
            out["last_turn_score"] = meta.get("last_turn_score")
            out["last_turn_feedback"] = str(meta.get("last_turn_feedback") or "")[:500]
        return out
    ensure_unique_served_question(session)
    q = session["questions"][session["current"]]
    remember_asked_question(session, q)
    qnum = int(session["current"]) + 1
    record_question_registry(
        session,
        question_number=qnum,
        question_text=q,
        status="asked",
        source=str(meta.get("question_source") or "dynamic"),
    )
    is_warm = is_warmup_index(meta, session["current"])
    # Warmup gets a distinct payload that the candidate UI uses to render a
    # "System Warmup" chip + "This response is not evaluated." subtitle.
    out = {
        "question": q,
        # For the evaluated pool, expose a clean 1-based index/total that hides
        # the warmup from progress UI ("Question 1/5" not "Question 2/6").
        # For the warmup itself we emit index=0 + total=evaluated_total so the
        # frontend can hide/replace the progress pill cleanly.
        "index": 0 if is_warm else _evaluated_index(session),
        "total": _evaluated_total(session),
        "skills": skills,
        "show_spoken_text": bool(meta.get("show_spoken_text", False)),
        "enable_transcript_input": bool(meta.get("enable_transcript_input", meta.get("show_spoken_text", False))),
        "mic_always_on": bool(meta.get("mic_always_on", False)),
        "timing_mode": str(meta.get("timing_mode") or "count"),
        "time_limit_sec": int(meta.get("time_limit_sec") or 0),
        "time_warnings": time_warnings_api_payload(meta),
        "session_difficulty": str(meta.get("session_difficulty") or meta.get("difficulty") or "medium"),
        "auto_advance": auto_advance_api_payload(meta),
        "question_source": str(meta.get("question_source") or "dynamic"),
        "is_warmup": bool(is_warm),
        "question_type": QUESTION_TYPE_INTRODUCTION if is_warm else question_type_for_index(meta, session["current"]),
    }
    if is_warm:
        out["warmup_label"] = WARMUP_LABEL
        out["warmup_note"] = WARMUP_NOTE
    if meta.get("last_turn_score") is not None:
        out["last_turn_score"] = meta.get("last_turn_score")
        out["last_turn_feedback"] = str(meta.get("last_turn_feedback") or "")[:500]
    return out

