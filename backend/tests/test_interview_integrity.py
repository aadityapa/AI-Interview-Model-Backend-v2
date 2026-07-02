"""Integrity violation types, counting, and 3-strike termination policy."""

from __future__ import annotations

from main import MAX_WARNINGS, _count_integrity_violations


def _event(vtype: str, **extra):
    row = {"type": vtype, "details": extra.get("details", vtype), "timestamp": "2026-07-01T10:00:00+05:30"}
    row.update({k: v for k, v in extra.items() if k not in row})
    return row


def test_count_integrity_includes_fullscreen_and_key_violations():
    events = [
        _event("tab_switch"),
        _event("fullscreen_exit"),
        _event("key_escape"),
        _event("alt_tab"),
        _event("windows_key"),
        _event("ctrl_esc"),
        _event("window_blur"),
        _event("visibility_hidden"),
        _event("focus_lost"),
    ]
    assert _count_integrity_violations(events) == len(events)


def test_count_integrity_ignores_termination_events():
    events = [
        _event("tab_switch"),
        _event("fullscreen_exit"),
        {"type": "termination", "details": "done"},
    ]
    assert _count_integrity_violations(events) == 2


def test_three_strike_policy_threshold():
    """Warnings on strikes 1-2; terminate when count reaches MAX_WARNINGS (3)."""
    events = [_event("tab_switch") for _ in range(MAX_WARNINGS - 1)]
    assert _count_integrity_violations(events) == MAX_WARNINGS - 1

    events.append(_event("fullscreen_exit"))
    assert _count_integrity_violations(events) == MAX_WARNINGS
    # Endpoint terminates when violation_count >= MAX_WARNINGS
    assert _count_integrity_violations(events) >= MAX_WARNINGS


def test_violation_payload_fields_preserved_in_event_shape():
    evt = _event(
        "fullscreen_exit",
        interview_id="tok-abc",
        candidate_id="cand@example.com",
        current_question="Explain REST APIs",
        fullscreen_status="inactive",
        browser_visibility="visible",
        window_focus=False,
    )
    assert evt["interview_id"] == "tok-abc"
    assert evt["candidate_id"] == "cand@example.com"
    assert evt["current_question"] == "Explain REST APIs"
    assert evt["fullscreen_status"] == "inactive"
    assert evt["browser_visibility"] == "visible"
    assert evt["window_focus"] is False
