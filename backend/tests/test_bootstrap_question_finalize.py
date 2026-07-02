"""Regression: manual / Question Bank bootstrap must not shuffle or dedupe away bank text."""

from __future__ import annotations

from main import _finalize_bootstrap_question_list


def test_locked_source_preserves_question_order_and_text():
    bank = [
        "What is the difference between is and ==?",
        "What are sets in Python?",
        "What is a primary key?",
    ]
    out = _finalize_bootstrap_question_list(
        bank,
        locked_source=True,
        question_seed="seed-a",
        pool_q=3,
    )
    assert out == bank


def test_dynamic_source_can_shuffle_but_keeps_unique_items():
    dynamic = ["Question A about Python?", "Question B about SQL?", "Question C about APIs?"]
    out = _finalize_bootstrap_question_list(
        dynamic,
        locked_source=False,
        question_seed="fixed-seed",
        pool_q=3,
    )
    assert sorted(out) == sorted(dynamic)
    out2 = _finalize_bootstrap_question_list(
        dynamic,
        locked_source=False,
        question_seed="fixed-seed",
        pool_q=3,
    )
    assert out == out2
