from __future__ import annotations

from pathlib import Path
from typing import Any


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str) and value.strip():
        return [s.strip() for s in value.split(",") if s.strip()]
    return []


def parse_question_bank_config(weights: dict | None) -> dict:
    """Extract question bank configuration from template weights."""
    w = weights if isinstance(weights, dict) else {}
    cfg = w.get("questionBankConfig") or w.get("question_bank_config") or {}
    if not isinstance(cfg, dict):
        cfg = {}
    skills = cfg.get("skills") or cfg.get("Skills") or []
    if isinstance(skills, str):
        skills = [s.strip() for s in skills.split(",") if s.strip()]
    elif not isinstance(skills, list):
        skills = []

    difficulties = _as_string_list(cfg.get("difficulties") or cfg.get("Difficulties"))
    if not difficulties:
        single_diff = str(cfg.get("difficulty") or cfg.get("Difficulty") or "").strip().lower()
        if single_diff:
            difficulties = [single_diff]

    categories = _as_string_list(cfg.get("categories") or cfg.get("Categories"))
    if not categories:
        single_cat = str(cfg.get("category") or cfg.get("Category") or "").strip().lower()
        if single_cat:
            categories = [single_cat]

    excluded = cfg.get("excludedQuestionIds") or cfg.get("excluded_question_ids") or []
    if isinstance(excluded, str):
        excluded = [s.strip() for s in excluded.split(",") if s.strip()]
    elif not isinstance(excluded, list):
        excluded = []

    return {
        "role": str(cfg.get("role") or cfg.get("Role") or "").strip(),
        "skills": [str(s).strip() for s in skills if str(s).strip()],
        "difficulties": [d.lower() for d in difficulties if d.lower() in {"easy", "medium", "hard"}],
        "categories": [
            c.lower()
            for c in categories
            if c.lower() in {"technical", "behavioral", "situational", "general"}
        ],
        "difficulty": difficulties[0] if difficulties else "",
        "category": categories[0] if categories else "",
        "questionCount": int(cfg.get("questionCount") or cfg.get("question_count") or cfg.get("QuestionCount") or 10),
        "randomizationEnabled": bool(
            cfg.get("randomizationEnabled", cfg.get("randomization_enabled", cfg.get("Randomization", True)))
        ),
        "avoidDuplicateQuestions": bool(
            cfg.get("avoidDuplicateQuestions", cfg.get("avoid_duplicate_questions", True))
        ),
        "excludedQuestionIds": [str(x).strip() for x in excluded if str(x).strip()],
    }


def bootstrap_question_bank_session(
    db_target: str | Path,
    *,
    weights: dict | None,
    job: dict | None,
    num_q: int,
    seed: str,
) -> tuple[list[str], dict[str, dict], list[dict]]:
    """
    Select questions from bank and build session artifacts.

    Returns:
        questions: list of question text strings (for session.questions)
        snapshot: index -> bank item metadata (for meta.question_bank_snapshot)
        bank_items: raw selected rows (for interview_question persistence)
    """
    from services.question_bank.repository import select_questions_for_interview

    cfg = parse_question_bank_config(weights)
    skills = cfg["skills"]
    if not skills and job:
        rs = (job or {}).get("requiredSkills") or (job or {}).get("required_skills") or []
        if isinstance(rs, list):
            skills = [str(s).strip() for s in rs if str(s).strip()]
        elif isinstance(rs, str):
            skills = [s.strip() for s in rs.split(",") if s.strip()]
    role = cfg["role"] or str((job or {}).get("jobTitle") or (job or {}).get("job_title") or "").strip()
    if not role and weights:
        role = str(weights.get("intelligenceTargetRole") or "").strip()

    difficulties = list(cfg["difficulties"])
    if not difficulties:
        fallback = cfg["difficulty"] or str((job or {}).get("difficulty") or "medium").strip().lower()
        if fallback:
            difficulties = [fallback]

    categories = list(cfg["categories"])
    if not categories:
        categories = [cfg["category"] or "technical"]

    count = max(1, min(cfg["questionCount"] or num_q or 10, num_q or 10))
    avoid_hashes: set[str] | None = None
    if cfg["avoidDuplicateQuestions"]:
        from services.question_bank.hash_utils import question_hash

        avoid_hashes = set()
        preview = weights.get("previewQuestions") if isinstance(weights, dict) else None
        if isinstance(preview, list):
            for q in preview:
                text = str(q or "").strip()
                if text:
                    avoid_hashes.add(question_hash(text))

    items = select_questions_for_interview(
        db_target,
        role=role,
        skills=skills,
        difficulty=difficulties or "",
        category=categories or "",
        count=count,
        randomize=cfg["randomizationEnabled"],
        avoid_hashes=avoid_hashes,
        excluded_ids=set(cfg["excludedQuestionIds"]),
        seed=seed,
    )
    if not items:
        return [], {}, []
    questions = [str(it.get("question") or "").strip() for it in items if str(it.get("question") or "").strip()]
    snapshot: dict[str, dict] = {}
    for i, it in enumerate(items):
        snapshot[str(i)] = {
            "question_id": it.get("id"),
            "question": it.get("question") or "",
            "expected_answer": it.get("expected_answer") or "",
            "keywords": it.get("keywords") or "",
            "role": it.get("role") or role,
            "skill": it.get("skill") or "",
            "difficulty": it.get("difficulty") or "medium",
            "category": it.get("category") or "technical",
            "question_source": "QUESTION_BANK",
        }
    return questions, snapshot, items
