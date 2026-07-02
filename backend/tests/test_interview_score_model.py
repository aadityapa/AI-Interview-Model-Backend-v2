"""Weighted interview score model (Jun 2026)."""

from __future__ import annotations

from ai import apply_interview_score_model, evaluate_introduction_answer
from utils.warmup import WARMUP_QUESTION_TEXT


def test_apply_interview_score_model_weighted_overall():
    report = {
        "communication_evaluation": {
            "communication_score": 7,
            "presentation_score": 6,
            "summary": "Clear explanations with minor filler words.",
        },
        "introduction_evaluation": {
            "communication": 80,
            "confidence": 75,
            "summary": "Professional self-introduction.",
        },
        "per_question": [
            {"question_index": 1, "score": 8.0},
            {"question_index": 2, "score": 6.0},
        ],
    }
    qs = ["What is CAN?", "How would you troubleshoot a bus-off scenario?"]
    ans = ["Controller area network.", "Check termination, error counters, and power."]
    out = apply_interview_score_model(report, qs, ans, session_meta={"warmup_indices": []})
    reasons = out.get("score_reasons") or {}
    assert reasons["technical"]["score"] == 70
    assert reasons["communication"]["score"] >= 60
    # When technical answers exist, headline overall tracks technical mean (not a weighted blend).
    assert reasons["overall"]["score"] == reasons["technical"]["score"]
    assert out.get("overall_score_percent") == float(reasons["overall"]["score"])
    assert isinstance(out.get("criteria_breakdown"), dict)
    assert len(str(out.get("scoring_rationale") or "")) > 10


def test_introduction_excluded_from_technical_mean():
    report = {
        "communication_evaluation": {"communication_score": 6, "presentation_score": 6, "summary": "OK"},
        "introduction_evaluation": evaluate_introduction_answer(
            WARMUP_QUESTION_TEXT,
            "I am Alex, a firmware engineer with two years of CAN experience.",
        ),
        "per_question": [
            {"question_index": 1, "score": 0.0, "feedback": "Introduction"},
            {"question_index": 2, "score": 8.0, "feedback": "Good"},
        ],
    }
    qs = [WARMUP_QUESTION_TEXT, "What is OOP?"]
    ans = ["I am Alex.", "Object oriented programming bundles data and methods."]
    meta = {"warmup_indices": [0]}
    out = apply_interview_score_model(report, qs, ans, session_meta=meta)
    assert out["score_reasons"]["technical"]["score"] == 80
    assert out["introduction_evaluation"]["excluded_from_technical_score"] is True


def test_score_reasons_include_human_text():
    report = {
        "communication_evaluation": {"communication_score": 5, "presentation_score": 5, "summary": "Adequate clarity."},
        "per_question": [{"question_index": 1, "score": 5.0}],
    }
    out = apply_interview_score_model(report, ["What is REST?"], ["Representational state transfer."], session_meta={})
    for key in ("communication", "technical", "confidence", "problem_solving", "overall"):
        assert isinstance(out["score_reasons"][key]["reason"], str)
        assert out["score_reasons"][key]["reason"].strip()
