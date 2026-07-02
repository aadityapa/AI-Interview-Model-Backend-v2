"""Overall score must follow evaluated technical answers, not soft-skill inflation."""

from __future__ import annotations

from ai import apply_interview_score_model


def test_poor_technical_answers_yield_low_overall_not_inflated():
    rows = [
        {"score": 1.0, "feedback": "Minimal relevance."},
        {"score": 0.0, "feedback": "No answer substance."},
        {"score": 0.0, "feedback": "No answer substance."},
    ]
    questions = ["Q1?", "Q2?", "Q3?"]
    answers = [
        "SQL option A because faster.",
        "skip",
        "I don't know",
    ]
    base = {
        "per_question": rows,
        "communication_evaluation": {"communication_score": 5.0, "summary": "Adequate tone."},
        "introduction_evaluation": {
            "communication": 50,
            "confidence": 50,
            "overall": 50,
            "summary": "Brief introduction.",
        },
    }
    out = apply_interview_score_model(base, questions, answers, session_meta={})
    overall = int(out["score_reasons"]["overall"]["score"])
    technical = int(out["score_reasons"]["technical"]["score"])
    assert technical <= 5
    assert overall <= 5
    assert overall == technical
    assert out["recommendation"] == "Reject"
