"""Tests for Question Bank selection relaxation, validation, and partial pools."""
from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from services.question_bank.hash_utils import question_hash
from services.question_bank.repository import create_question, ensure_question_bank_tables
from services.question_bank.selection import (
    bootstrap_question_bank_session,
    format_question_bank_validation_error,
    select_question_bank_for_interview,
    validate_question_bank_pool,
)


def _make_db() -> Path:
    fd, path = tempfile.mkstemp(suffix=".db")
    import os

    os.close(fd)
    db = Path(path)
    ensure_question_bank_tables(db)
    return db


def _seed_bank(db: Path, rows: list[dict]) -> None:
    for row in rows:
        create_question(
            db,
            {
                "role": row.get("role", "Engineer"),
                "skill": row.get("skill", "Python"),
                "difficulty": row.get("difficulty", "easy"),
                "category": row.get("category", "technical"),
                "question": row["question"],
                "expectedAnswer": row.get("expectedAnswer", "answer"),
            },
        )


@pytest.fixture()
def bank_db():
    db = _make_db()
    _seed_bank(
        db,
        [
            {"role": "Engineer", "skill": "Python", "difficulty": "easy", "question": "What is a list comprehension?"},
            {"role": "Engineer", "skill": "Python", "difficulty": "easy", "question": "Explain duck typing in Python."},
            {"role": "Engineer", "skill": "SQL", "difficulty": "easy", "question": "What is a JOIN in SQL?"},
            {"role": "Engineer", "skill": "SQL", "difficulty": "medium", "question": "Explain indexing trade-offs."},
            {"role": "Engineer", "skill": "Python", "difficulty": "medium", "question": "How does GIL affect threading?"},
        ],
    )
    return db


def _weights(**overrides):
    base = {
        "questionBankConfig": {
            "role": "Engineer",
            "skills": ["Python"],
            "difficulties": ["easy"],
            "categories": ["technical"],
            "questionCount": 5,
            "randomizationEnabled": False,
            "avoidDuplicateQuestions": False,
            "excludedQuestionIds": [],
        }
    }
    if overrides:
        base["questionBankConfig"].update(overrides)
    return base


def test_validation_breakdown_structure(bank_db):
    job = {"jobTitle": "Engineer", "requiredSkills": ["Python"]}
    val = validate_question_bank_pool(
        bank_db,
        weights=_weights(),
        job=job,
        required_count=5,
    )
    assert val["question_source"] == "question_bank"
    assert "role" in val and "filter" in val["role"]
    assert isinstance(val["skills"], list)
    assert val["skills"][0]["skill"] == "Python"
    assert "difficulty" in val and "category" in val
    assert val["total_active_in_bank"] >= 5
    assert val["matching_after_all_filters"] >= 2
    assert val["required_count"] == 5
    assert val["selected_count"] == 0


def test_partial_pool_returns_available_count(bank_db):
    result = select_question_bank_for_interview(
        bank_db,
        weights=_weights(questionCount=5),
        job={"jobTitle": "Engineer", "requiredSkills": ["Python"]},
        num_q=5,
        seed="partial-test",
        allow_partial=True,
        use_preview_fallback=False,
    )
    assert len(result["questions"]) == 2
    assert result["partial_pool"] is True
    assert result["validation"]["selected_count"] == 2


def test_relaxation_finds_questions_when_skill_label_differs(bank_db):
    result = select_question_bank_for_interview(
        bank_db,
        weights=_weights(skills=["python"], difficulties=["easy"]),
        job={"jobTitle": "Engineer", "requiredSkills": ["python"]},
        num_q=2,
        seed="relax-test",
        use_preview_fallback=False,
    )
    assert len(result["questions"]) >= 2
    assert result["relaxation_mode"] in {"strict", "no_avoid", "relax_role", "relax_difficulty", "relax_role_difficulty"}


def test_avoid_history_does_not_empty_pool_when_relaxation_available(bank_db):
    q1 = "What is a list comprehension?"
    avoid = [q1]
    result = select_question_bank_for_interview(
        bank_db,
        weights=_weights(avoidDuplicateQuestions=True),
        job={"jobTitle": "Engineer", "requiredSkills": ["Python"]},
        num_q=2,
        seed="avoid-test",
        avoid_question_texts=avoid,
        use_preview_fallback=False,
    )
    assert len(result["questions"]) >= 1


def test_format_validation_error_includes_filters():
    msg = format_question_bank_validation_error(
        {
            "total_active_in_bank": 0,
            "role": {"filter": "QA", "matched": False, "pool_count": 0},
            "skills": [{"skill": "Python", "matched": False, "pool_count": 0}],
            "difficulty": {"filter": "easy", "matched": False, "pool_count": 0},
            "category": {"filter": "technical", "matched": False, "pool_count": 0},
            "matching_after_all_filters": 0,
            "required_count": 5,
        }
    )
    assert "No Question Bank questions match" in msg
    assert "Question Bank has no active questions" in msg


def test_dynamic_bootstrap_path_unchanged():
    """Ensure dynamic/manual code paths are not altered by QB helpers."""
    from main import _coerce_question_type

    assert _coerce_question_type("dynamic") == "dynamic"
    assert _coerce_question_type("manual") == "manual"
    assert _coerce_question_type("question_bank") == "question_bank"


def test_bootstrap_question_bank_session_backward_compatible_tuple(bank_db):
    qs, snap, items = bootstrap_question_bank_session(
        bank_db,
        weights=_weights(questionCount=2),
        job={"jobTitle": "Engineer", "requiredSkills": ["Python"]},
        num_q=2,
        seed="tuple-test",
    )
    assert len(qs) == 2
    assert isinstance(snap, dict)
    assert len(items) == 2


def test_balanced_selection_across_skill_category_difficulty(tmp_path):
    """Preview/interview should spread picks across skill, category, and difficulty buckets."""
    db = tmp_path / "qb.sqlite"
    ensure_question_bank_tables(db)
    rows = [
        {"role": "Python", "skill": "Python", "difficulty": "easy", "category": "technical", "question": "Py easy tech"},
        {"role": "Python", "skill": "Python", "difficulty": "easy", "category": "technical", "question": "Py easy tech 2"},
        {"role": "Python", "skill": "Python", "difficulty": "medium", "category": "technical", "question": "Py medium tech"},
        {"role": "SQL", "skill": "SQL", "difficulty": "easy", "category": "technical", "question": "SQL easy tech"},
        {"role": "SQL", "skill": "SQL", "difficulty": "medium", "category": "technical", "question": "SQL medium tech"},
        {"role": "Python", "skill": "Python", "difficulty": "easy", "category": "behavioral", "question": "Py easy behavioral"},
        {"role": "SQL", "skill": "SQL", "difficulty": "easy", "category": "situational", "question": "SQL easy situational"},
    ]
    _seed_bank(db, rows)

    skills = ["Python", "SQL"]
    weights = {
        "questionBankConfig": {
            "role": "Test_Python_Developer",
            "skills": skills,
            "difficulties": ["easy", "medium"],
            "categories": ["technical", "behavioral", "situational"],
            "questionCount": 6,
            "randomizationEnabled": False,
            "avoidDuplicateQuestions": False,
            "excludedQuestionIds": [],
        }
    }
    job = {"jobTitle": "Test_Python_Developer", "requiredSkills": skills}
    result = select_question_bank_for_interview(
        db,
        weights=weights,
        job=job,
        num_q=6,
        seed="balanced-dims",
        use_preview_fallback=False,
        for_preview=True,
    )
    assert len(result["questions"]) == 6
    cats = {str(it.get("category") or "").lower() for it in result["items"]}
    diffs = {str(it.get("difficulty") or "").lower() for it in result["items"]}
    item_skills = {str(it.get("skill") or "").lower() for it in result["items"]}
    assert "python" in item_skills and "sql" in item_skills
    assert len(diffs) >= 2, "expected both easy and medium when available"
    assert "behavioral" in cats or "situational" in cats, "expected non-technical category when available"


def test_multi_skill_cross_role_template_includes_all_skills(tmp_path):
    """Bank rows tagged Java Developer + Spring Boot must match Test_Python_Developer template."""
    db = tmp_path / "qb_multi.sqlite"
    ensure_question_bank_tables(db)
    rows = [
        {"role": "Python", "skill": "Python", "difficulty": "easy", "question": "Python Q1"},
        {"role": "Python", "skill": "Python", "difficulty": "easy", "question": "Python Q2"},
        {"role": "SQL", "skill": "SQL", "difficulty": "easy", "question": "SQL Q1"},
        {"role": "SQL", "skill": "SQL", "difficulty": "easy", "question": "SQL Q2"},
        {"role": "Java Developer", "skill": "Spring Boot", "difficulty": "medium", "question": "Spring Q1"},
        {"role": "Java Developer", "skill": "Spring Boot", "difficulty": "medium", "question": "Spring Q2"},
        {"role": "Java Developer", "skill": "Core Java", "difficulty": "medium", "question": "Core Java Q1"},
        {"role": "Java Developer", "skill": "JVM", "difficulty": "medium", "question": "JVM Q1"},
        {"role": "Java Developer", "skill": "Multithreading", "difficulty": "hard", "question": "Thread Q1"},
        {"role": "Java Developer", "skill": "Collections", "difficulty": "easy", "question": "Collections Q1"},
    ]
    _seed_bank(db, rows)

    skills = ["Python", "SQL", "Spring Boot", "Core Java", "JVM", "Multithreading", "Collections"]
    weights = {
        "questionBankConfig": {
            "role": "Test_Python_Developer",
            "skills": skills,
            "difficulties": ["easy", "medium", "hard"],
            "categories": ["technical"],
            "questionCount": 10,
            "randomizationEnabled": False,
            "avoidDuplicateQuestions": False,
            "excludedQuestionIds": [],
        }
    }
    job = {"jobTitle": "Test_Python_Developer", "requiredSkills": skills}

    val = validate_question_bank_pool(db, weights=weights, job=job, required_count=10)
    assert val["matching_after_all_filters"] == 10
    for sk in ["Spring Boot", "Core Java", "JVM", "Multithreading", "Collections"]:
        row = next(r for r in val["skills"] if r["skill"] == sk)
        assert row["pool_count"] >= 1, f"{sk} should match strict filters"

    result = select_question_bank_for_interview(
        db,
        weights=weights,
        job=job,
        num_q=10,
        seed="multi-skill",
        use_preview_fallback=False,
    )
    assert len(result["questions"]) == 10
    selected_skills = {str(it.get("skill") or "").strip().lower() for it in result["items"]}
    for expected in ["spring boot", "core java", "jvm", "multithreading", "collections", "python", "sql"]:
        assert any(expected in sk or sk in expected for sk in selected_skills), f"missing skill coverage: {expected}"
