"""Dashboard/report rows must key by interview_id, not shared walk-in email."""

from __future__ import annotations

from hr.repository import interview_record_key, list_records_for_candidate


def test_interview_record_key_uses_id_not_email():
    rec_a = {"id": "int-111", "candidate_email": "admin@karnex.in", "candidate_name": "Alice"}
    rec_b = {"id": "int-222", "candidate_email": "admin@karnex.in", "candidate_name": "Bob"}
    assert interview_record_key(rec_a) == "int-111"
    assert interview_record_key(rec_b) == "int-222"
    assert interview_record_key(rec_a) != interview_record_key(rec_b)


def test_file_fallback_groups_by_interview_id(tmp_path):
    data_file = tmp_path / "hr_records.json"
    rows = [
        {"id": "aaa", "candidate_email": "shared@walk.in", "candidate_name": "One"},
        {"id": "bbb", "candidate_email": "shared@walk.in", "candidate_name": "Two"},
    ]
    data_file.write_text(__import__("json").dumps(rows), encoding="utf-8")
    one = list_records_for_candidate(data_file, "aaa")
    two = list_records_for_candidate(data_file, "bbb")
    assert len(one) == 1 and one[0]["candidate_name"] == "One"
    assert len(two) == 1 and two[0]["candidate_name"] == "Two"


def test_email_alone_does_not_match_records(tmp_path):
    data_file = tmp_path / "hr_records.json"
    rows = [
        {"id": "aaa", "candidate_email": "shared@walk.in", "candidate_name": "One"},
        {"id": "bbb", "candidate_email": "shared@walk.in", "candidate_name": "Two"},
    ]
    data_file.write_text(__import__("json").dumps(rows), encoding="utf-8")
    legacy = list_records_for_candidate(data_file, "shared@walk.in")
    assert legacy == []
