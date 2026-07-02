"""Tests for invite session template matching and Question Bank pool refill."""

from __future__ import annotations

from candidate.service import next_question_payload
from utils.invite_session_guard import (
    expected_question_source,
    invite_session_matches_template,
    invite_session_playable,
    invite_session_safe_to_rebuild,
)


def test_expected_question_source_question_bank():
    assert expected_question_source({"questionType": "question_bank"}) == "QUESTION_BANK"


def test_is_locked_question_source_manual_and_bank():
    from utils.invite_session_guard import is_locked_question_source

    assert is_locked_question_source({"question_source": "manual"}) is True
    assert is_locked_question_source({"question_source": "QUESTION_BANK"}) is True
    assert is_locked_question_source({"generation_mode": "question_bank"}) is True
    assert is_locked_question_source({"question_source": "dynamic"}) is False


def test_stale_dynamic_session_rejected_for_question_bank_template():
    job = {"jobId": "bb0f2be452", "questionType": "question_bank", "numQ": 7}
    session = {
        "current": 0,
        "questions": ["Please introduce yourself.", "AI generated question?"],
        "answers": [],
        "meta": {
            "job_id": "bb0f2be452",
            "question_source": "dynamic",
            "generation_mode": "ai",
            "timing_mode": "count",
            "num_q": 7,
            "warmup_indices": [0],
        },
    }
    assert invite_session_matches_template(session, job, {}) is False
    assert invite_session_safe_to_rebuild(session) is True


def test_legacy_empty_question_source_rejected_for_question_bank():
    job = {"jobId": "bb0f2be452", "questionType": "question_bank", "numQ": 7}
    session = {
        "current": 0,
        "questions": ["Please introduce yourself.", "AI tradeoff question?"],
        "answers": [],
        "meta": {
            "job_id": "bb0f2be452",
            "question_source": "",
            "generation_mode": "ai",
            "timing_mode": "count",
            "num_q": 7,
            "warmup_indices": [0],
        },
    }
    assert invite_session_matches_template(session, job, {}) is False


def test_question_bank_session_matches_when_snapshot_present():
    job = {"jobId": "bb0f2be452", "questionType": "question_bank", "numQ": 7}
    session = {
        "current": 0,
        "questions": ["Please introduce yourself.", "QB Q1", "QB Q2"],
        "answers": [],
        "meta": {
            "job_id": "bb0f2be452",
            "question_source": "QUESTION_BANK",
            "question_bank_snapshot": {"0": {"question": "QB Q1"}},
            "timing_mode": "count",
            "num_q": 2,
            "warmup_indices": [0],
        },
    }
    assert invite_session_matches_template(session, job, {}) is True
    assert invite_session_playable(session) is True


def test_unplayable_session_at_end_of_empty_pool():
    session = {
        "current": 2,
        "questions": ["warmup", "Q1"],
        "answers": [],
        "completed": False,
        "meta": {
            "timing_mode": "count",
            "num_q": 1,
            "warmup_indices": [0],
            "question_source": "manual",
        },
    }
    assert invite_session_playable(session) is False
    assert invite_session_safe_to_rebuild(session) is True


def test_next_question_does_not_complete_when_pool_underfilled(monkeypatch):
    """Skip on last loaded question must not end interview when template cap is higher."""
    session = {
        "current": 2,
        "questions": ["warmup", "Q1"],
        "answers": ["skip", "skip"],
        "completed": False,
        "meta": {
            "jd_skills": ["python"],
            "timing_mode": "count",
            "num_q": 5,
            "warmup_indices": [0],
            "question_source": "QUESTION_BANK",
            "job_id": "bb0f2be452",
            "question_bank_snapshot": {"0": {"question": "Q1"}},
            "question_seed": "seed-1",
        },
    }

    def _fake_refill(sess, _db):
        sess["questions"] = ["warmup", "Q1", "Q2", "Q3", "Q4", "Q5"]
        return True

    monkeypatch.setattr("candidate.service.refill_question_bank_pool_if_needed", _fake_refill)
    out = next_question_payload(session, db_target="test-db")
    assert out.get("question") == "Q2"
    assert session.get("completed") is not True
