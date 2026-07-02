"""Semantic duplicate detection for dynamic interview questions."""

from utils.question_uniqueness import (
    DEFAULT_SIMILARITY_THRESHOLD,
    consecutive_concept_too_similar,
    dedupe_question_list_semantic,
    ensure_unique_served_question,
    question_similarity_score,
    question_too_similar,
    record_question_registry,
)


def test_default_similarity_threshold_is_70_percent():
    assert DEFAULT_SIMILARITY_THRESHOLD == 0.7


def test_consecutive_concept_blocks_back_to_back_repeat():
    prior = ["Explain ViewModel in Android."]
    repeat = "What is ViewModel?"
    assert consecutive_concept_too_similar(repeat, prior)
    assert question_too_similar(repeat, prior)


def test_viewmodel_paraphrases_are_duplicates():
    a = "Explain ViewModel in Android."
    b = "What is ViewModel?"
    c = "Explain LiveData in Android."
    assert question_too_similar(b, [a])
    assert not question_too_similar(c, [a])


def test_similarity_score_high_for_same_topic():
    score = question_similarity_score("Explain ViewModel in Android.", "Why do we use ViewModel?")
    assert score >= 0.8


def test_dedupe_question_list_semantic():
    qs = [
        "Explain ViewModel in Android.",
        "Explain LiveData.",
        "What is ViewModel?",
        "Explain Room Database.",
    ]
    out = dedupe_question_list_semantic(qs)
    assert len(out) == 3
    assert "What is ViewModel?" not in out


def test_record_question_registry_and_ensure_unique():
    session = {
        "current": 1,
        "questions": [
            "Explain ViewModel in Android.",
            "What is ViewModel?",
            "Explain Room Database.",
        ],
        "answers": ["skip"],
        "meta": {
            "interview_id": "int-1",
            "question_source": "dynamic",
            "asked_questions": ["Explain ViewModel in Android."],
            "jd_text": "Kotlin Android developer",
            "jd_skills": ["kotlin", "room", "coroutines", "navigation"],
            "session_difficulty": "medium",
        },
    }
    record_question_registry(session, question_number=1, question_text=session["questions"][0], status="asked")
    assert session["meta"]["question_registry"][0]["status"] == "asked"
    replaced = ensure_unique_served_question(session)
    assert replaced is True
    assert not question_too_similar(session["questions"][1], session["meta"]["asked_questions"])


def test_manual_questions_not_replaced_by_dedupe():
    session = {
        "current": 1,
        "questions": ["Manual Q1", "Manual Q1 paraphrase?", "Manual Q3"],
        "answers": ["answered"],
        "meta": {
            "interview_id": "int-manual",
            "question_source": "manual",
            "generation_mode": "manual",
            "asked_questions": ["Manual Q1"],
            "jd_text": "Role",
            "jd_skills": ["skill"],
            "session_difficulty": "medium",
        },
    }
    replaced = ensure_unique_served_question(session)
    assert replaced is False
    assert session["questions"][1] == "Manual Q1 paraphrase?"


def test_question_bank_not_replaced_by_dedupe():
    session = {
        "current": 1,
        "questions": [
            "Please introduce yourself.",
            "What is the difference between is and ==?",
            "What are sets in Python?",
        ],
        "answers": ["skip"],
        "meta": {
            "interview_id": "int-qb",
            "question_source": "QUESTION_BANK",
            "generation_mode": "question_bank",
            "asked_questions": ["Please introduce yourself."],
            "warmup_indices": [0],
            "jd_text": "Python developer",
            "jd_skills": ["python"],
            "session_difficulty": "medium",
        },
    }
    replaced = ensure_unique_served_question(session)
    assert replaced is False
    assert session["questions"][1] == "What is the difference between is and ==?"
