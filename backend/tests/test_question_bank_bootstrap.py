from __future__ import annotations

from pathlib import Path

import pytest

from auth_db import get_job_template, init_auth_db, upsert_job_template
from services.question_bank.repository import create_question, ensure_question_bank_tables
from services.question_bank.selection import bootstrap_question_bank_session


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    db_file = tmp_path / "qb_bootstrap.db"
    init_auth_db(db_file)
    ensure_question_bank_tables(db_file)
    for i, q in enumerate(
        [
            "What is the difference between is and ==?",
            "What are sets in Python?",
            "What is a primary key?",
            "How do you write a SELECT with JOIN?",
            "Explain list comprehension.",
            "What is a foreign key?",
        ],
        start=1,
    ):
        create_question(
            db_file,
            {
                "role": "Python",
                "skill": "Python" if i <= 3 else "SQL",
                "difficulty": "easy",
                "category": "technical",
                "question": q,
                "expectedAnswer": "sample",
                "keywords": "python,sql",
                "isActive": True,
                "approvalStatus": "approved",
            },
        )
    upsert_job_template(
        db_file,
        {
            "jobId": "qb-job",
            "jobTitle": "Python Developer",
            "requiredSkills": "Python, SQL",
            "questionType": "question_bank",
            "weights": {
                "previewQuestions": [
                    "What is the difference between is and ==?",
                    "What are sets in Python?",
                    "What is a primary key?",
                ],
                "questionBankConfig": {
                    "role": "Python Developer",
                    "skills": ["Python", "SQL"],
                    "categories": ["technical"],
                    "difficulties": ["easy"],
                    "questionCount": 3,
                    "randomizationEnabled": True,
                    "avoidDuplicateQuestions": True,
                },
            },
        },
    )
    return db_file


def test_bootstrap_ignores_preview_sample_when_selecting(db_path: Path):
    job = get_job_template(db_path, "qb-job")
    weights = job.get("weights") or {}
    questions, _snapshot, items = bootstrap_question_bank_session(
        db_path,
        weights=weights,
        job=job,
        num_q=3,
        seed="candidate-a",
    )
    assert len(questions) == 3
    assert len(items) == 3
    assert all("?" in q for q in questions)
