"""Authoritative expected answers for consistent per-question evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from services.question_bank.hash_utils import question_hash


def question_lookup_key(text: str) -> str:
    return question_hash(text)


def _merge_snapshot_into(out: dict[str, str], session_meta: dict | None) -> None:
    snap = (session_meta or {}).get("question_bank_snapshot")
    if not isinstance(snap, dict):
        return
    for entry in snap.values():
        if not isinstance(entry, dict):
            continue
        q = str(entry.get("question") or "").strip()
        expected = str(entry.get("expected_answer") or entry.get("expectedAnswer") or "").strip()
        if q and expected:
            out[question_lookup_key(q)] = expected


def _merge_stored_into(out: dict[str, str], session_meta: dict | None) -> None:
    stored = (session_meta or {}).get("canonical_expected_answers")
    if not isinstance(stored, dict):
        return
    for key, val in stored.items():
        expected = str(val or "").strip()
        if expected:
            out[str(key).strip()] = expected


def lookup_expected_answers_from_bank(
    db_target: str | Path | None,
    questions: Sequence[str],
) -> dict[str, str]:
    """Load hash -> expected_answer from question_bank for matching question texts."""
    if not db_target:
        return {}
    texts = [str(q or "").strip() for q in (questions or []) if str(q or "").strip()]
    if not texts:
        return {}
    hashes = sorted({question_lookup_key(t) for t in texts})
    try:
        from services.question_bank.repository import lookup_expected_answers_by_hashes

        return lookup_expected_answers_by_hashes(db_target, hashes)
    except Exception:
        return {}


def resolve_canonical_expected_answers_for_questions(
    questions: Sequence[str],
    session_meta: dict | None,
    *,
    db_target: str | Path | None = None,
) -> dict[str, str]:
    """
    Build hash -> authoritative expected answer for a question list.

    Same question text always resolves to the same reference across candidates
    when the Question Bank (or session snapshot) defines it.
    """
    out: dict[str, str] = {}
    _merge_stored_into(out, session_meta)
    _merge_snapshot_into(out, session_meta)
    bank = lookup_expected_answers_from_bank(db_target, questions)
    for key, val in bank.items():
        if val and key not in out:
            out[key] = val
    return out


def expected_answer_for_question(question: str, ref_map: dict[str, str]) -> str:
    q = str(question or "").strip()
    if not q or not ref_map:
        return ""
    return str(ref_map.get(question_lookup_key(q)) or "").strip()


def apply_canonical_expected_answers(
    rows: list[dict],
    questions: Sequence[str],
    session_meta: dict | None,
    *,
    db_target: str | Path | None = None,
) -> None:
    """Overwrite per-question expected/ideal answers with canonical references."""
    ref_map = resolve_canonical_expected_answers_for_questions(
        questions, session_meta, db_target=db_target
    )
    if not ref_map:
        return
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        q = str((questions[i] if i < len(questions) else "") or "").strip()
        expected = expected_answer_for_question(q, ref_map)
        if not expected:
            continue
        row["expected_answer"] = expected
        row["ideal_answer"] = expected
        row["reference_answer_source"] = "question_bank"
