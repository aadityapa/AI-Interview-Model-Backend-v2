"""Question Bank selection and avoid-history regression tests."""
from __future__ import annotations

import pytest

from services.question_bank.selection import bootstrap_question_bank_session, parse_question_bank_config
from utils.question_uniqueness import build_question_avoid_history


def test_parse_question_bank_config_multi_filters():
    cfg = parse_question_bank_config(
        {
            "questionBankConfig": {
                "role": "Python Developer",
                "skills": ["Python", "SQL"],
                "difficulties": ["easy", "medium"],
                "categories": ["technical", "behavioral"],
                "excludedQuestionIds": ["abc-123"],
                "questionCount": 5,
            }
        }
    )
    assert cfg["role"] == "Python Developer"
    assert cfg["skills"] == ["Python", "SQL"]
    assert cfg["difficulties"] == ["easy", "medium"]
    assert cfg["categories"] == ["technical", "behavioral"]
    assert cfg["excludedQuestionIds"] == ["abc-123"]
    assert cfg["questionCount"] == 5


def test_build_question_avoid_history_skips_preview_when_empty():
    hist = build_question_avoid_history(
        global_recent=["recent q"],
        job_recent=[],
        manual_questions=[],
        template_preview=[],
        session_asked=[],
    )
    assert hist == ["recent q"]


def test_question_bank_avoid_excludes_preview_not_prior_interviews(monkeypatch):
    """Preview lines must not be treated as already-asked when selecting from the bank."""
    import main

    preview = ["Bank question A", "Bank question B"]
    job = {
        "jobId": "job-1",
        "questionType": "question_bank",
        "manualQuestions": [],
        "weights": {"previewQuestions": preview, "questionBankConfig": {"role": "Dev", "skills": ["X"]}},
    }

    monkeypatch.setattr(main, "recently_asked_questions", lambda _n=120: [])
    monkeypatch.setattr(main, "recent_questions_for_job_template", lambda *a, **k: [])
    monkeypatch.setattr(main, "sessions", {})

    with_preview = main._build_question_avoid_history(job, job["weights"], include_template_preview=True)
    without_preview = main._build_question_avoid_history(job, job["weights"], include_template_preview=False)

    assert preview[0] in with_preview
    assert preview[0] not in without_preview


def test_bootstrap_question_bank_session_respects_avoid_hashes(tmp_path, monkeypatch):
    """Selection with avoid hashes should still return items when pool is larger than avoid set."""
    from services.question_bank import repository as repo

    db = tmp_path / "qb.sqlite"
    repo.ensure_question_bank_tables(db)

    rows = [
        {
            "role": "Python",
            "skill": "Python",
            "difficulty": "easy",
            "category": "technical",
            "question": "What is a list?",
            "expectedAnswer": "Ordered mutable sequence.",
            "keywords": "python",
            "isActive": True,
        },
        {
            "role": "Python",
            "skill": "Python",
            "difficulty": "easy",
            "category": "technical",
            "question": "What is a tuple?",
            "expectedAnswer": "Ordered immutable sequence.",
            "keywords": "python",
            "isActive": True,
        },
    ]
    for row in rows:
        repo.create_question(db, row, created_by="test")

    weights = {
        "questionBankConfig": {
            "role": "Python",
            "skills": ["Python"],
            "difficulties": ["easy"],
            "categories": ["technical"],
            "questionCount": 2,
            "randomizationEnabled": False,
            "avoidDuplicateQuestions": True,
        }
    }
    qs, snap, items = bootstrap_question_bank_session(
        db,
        weights=weights,
        job={"jobTitle": "Python Developer", "requiredSkills": ["Python"]},
        num_q=2,
        seed="unit-test",
        avoid_question_texts=["What is a list?"],
    )
    assert len(qs) == 1
    assert qs[0] == "What is a tuple?"
    assert snap["0"]["expected_answer"]
