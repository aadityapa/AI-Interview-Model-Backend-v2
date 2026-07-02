"""Regression: filtered Q/A lists must not inherit session warmup index 0."""

from __future__ import annotations

from ai import merge_per_question_eval_into_report
from utils.warmup import (
    WARMUP_QUESTION_TEXT,
    meta_for_filtered_qa_evaluation,
)


def test_meta_for_filtered_qa_clears_stale_warmup_index():
    meta = {"warmup_indices": [0], "question_types": {"0": "INTRODUCTION"}}
    aligned = meta_for_filtered_qa_evaluation(meta, ["When does the sender start transmitting CFs?"])
    assert aligned is not None
    assert "warmup_indices" not in aligned
    assert "question_types" not in aligned


def test_merge_eval_scores_first_technical_after_warmup_stripped(monkeypatch):
    def _fake_batch(questions, answers, model="gpt-4o-mini", *, meta=None):
        assert meta is not None
        assert "warmup_indices" not in meta
        return [
            {
                "question_index": 1,
                "score": 7.5,
                "strengths": ["Good"],
                "weaknesses": [],
                "feedback": "Solid technical answer.",
            }
        ]

    monkeypatch.setattr("ai.evaluate_per_question_interview_batch", _fake_batch)
    qs = ["When does the sender start transmitting Consecutive Frames (CFs)?"]
    ans = ["After the First Frame is acknowledged."]
    out = merge_per_question_eval_into_report(
        {"overall_score": 9.0, "skill_scores": []},
        qs,
        ans,
        model="gpt-4o-mini",
        session_meta={"warmup_indices": [0]},
    )
    row = (out.get("per_question") or [])[0]
    assert float(row.get("score") or 0.0) == 7.5
    assert row.get("excluded_from_score") is not True
    assert out["technical_score"] == 7.5


def test_meta_keeps_warmup_when_question_still_present():
    meta = {"warmup_indices": [0]}
    qs = [WARMUP_QUESTION_TEXT, "What is CAN?"]
    aligned = meta_for_filtered_qa_evaluation(meta, qs)
    assert aligned is meta or aligned.get("warmup_indices") == [0]
