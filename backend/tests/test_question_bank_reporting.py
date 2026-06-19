"""Question Bank expected answers on interview reports."""
from ai import _apply_question_bank_expected_answers, merge_per_question_eval_into_report


def test_apply_question_bank_expected_answers(monkeypatch):
    rows = [{"question_index": 1, "score": 7.0, "expected_answer": "", "ideal_answer": ""}]
    meta = {
        "question_bank_snapshot": {
            "0": {
                "question": "What is Python?",
                "expected_answer": "A high-level programming language.",
            }
        }
    }
    _apply_question_bank_expected_answers(rows, ["What is Python?"], meta)
    assert rows[0]["expected_answer"] == "A high-level programming language."
    assert rows[0]["ideal_answer"] == "A high-level programming language."


def test_merge_report_includes_bank_expected_answers(monkeypatch):
    monkeypatch.setattr(
        "ai.evaluate_per_question_interview_batch",
        lambda *a, **k: [{"question_index": 1, "score": 8.0, "expected_answer": "ai guess"}],
    )
    meta = {
        "question_bank_snapshot": {
            "0": {"question": "Q1", "expected_answer": "Bank reference answer."},
        }
    }
    out = merge_per_question_eval_into_report({}, ["Q1"], ["A1"], "gpt-4o-mini", session_meta=meta)
    row = out["per_question"][0]
    assert row["expected_answer"] == "Bank reference answer."
    assert row["ideal_answer"] == "Bank reference answer."
