from __future__ import annotations

from pathlib import Path

import pytest

from services.question_bank.repository import (
    create_question,
    ensure_question_bank_tables,
    list_roles_from_questions,
)


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    db_file = tmp_path / "question_bank_test.db"
    ensure_question_bank_tables(db_file)
    return db_file


def test_create_question_and_list_roles(db_path: Path):
    created = create_question(
        db_path,
        {
            "role": "Java Developer",
            "skill": "Core Java",
            "difficulty": "medium",
            "category": "technical",
            "question": "What is polymorphism in Java?",
            "expectedAnswer": "Ability of one interface to be used for a general class of actions.",
            "keywords": "OOP,polymorphism",
            "isActive": True,
        },
    )
    assert created["role"] == "Java Developer"
    assert created["skill"] == "Core Java"
    assert created["questionHash"]

    roles = list_roles_from_questions(db_path)
    assert "Java Developer" in roles
