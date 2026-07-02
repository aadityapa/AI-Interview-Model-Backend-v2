"""Bootstrap must not crash when canonical_expected_answers resolution fails."""

from __future__ import annotations

import utils.canonical_expected_answers as cea


def test_resolve_canonical_expected_answers_fallback(monkeypatch):
    import main

    def _boom(*_a, **_k):
        raise RuntimeError("simulated resolver failure")

    monkeypatch.setattr(cea, "resolve_canonical_expected_answers_for_questions", _boom)
    out = main._resolve_canonical_expected_answers(["What is CAN?"], {})
    assert out == {}


def test_resolve_canonical_expected_answers_normal():
    import main

    meta = {
        "canonical_expected_answers": {
            cea.question_lookup_key("Stored Q"): "Stored answer.",
        }
    }
    out = main._resolve_canonical_expected_answers(["Stored Q"], meta)
    assert out[cea.question_lookup_key("Stored Q")] == "Stored answer."
