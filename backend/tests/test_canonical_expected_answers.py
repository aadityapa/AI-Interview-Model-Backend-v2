"""Canonical expected answer resolution for consistent scoring."""

from __future__ import annotations

from utils.canonical_expected_answers import (
    apply_canonical_expected_answers,
    expected_answer_for_question,
    question_lookup_key,
    resolve_canonical_expected_answers_for_questions,
)


def test_question_lookup_key_stable():
    a = question_lookup_key("What is N_Bs?")
    b = question_lookup_key("  what   is   n_bs? ")
    assert a == b


def test_resolve_merges_snapshot_and_stored():
    meta = {
        "canonical_expected_answers": {
            question_lookup_key("Q stored"): "Stored answer.",
        },
        "question_bank_snapshot": {
            "0": {"question": "What is CAN?", "expected_answer": "Controller Area Network."},
        },
    }
    out = resolve_canonical_expected_answers_for_questions(["What is CAN?", "Other"], meta)
    assert out[question_lookup_key("What is CAN?")] == "Controller Area Network."
    assert out[question_lookup_key("Q stored")] == "Stored answer."


def test_apply_overwrites_ai_expected_answer():
    rows = [{"question_index": 1, "score": 2.0, "expected_answer": "wrong AI guess"}]
    meta = {
        "canonical_expected_answers": {
            question_lookup_key("What is N_Bs?"): (
                "N_Bs is the buffer-to-sender time: how long the sender waits for a "
                "Flow Control frame after transmitting a frame (typically 1000 ms in CAN TP)."
            ),
        }
    }
    apply_canonical_expected_answers(rows, ["What is N_Bs?"], meta)
    assert "buffer" in rows[0]["expected_answer"].lower() or "flow control" in rows[0]["expected_answer"].lower()
    assert rows[0]["expected_answer"] != "wrong AI guess"
    assert rows[0]["reference_answer_source"] == "question_bank"


def test_expected_answer_for_question_miss():
    assert expected_answer_for_question("Unknown?", {}) == ""
