"""Tests for smart auto-advance template settings."""

from utils.auto_advance import (
    auto_advance_api_payload,
    parse_auto_advance_meta,
    record_auto_advance_turn_event,
    resolve_auto_advance_settings,
    stamp_auto_advance_settings,
)
from utils.answer_completion import analyze_answer_completion, heuristic_answer_completion


def test_resolve_defaults_on():
    cfg = resolve_auto_advance_settings()
    assert cfg["enabled"] is True
    assert cfg["initial_response_wait_sec"] == 5
    assert cfg["no_response_extra_wait_sec"] == 2.5
    assert cfg["silence_detection_sec"] == 2.5
    assert cfg["confirmation_before_next_sec"] == 2.5
    assert cfg["minimum_answer_words"] == 5
    assert cfg["minimum_speech_duration_sec"] == 2
    assert cfg["speech_energy_threshold"] == 0.038


def test_resolve_from_weights():
    cfg = resolve_auto_advance_settings(
        weights={
            "autoAdvanceEnabled": True,
            "initialResponseWaitSec": 9,
            "noResponseExtraWaitSec": 3,
            "silenceDetectionSec": 4,
            "confirmationBeforeNextSec": 2,
        }
    )
    assert cfg["enabled"] is True
    assert cfg["initial_response_wait_sec"] == 9
    assert cfg["no_response_extra_wait_sec"] == 3
    assert cfg["silence_detection_sec"] == 4
    assert cfg["confirmation_before_next_sec"] == 2


def test_stamp_and_api_payload():
    meta = {}
    stamp_auto_advance_settings(meta, {"autoAdvanceEnabled": True, "silenceDetectionSec": 2.5})
    assert meta["auto_advance_enabled"] is True
    payload = auto_advance_api_payload(meta)
    assert payload["enabled"] is True
    assert payload["silence_detection_sec"] == 2.5
    assert payload["no_response_extra_wait_sec"] == 2.5


def test_record_turn_event():
    session = {"meta": {}}
    record_auto_advance_turn_event(
        session,
        question_index=1,
        question_text="What is CAN?",
        answer_transcript="CAN is a bus protocol.",
        event={"trigger": "silence", "auto_submitted": True, "skipped": False},
    )
    events = session["meta"]["auto_advance_turn_events"]
    assert len(events) == 1
    assert events[0]["question_index"] == 2
    assert events[0]["auto_submitted"] is True


def test_parse_meta_json():
    raw = '{"trigger":"voice_command","auto_submitted":true}'
    assert parse_auto_advance_meta(raw)["trigger"] == "voice_command"


def test_answer_completion_heuristic_complete(monkeypatch):
    monkeypatch.setattr("openai_client.openai_key_configured", lambda *_a, **_k: False)
    result = analyze_answer_completion(
        question_text="Explain REST APIs.",
        transcript="REST uses HTTP verbs to perform CRUD operations on resources.",
        silence_duration_sec=3.0,
        is_still_speaking=False,
        silence_threshold_sec=2.5,
    )
    assert result["status"] == "ANSWER_COMPLETE"
    assert result["confidence"] > 0.5
    assert result.get("source") == "heuristic"


def test_answer_completion_heuristic_in_progress(monkeypatch):
    monkeypatch.setattr("openai_client.openai_key_configured", lambda *_a, **_k: False)
    result = analyze_answer_completion(
        question_text="Explain REST APIs.",
        transcript="Um, let me think",
        silence_duration_sec=0.5,
        is_still_speaking=True,
        silence_threshold_sec=2.5,
    )
    assert result["status"] == "ANSWER_IN_PROGRESS"
    assert result.get("source") == "heuristic"


def test_heuristic_explicit_done():
    result = heuristic_answer_completion(
        "That's all, thanks.",
        silence_duration_sec=1.0,
        is_still_speaking=False,
        silence_threshold_sec=2.5,
    )
    assert result["status"] == "ANSWER_COMPLETE"


def test_heuristic_filler_trailing():
    result = heuristic_answer_completion(
        "I worked on embedded systems and um",
        silence_duration_sec=3.0,
        is_still_speaking=False,
        silence_threshold_sec=2.5,
    )
    assert result["status"] == "ANSWER_IN_PROGRESS"


def test_heuristic_silence_complete():
    result = heuristic_answer_completion(
        "REST uses HTTP verbs for CRUD on resources.",
        silence_duration_sec=3.0,
        is_still_speaking=False,
        silence_threshold_sec=2.5,
    )
    assert result["status"] == "ANSWER_COMPLETE"


def test_silence_detection_clamped_to_range():
    cfg = resolve_auto_advance_settings(weights={"silenceDetectionSec": 10})
    assert cfg["silence_detection_sec"] == 5.0
    cfg2 = resolve_auto_advance_settings(weights={"silenceDetectionSec": 1})
    assert cfg2["silence_detection_sec"] == 2.5
