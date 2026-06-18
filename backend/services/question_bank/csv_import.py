from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any
from uuid import uuid4

from services.question_bank.hash_utils import question_hash
from services.question_bank.repository import (
    VALID_CATEGORIES,
    VALID_DIFFICULTIES,
    create_question,
    find_question_by_hash,
    update_question,
    _connect,
    _is_postgres,
    _now_iso,
)


def _decode_csv_text(file_content: bytes) -> str:
    if file_content.startswith(b"PK\x03\x04"):
        raise ValueError(
            "This file is an Excel workbook (.xlsx), not CSV. "
            "In Excel choose File -> Save As -> CSV UTF-8 (Comma delimited) (*.csv), then upload again."
        )
    if file_content.startswith(b"\xff\xfe") or file_content.startswith(b"\xfe\xff"):
        return file_content.decode("utf-16")
    return file_content.decode("utf-8-sig", errors="replace")


def _make_csv_reader(text: str) -> csv.DictReader:
    buf = io.StringIO(text, newline="")
    sample = "\n".join(text.splitlines()[:10])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t", "|"])
        return csv.DictReader(buf, dialect=dialect)
    except Exception:
        return csv.DictReader(buf)


def _parse_bool(raw: str) -> bool | None:
    s = str(raw or "").strip().lower()
    if s in {"true", "1", "yes", "on"}:
        return True
    if s in {"false", "0", "no", "off"}:
        return False
    return None


def _normalize_row_keys(row: dict) -> dict:
    out: dict[str, str] = {}
    for k, v in row.items():
        key = str(k or "").strip()
        if not key:
            continue
        compact = key.replace(" ", "").replace("_", "")
        out[compact.lower()] = str(v or "").strip()
    return {
        "Role": out.get("role", ""),
        "Skill": out.get("skill", ""),
        "Difficulty": out.get("difficulty", "medium") or "medium",
        "Category": out.get("category", "technical") or "technical",
        "Question": out.get("question", ""),
        "ExpectedAnswer": out.get("expectedanswer", ""),
        "Keywords": out.get("keywords", ""),
        "IsActive": out.get("isactive", "TRUE") or "TRUE",
    }


def validate_csv_row(row: dict, row_num: int, *, file_hashes: set[str]) -> list[str]:
    errors: list[str] = []
    question = str(row.get("Question") or "").strip()
    expected = str(row.get("ExpectedAnswer") or "").strip()
    difficulty = str(row.get("Difficulty") or "").strip().lower()
    category = str(row.get("Category") or "").strip().lower()
    active_raw = str(row.get("IsActive") or "TRUE").strip()

    if not question:
        errors.append(f"Row {row_num}: Empty question")
    if not expected:
        errors.append(f"Row {row_num}: Missing expected answer")
    if difficulty and difficulty not in VALID_DIFFICULTIES:
        errors.append(f"Row {row_num}: Invalid difficulty value '{difficulty}'")
    if category and category not in VALID_CATEGORIES:
        errors.append(f"Row {row_num}: Invalid category value '{category}'")
    if _parse_bool(active_raw) is None:
        errors.append(f"Row {row_num}: Invalid boolean value for IsActive")

    if question:
        qhash = question_hash(question)
        if qhash in file_hashes:
            errors.append(f"Row {row_num}: Duplicate question found in file")
        else:
            file_hashes.add(qhash)
    return errors


def import_csv(
    db_target: str | Path,
    file_content: bytes,
    *,
    file_name: str = "upload.csv",
    uploaded_by: str = "",
    error_report_dir: str | Path | None = None,
) -> dict:
    upload_id = str(uuid4())
    started = _now_iso()
    try:
        text = _decode_csv_text(file_content)
    except ValueError as exc:
        return {"error": str(exc), "uploadId": upload_id}

    reader = _make_csv_reader(text)
    if not reader.fieldnames:
        return {"error": "CSV has no header row", "uploadId": upload_id}

    file_hashes: set[str] = set()
    all_errors: list[str] = []
    valid_rows: list[dict] = []
    row_num = 1
    for raw_row in reader:
        row_num += 1
        norm = _normalize_row_keys(raw_row)
        row_errors = validate_csv_row(norm, row_num, file_hashes=file_hashes)
        if row_errors:
            all_errors.extend(row_errors)
            continue
        valid_rows.append(norm)

    total = row_num - 1
    success = 0
    updated = 0
    for norm in valid_rows:
        payload = {
            "role": norm["Role"],
            "skill": norm["Skill"],
            "difficulty": norm["Difficulty"].lower(),
            "category": norm["Category"].lower(),
            "question": norm["Question"],
            "expectedAnswer": norm["ExpectedAnswer"],
            "keywords": norm["Keywords"],
            "isActive": _parse_bool(norm["IsActive"]) is not False,
        }
        try:
            qhash = question_hash(norm["Question"])
            existing = find_question_by_hash(db_target, qhash)
            if existing:
                update_question(db_target, str(existing["id"]), payload, updated_by=uploaded_by)
                updated += 1
            else:
                create_question(db_target, payload, created_by=uploaded_by)
            success += 1
        except ValueError as exc:
            all_errors.append(f"Import error: {exc}")
            failed = len(all_errors)

    error_path = ""
    if all_errors and error_report_dir:
        report_dir = Path(error_report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        error_path = str(report_dir / f"import_errors_{upload_id}.txt")
        with open(error_path, "w", encoding="utf-8") as f:
            f.write("\n".join(all_errors))

    completed = _now_iso()
    status = "completed" if success > 0 else ("failed" if all_errors else "empty")
    ph = "%s" if _is_postgres(db_target) else "?"
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO question_upload_history
                    (id, file_name, total_records, success_records, failed_records,
                     uploaded_by, upload_started_at, upload_completed_at, status, error_report_path)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    """,
                    (
                        upload_id,
                        file_name,
                        total,
                        success,
                        len(all_errors),
                        uploaded_by,
                        started,
                        completed,
                        status,
                        error_path or "",
                    ),
                )
        else:
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO question_upload_history
                (id, file_name, total_records, success_records, failed_records,
                 uploaded_by, upload_started_at, upload_completed_at, status, error_report_path)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                """,
                (
                    upload_id,
                    file_name,
                    total,
                    success,
                    len(all_errors),
                    uploaded_by,
                    started,
                    completed,
                    status,
                    error_path or None,
                ),
            )
            conn.commit()

    return {
        "uploadId": upload_id,
        "fileName": file_name,
        "totalRecords": total,
        "successRecords": success,
        "updatedRecords": updated,
        "insertedRecords": success - updated,
        "failedRecords": len(all_errors),
        "status": status,
        "errors": all_errors[:200],
        "errorReportPath": error_path,
    }
