from __future__ import annotations

from pathlib import Path

import pytest

from auth_db import get_job_template, init_auth_db, upsert_job_template


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    db_file = tmp_path / "template_qt_test.db"
    init_auth_db(db_file)
    return db_file


def test_upsert_job_template_preserves_question_bank(db_path: Path):
    job_id = "job-qb-1"
    upsert_job_template(
        db_path,
        {
            "jobId": job_id,
            "jobTitle": "Python Developer",
            "requiredSkills": "Python, SQL",
            "questionType": "question_bank",
            "weights": {
                "questionBankConfig": {
                    "role": "Python Developer",
                    "skills": ["Python", "SQL"],
                    "categories": ["technical"],
                    "difficulties": ["easy"],
                },
                "previewQuestions": ["What is a primary key?"],
            },
        },
    )
    loaded = get_job_template(db_path, job_id)
    assert loaded is not None
    assert loaded["questionType"] == "question_bank"
    assert loaded["weights"]["questionBankConfig"]["role"] == "Python Developer"


def test_coerce_question_type_rejects_unknown():
    from auth_db import _coerce_question_type

    assert _coerce_question_type("question_bank") == "question_bank"
    assert _coerce_question_type("QUESTION_BANK") == "question_bank"
    assert _coerce_question_type("bogus") == "dynamic"
