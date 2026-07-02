from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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


def resolve_question_bank_params(
    weights: dict | None,
    job: dict | None,
) -> dict[str, Any]:
    """Normalize role/skills/difficulty/category filters from template weights + job row."""
    cfg = parse_question_bank_config(weights)
    skills = list(cfg["skills"])
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

    return {
        "role": role,
        "skills": skills,
        "difficulties": difficulties,
        "categories": categories,
        "excluded_ids": set(cfg["excludedQuestionIds"]),
        "randomize": cfg["randomizationEnabled"],
        "avoid_duplicates": cfg["avoidDuplicateQuestions"],
        "question_count": cfg["questionCount"],
        "cfg": cfg,
    }


def _count_active_in_bank(db_target: str | Path) -> int:
    from services.question_bank.repository import _connect, _is_postgres

    pg = _is_postgres(db_target)
    active_clause = "is_active = TRUE" if pg else "is_active = 1"
    with _connect(db_target) as conn:
        if pg:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM question_bank WHERE {active_clause}")
                return int((cur.fetchone() or [0])[0])
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM question_bank WHERE {active_clause}")
        return int((cur.fetchone() or [0])[0])


def validate_question_bank_pool(
    db_target: str | Path,
    *,
    weights: dict | None,
    job: dict | None,
    required_count: int,
    avoid_question_texts: list[str] | None = None,
) -> dict[str, Any]:
    """
    Pre-start validation with per-filter pool breakdown (strict filters only).
    """
    from services.question_bank.repository import count_questions_for_interview

    params = resolve_question_bank_params(weights, job)
    cfg = params["cfg"]
    role = params["role"]
    skills = params["skills"]
    difficulties = params["difficulties"]
    categories = params["categories"]
    excluded_ids = params["excluded_ids"]

    avoid_hashes: set[str] | None = None
    if params["avoid_duplicates"] and avoid_question_texts:
        from services.question_bank.hash_utils import question_hash

        avoid_hashes = {
            question_hash(text)
            for text in avoid_question_texts
            if str(text or "").strip()
        }
        if not avoid_hashes:
            avoid_hashes = None

    total_active = _count_active_in_bank(db_target)
    strict_pool = count_questions_for_interview(
        db_target,
        role=role,
        skills=skills,
        difficulty=difficulties,
        category=categories,
        excluded_ids=excluded_ids,
    )

    role_pool = count_questions_for_interview(
        db_target,
        role=role,
        skills=[],
        difficulty="",
        category="",
        excluded_ids=excluded_ids,
    )
    role_matched = (not role) or role_pool > 0

    skill_rows: list[dict[str, Any]] = []
    for sk in skills:
        sk_pool = count_questions_for_interview(
            db_target,
            role=role,
            skills=[sk],
            difficulty=difficulties,
            category=categories,
            excluded_ids=excluded_ids,
        )
        skill_rows.append({"skill": sk, "matched": sk_pool > 0, "pool_count": sk_pool})

    diff_pool = count_questions_for_interview(
        db_target,
        role=role,
        skills=skills,
        difficulty=difficulties,
        category="",
        excluded_ids=excluded_ids,
    )
    cat_pool = count_questions_for_interview(
        db_target,
        role=role,
        skills=skills,
        difficulty=difficulties,
        category=categories,
        excluded_ids=excluded_ids,
    )

    category_rows: list[dict[str, Any]] = []
    for cat in categories:
        cat_count = count_questions_for_interview(
            db_target,
            role=role,
            skills=skills,
            difficulty=difficulties,
            category=[cat],
            excluded_ids=excluded_ids,
        )
        category_rows.append({"category": cat, "matched": cat_count > 0, "pool_count": cat_count})

    difficulty_rows: list[dict[str, Any]] = []
    for diff in difficulties:
        diff_count = count_questions_for_interview(
            db_target,
            role=role,
            skills=skills,
            difficulty=[diff],
            category=categories,
            excluded_ids=excluded_ids,
        )
        difficulty_rows.append({"difficulty": diff, "matched": diff_count > 0, "pool_count": diff_count})

    diff_label = ", ".join(difficulties) if difficulties else "any"
    cat_label = ", ".join(categories) if categories else "any"

    return {
        "role": {"filter": role, "matched": role_matched, "pool_count": role_pool},
        "skills": skill_rows,
        "categories": category_rows,
        "difficulties": difficulty_rows,
        "difficulty": {
            "filter": diff_label,
            "matched": diff_pool > 0,
            "pool_count": diff_pool,
        },
        "category": {
            "filter": cat_label,
            "matched": cat_pool > 0,
            "pool_count": cat_pool,
        },
        "total_active_in_bank": total_active,
        "matching_after_all_filters": strict_pool,
        "required_count": max(1, int(required_count or 1)),
        "selected_count": 0,
        "question_source": "question_bank",
        "avoid_hash_count": len(avoid_hashes or []),
        "excluded_id_count": len(excluded_ids),
        "avoid_duplicates": bool(cfg.get("avoidDuplicateQuestions")),
    }


def format_question_bank_validation_error(validation: dict[str, Any]) -> str:
    """Human-readable error from validation breakdown."""
    lines = ["No Question Bank questions match this template."]
    total = int(validation.get("total_active_in_bank") or 0)
    if total <= 0:
        lines.append("The Question Bank has no active questions. Upload questions in Admin → Question Bank.")
    else:
        role = validation.get("role") or {}
        if role.get("filter") and not role.get("matched"):
            lines.append(f"Role filter “{role.get('filter')}”: 0 matches ({role.get('pool_count', 0)} with relaxed role).")
        for sk in validation.get("skills") or []:
            if not sk.get("matched"):
                lines.append(f"Skill “{sk.get('skill')}”: 0 matches.")
        diff = validation.get("difficulty") or {}
        if diff.get("filter") and not diff.get("matched"):
            lines.append(f"Difficulty ({diff.get('filter')}): 0 matches.")
        cat = validation.get("category") or {}
        if cat.get("filter") and not cat.get("matched"):
            lines.append(f"Category ({cat.get('filter')}): 0 matches.")
        strict = int(validation.get("matching_after_all_filters") or 0)
        required = int(validation.get("required_count") or 0)
        if strict > 0 and strict < required:
            lines.append(
                f"Only {strict} question(s) match all filters but {required} are required. "
                "Upload more questions or reduce the question count."
            )
        elif strict <= 0:
            lines.append(
                "Upload matching questions in Admin → Question Bank, or widen role/skills/difficulty "
                "filters in the template and schedule a new invite."
            )
    return " ".join(lines)


def _preview_questions_from_weights(weights: dict | None, *, limit: int) -> list[str]:
    w = weights if isinstance(weights, dict) else {}
    raw = w.get("previewQuestions")
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        q = str(item or "").strip()
        if q:
            out.append(q)
        if len(out) >= max(1, limit):
            break
    return out


def _build_snapshot(items: list[dict], *, role: str) -> tuple[list[str], dict[str, dict]]:
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
    return questions, snapshot


def _select_bank_items_with_relaxation(
    db_target: str | Path,
    *,
    role: str,
    skills: list[str],
    difficulties: list[str],
    categories: list[str],
    count: int,
    randomize: bool,
    avoid_hashes: set[str] | None,
    excluded_ids: set[str],
    seed: str,
    allow_partial: bool = True,
    for_preview: bool = False,
) -> tuple[list[dict], str, int]:
    """
    Try progressively looser filters so invite login does not fail when HR
    template filters are slightly misaligned with bank row labels.

    Final fallback "no_exclusions" ignores HR-excluded IDs to guarantee that
    Question Bank mode never silently falls back to AI generation when the bank
    has questions but all of them happen to be in the exclusion list.

    Returns (items, relaxation_mode, pool_at_mode).
    """
    from services.question_bank.repository import count_questions_for_interview, select_questions_for_interview

    _SENTINEL = object()  # marks the no_exclusions pass

    attempts: list[tuple[str, dict]] = [
        ("strict", {"role": role, "skills": skills, "difficulty": difficulties, "category": categories, "avoid_hashes": avoid_hashes, "excl": excluded_ids}),
        ("no_avoid", {"role": role, "skills": skills, "difficulty": difficulties, "category": categories, "avoid_hashes": None, "excl": excluded_ids}),
        # Never drop skills — only relax role when template title mismatches bank row labels.
        ("relax_role", {"role": "", "skills": skills, "difficulty": difficulties, "category": categories, "avoid_hashes": None, "excl": excluded_ids}),
    ]
    # HR explicitly selected categories/difficulties — do not relax those dimensions.
    if not categories:
        attempts.append(
            ("relax_category", {"role": role, "skills": skills, "difficulty": difficulties, "category": "", "avoid_hashes": None, "excl": excluded_ids}),
        )
    if not difficulties:
        attempts.append(
            ("relax_difficulty", {"role": role, "skills": skills, "difficulty": "", "category": categories, "avoid_hashes": None, "excl": excluded_ids}),
        )
    if not for_preview:
        attempts.append(
            ("no_exclusions", {"role": "", "skills": skills, "difficulty": difficulties, "category": categories, "avoid_hashes": None, "excl": set()}),
        )
    seen_modes: set[str] = set()
    for mode, params in attempts:
        if avoid_hashes is None and mode == "no_avoid":
            continue
        effective_excl: set[str] = params.get("excl") or set()  # type: ignore[assignment]
        key = (
            f"{mode}|{params['role']}|{','.join(params['skills'])}|"
            f"{','.join(params['difficulty'] if isinstance(params['difficulty'], list) else [params['difficulty']])}|"
            f"{','.join(params['category'] if isinstance(params['category'], list) else [params['category']])}|"
            f"{bool(params['avoid_hashes'])}|excl={len(effective_excl)}"
        )
        if key in seen_modes:
            continue
        seen_modes.add(key)
        pool = count_questions_for_interview(
            db_target,
            role=str(params["role"] or ""),
            skills=list(params["skills"] or []),
            difficulty=params["difficulty"] or "",
            category=params["category"] or "",
            excluded_ids=effective_excl,
        )
        if pool <= 0:
            continue
        request_count = count if allow_partial else max(count, 1)
        items = select_questions_for_interview(
            db_target,
            role=str(params["role"] or ""),
            skills=list(params["skills"] or []),
            difficulty=params["difficulty"] or "",
            category=params["category"] or "",
            count=request_count,
            randomize=randomize,
            avoid_hashes=params["avoid_hashes"],
            excluded_ids=effective_excl,
            seed=seed,
            balance_skills=skills,
            balance_categories=categories,
            balance_difficulties=difficulties,
        )
        if items:
            if mode == "no_exclusions":
                logger.warning(
                    "question_bank.selection.no_exclusions_fallback",
                    extra={
                        "event": "question_bank.selection.no_exclusions_fallback",
                        "pool": pool,
                        "selected": len(items),
                        "role": role,
                        "skills": skills[:5],
                        "excluded_count": len(excluded_ids),
                        "reason": "All bank questions were in the HR-excluded list; serving them anyway to prevent AI fallback.",
                    },
                )
            elif mode != "strict":
                logger.info(
                    "question_bank.selection.relaxed",
                    extra={
                        "event": "question_bank.selection.relaxed",
                        "mode": mode,
                        "pool": pool,
                        "selected": len(items),
                        "role": role,
                        "skills": skills[:5],
                    },
                )
            return items, mode, pool
    return [], "none", 0


def select_question_bank_for_interview(
    db_target: str | Path,
    *,
    weights: dict | None,
    job: dict | None,
    num_q: int,
    seed: str,
    avoid_question_texts: list[str] | None = None,
    allow_partial: bool = True,
    use_preview_fallback: bool = True,
    for_preview: bool = False,
) -> dict[str, Any]:
    """
    Unified Question Bank selection for template preview and invite bootstrap.
    """
    params = resolve_question_bank_params(weights, job)
    cfg = params["cfg"]
    role = params["role"]
    skills = params["skills"]
    difficulties = params["difficulties"]
    categories = params["categories"]
    count = max(1, min(cfg["questionCount"] or num_q or 10, num_q or 10))

    avoid_hashes: set[str] | None = None
    if params["avoid_duplicates"] and avoid_question_texts:
        from services.question_bank.hash_utils import question_hash

        avoid_hashes = {
            question_hash(text)
            for text in avoid_question_texts
            if str(text or "").strip()
        }
        if not avoid_hashes:
            avoid_hashes = None

    validation = validate_question_bank_pool(
        db_target,
        weights=weights,
        job=job,
        required_count=count,
        avoid_question_texts=avoid_question_texts,
    )

    items, mode, pool_at_mode = _select_bank_items_with_relaxation(
        db_target,
        role=role,
        skills=skills,
        difficulties=difficulties,
        categories=categories,
        count=count,
        randomize=params["randomize"],
        avoid_hashes=avoid_hashes,
        excluded_ids=params["excluded_ids"],
        seed=seed,
        allow_partial=allow_partial,
        for_preview=for_preview,
    )

    template_id = str((job or {}).get("jobId") or (job or {}).get("job_id") or "").strip()
    skill_counts = [
        {"skill": row.get("skill"), "pool_count": row.get("pool_count", 0)}
        for row in (validation.get("skills") or [])
        if isinstance(row, dict)
    ]
    category_counts = [
        {"category": row.get("category"), "pool_count": row.get("pool_count", 0)}
        for row in (validation.get("categories") or [])
        if isinstance(row, dict)
    ]
    difficulty_counts = [
        {"difficulty": row.get("difficulty"), "pool_count": row.get("pool_count", 0)}
        for row in (validation.get("difficulties") or [])
        if isinstance(row, dict)
    ]
    total_strict = int(validation.get("matching_after_all_filters") or 0)

    partial_pool = False
    if items:
        selected = len(items)
        selected_skills = sorted(
            {
                str(it.get("skill") or "").strip()
                for it in items
                if str(it.get("skill") or "").strip()
            }
        )
        selected_categories = sorted(
            {
                str(it.get("category") or "").strip().lower()
                for it in items
                if str(it.get("category") or "").strip()
            }
        )
        selected_difficulties = sorted(
            {
                str(it.get("difficulty") or "").strip().lower()
                for it in items
                if str(it.get("difficulty") or "").strip()
            }
        )
        validation["selected_count"] = selected
        logger.info(
            "question_bank.selection.result",
            extra={
                "event": "question_bank.selection.result",
                "template_id": template_id,
                "question_source": "question_bank",
                "selected_skills": skills,
                "parsed_skills": skills,
                "selected_categories": categories,
                "selected_difficulties": difficulties,
                "matching_per_skill": skill_counts,
                "matching_per_category": category_counts,
                "matching_per_difficulty": difficulty_counts,
                "total_found": total_strict,
                "total_found_at_mode": pool_at_mode,
                "pool_size_requested": count,
                "questions_selected": selected,
                "result_skills": selected_skills,
                "result_categories": selected_categories,
                "result_difficulties": selected_difficulties,
                "relaxation_mode": mode,
                "role": role,
            },
        )
        if selected < count:
            partial_pool = True
            logger.warning(
                "question_bank.partial_pool",
                extra={
                    "event": "question_bank.partial_pool",
                    "required": count,
                    "selected": selected,
                    "pool": pool_at_mode,
                    "relaxation_mode": mode,
                    "role": role,
                    "skills": skills[:5],
                },
            )
        questions, snapshot = _build_snapshot(items, role=role)
        return {
            "questions": questions,
            "snapshot": snapshot,
            "items": items,
            "validation": validation,
            "relaxation_mode": mode,
            "partial_pool": partial_pool,
            "questions_found": pool_at_mode,
            "questions_selected": selected,
        }

    if use_preview_fallback:
        preview = _preview_questions_from_weights(weights, limit=count)
        if preview:
            logger.warning(
                "question_bank.selection.preview_fallback",
                extra={
                    "event": "question_bank.selection.preview_fallback",
                    "count": len(preview),
                    "role": role,
                    "skills": skills[:5],
                },
            )
            pseudo_items = [
                {
                    "id": "",
                    "question": q,
                    "expected_answer": "",
                    "keywords": "",
                    "role": role,
                    "skill": "",
                    "difficulty": "medium",
                    "category": "technical",
                }
                for q in preview
            ]
            questions, snapshot = _build_snapshot(pseudo_items, role=role)
            validation["selected_count"] = len(questions)
            return {
                "questions": questions,
                "snapshot": snapshot,
                "items": pseudo_items,
                "validation": validation,
                "relaxation_mode": "preview_fallback",
                "partial_pool": len(questions) < count,
                "questions_found": validation.get("matching_after_all_filters", 0),
                "questions_selected": len(questions),
            }

    validation["selected_count"] = 0
    logger.warning(
        "question_bank.selection.empty",
        extra={
            "event": "question_bank.selection.empty",
            "role": role,
            "skills": skills[:8],
            "difficulties": difficulties,
            "categories": categories,
            "avoid_count": len(avoid_hashes or []),
            "excluded_count": len(params["excluded_ids"]),
            "relax_mode": mode,
            "matching_after_all_filters": validation.get("matching_after_all_filters"),
        },
    )
    return {
        "questions": [],
        "snapshot": {},
        "items": [],
        "validation": validation,
        "relaxation_mode": mode,
        "partial_pool": False,
        "questions_found": 0,
        "questions_selected": 0,
    }


def bootstrap_question_bank_session(
    db_target: str | Path,
    *,
    weights: dict | None,
    job: dict | None,
    num_q: int,
    seed: str,
    avoid_question_texts: list[str] | None = None,
) -> tuple[list[str], dict[str, dict], list[dict]]:
    """
    Select questions from bank and build session artifacts.

    Returns:
        questions: list of question text strings (for session.questions)
        snapshot: index -> bank item metadata (for meta.question_bank_snapshot)
        bank_items: raw selected rows (for interview_question persistence)
    """
    result = select_question_bank_for_interview(
        db_target,
        weights=weights,
        job=job,
        num_q=num_q,
        seed=seed,
        avoid_question_texts=avoid_question_texts,
        allow_partial=True,
        use_preview_fallback=True,
    )
    return result["questions"], result["snapshot"], result["items"]
