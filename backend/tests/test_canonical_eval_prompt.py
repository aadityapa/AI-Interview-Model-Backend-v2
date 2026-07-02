"""Evaluation must use Question Bank reference when available."""

from __future__ import annotations

from ai import evaluate_per_question_interview_batch


def test_openai_eval_receives_reference_answer(monkeypatch):
    captured = {}

    def _fake_chunk(qs, ans, idxs, model, *, role_hint="", reference_answers=None):
        captured["reference_answers"] = list(reference_answers or [])
        return [
            {
                "question_index": idxs[0] + 1,
                "score": 4.0,
                "expected_answer": "AI invented",
                "strengths": [],
                "weaknesses": [],
                "feedback": "ok",
            }
        ]

    monkeypatch.setattr("ai._evaluate_per_question_chunk_openai_indexed", _fake_chunk)
    monkeypatch.setattr("openai_client.openai_key_configured", lambda *_a, **_k: True)

    ref = "N_Bs is buffer-to-sender time waiting for Flow Control (1000 ms typical)."
    meta = {
        "canonical_expected_answers": {
            __import__("services.question_bank.hash_utils", fromlist=["question_hash"]).question_hash(
                "What is N_Bs?"
            ): ref,
        }
    }
    rows = evaluate_per_question_interview_batch(
        ["What is N_Bs?"],
        ["Some partial answer about flow control."],
        model="gpt-4o-mini",
        meta=meta,
    )
    assert captured["reference_answers"] == [ref]
    assert rows[0]["expected_answer"] == ref
