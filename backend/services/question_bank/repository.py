from __future__ import annotations

import csv
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from functools import lru_cache

from services.question_bank.hash_utils import question_hash

VALID_DIFFICULTIES = frozenset({"easy", "medium", "hard"})
VALID_CATEGORIES = frozenset({"technical", "behavioral", "situational", "general"})
VALID_APPROVAL_STATUSES = frozenset({"approved", "pending", "rejected"})


def qb_require_approval() -> bool:
    return str(os.getenv("QB_REQUIRE_APPROVAL") or "false").strip().lower() in {"1", "true", "yes", "on"}


def _append_approved_only_filter(clauses: list[str], *, for_interview: bool) -> None:
    if for_interview and qb_require_approval():
        clauses.append("approval_status = 'approved'")

CSV_COLUMNS = (
    "Role",
    "Skill",
    "Difficulty",
    "Category",
    "Question",
    "ExpectedAnswer",
    "Keywords",
    "IsActive",
)

QUESTION_BANK_COLUMNS = (
    "id",
    "role",
    "skill",
    "difficulty",
    "category",
    "question",
    "expected_answer",
    "keywords",
    "is_active",
    "question_hash",
    "version",
    "approval_status",
    "created_at",
    "updated_at",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_postgres(db_target: str | Path) -> bool:
    s = str(db_target)
    return s.startswith("postgresql://") or s.startswith("postgres://")


def _connect(db_target: str | Path):
    from auth_db import _connect_postgres, _connect_sqlite, _is_postgres as is_pg

    if is_pg(db_target):
        return _connect_postgres(str(db_target))
    import sqlite3

    conn = sqlite3.connect(str(db_target))
    conn.row_factory = sqlite3.Row
    return conn


@lru_cache(maxsize=8)
def _question_bank_column_names(db_target: str) -> frozenset[str]:
    pg = db_target.startswith("postgresql://") or db_target.startswith("postgres://")
    with _connect(db_target) as conn:
        if pg:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'question_bank'
                    """
                )
                return frozenset(str(r[0]) for r in (cur.fetchall() or []))
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(question_bank)")
        return frozenset(str(r[1]) for r in (cur.fetchall() or []))


def _sync_legacy_question_fields(
    db_target: str | Path,
    row: dict,
    *,
    qtext: str,
    actor: str = "",
    version: int | None = None,
) -> dict:
    """Populate legacy NOT NULL columns (e.g. question_text, created_by) when present."""
    cols = _question_bank_column_names(str(db_target))
    out = dict(row)
    if "question_text" in cols:
        out["question_text"] = qtext
    if "created_by" in cols and "created_by" not in out:
        out["created_by"] = actor or ""
    if "updated_by" in cols:
        out["updated_by"] = actor or out.get("updated_by") or ""
    ver = version if version is not None else int(out.get("version") or out.get("version_number") or 1)
    if "version_number" in cols:
        out["version_number"] = ver
    return out


def _row_to_dict(row: Any, columns: tuple[str, ...] | None = None) -> dict:
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    if isinstance(row, (tuple, list)):
        cols = columns or QUESTION_BANK_COLUMNS
        if len(row) != len(cols):
            raise ValueError(f"Row has {len(row)} values but expected {len(cols)} columns")
        return dict(zip(cols, row))
    return dict(row)


def _question_api(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "role": row.get("role") or "",
        "skill": row.get("skill") or "",
        "difficulty": row.get("difficulty") or "medium",
        "category": row.get("category") or "technical",
        "question": row.get("question") or row.get("question_text") or "",
        "expectedAnswer": row.get("expected_answer") or "",
        "keywords": row.get("keywords") or "",
        "isActive": bool(row.get("is_active") if row.get("is_active") is not None else True),
        "questionHash": row.get("question_hash") or "",
        "version": int(row.get("version") or 1),
        "approvalStatus": row.get("approval_status") or "approved",
        "createdAt": row.get("created_at") or "",
        "updatedAt": row.get("updated_at") or "",
    }


def _question_bank_create_sqlite() -> str:
    return """
        CREATE TABLE IF NOT EXISTS question_bank (
            id TEXT PRIMARY KEY,
            role TEXT NOT NULL DEFAULT '',
            skill TEXT NOT NULL DEFAULT '',
            difficulty TEXT NOT NULL DEFAULT 'medium',
            category TEXT NOT NULL DEFAULT 'technical',
            question TEXT NOT NULL,
            expected_answer TEXT NOT NULL DEFAULT '',
            keywords TEXT NOT NULL DEFAULT '',
            is_active INTEGER NOT NULL DEFAULT 1,
            question_hash TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            approval_status TEXT NOT NULL DEFAULT 'approved',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
    """


def _question_bank_create_postgres() -> str:
    return """
        CREATE TABLE IF NOT EXISTS question_bank (
            id TEXT PRIMARY KEY,
            role TEXT NOT NULL DEFAULT '',
            skill TEXT NOT NULL DEFAULT '',
            difficulty TEXT NOT NULL DEFAULT 'medium',
            category TEXT NOT NULL DEFAULT 'technical',
            question TEXT NOT NULL,
            expected_answer TEXT NOT NULL DEFAULT '',
            keywords TEXT NOT NULL DEFAULT '',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            question_hash TEXT NOT NULL DEFAULT '',
            version INTEGER NOT NULL DEFAULT 1,
            approval_status TEXT NOT NULL DEFAULT 'approved',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
    """


def ensure_question_bank_tables(db_target: str | Path) -> None:
    pg = _is_postgres(db_target)
    with _connect(db_target) as conn:
        if pg:
            with conn.cursor() as cur:
                cur.execute(_question_bank_create_postgres())
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS question_upload_history (
                        id TEXT PRIMARY KEY,
                        file_name TEXT NOT NULL DEFAULT '',
                        total_records INTEGER NOT NULL DEFAULT 0,
                        success_records INTEGER NOT NULL DEFAULT 0,
                        failed_records INTEGER NOT NULL DEFAULT 0,
                        uploaded_by TEXT NOT NULL DEFAULT '',
                        upload_started_at TEXT NOT NULL DEFAULT '',
                        upload_completed_at TEXT NOT NULL DEFAULT '',
                        status TEXT NOT NULL DEFAULT 'pending',
                        error_report_path TEXT
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS interview_question (
                        id TEXT PRIMARY KEY,
                        interview_id TEXT NOT NULL,
                        question_id TEXT,
                        question_text TEXT NOT NULL,
                        expected_answer TEXT NOT NULL DEFAULT '',
                        skill TEXT NOT NULL DEFAULT '',
                        difficulty TEXT NOT NULL DEFAULT 'medium',
                        question_order INTEGER NOT NULL DEFAULT 0,
                        question_source TEXT NOT NULL DEFAULT 'QUESTION_BANK',
                        asked_at TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS candidate_answer (
                        id TEXT PRIMARY KEY,
                        interview_id TEXT NOT NULL,
                        candidate_id TEXT NOT NULL DEFAULT '',
                        question_id TEXT,
                        question_text_snapshot TEXT NOT NULL DEFAULT '',
                        expected_answer_snapshot TEXT NOT NULL DEFAULT '',
                        candidate_answer TEXT NOT NULL DEFAULT '',
                        answer_duration REAL NOT NULL DEFAULT 0,
                        question_source TEXT NOT NULL DEFAULT 'QUESTION_BANK',
                        question_order INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS evaluation_result (
                        id TEXT PRIMARY KEY,
                        candidate_answer_id TEXT NOT NULL,
                        technical_score REAL NOT NULL DEFAULT 0,
                        communication_score REAL NOT NULL DEFAULT 0,
                        confidence_score REAL NOT NULL DEFAULT 0,
                        problem_solving_score REAL NOT NULL DEFAULT 0,
                        completeness_score REAL NOT NULL DEFAULT 0,
                        overall_score REAL NOT NULL DEFAULT 0,
                        strengths TEXT NOT NULL DEFAULT '[]',
                        weaknesses TEXT NOT NULL DEFAULT '[]',
                        improvement_areas TEXT NOT NULL DEFAULT '[]',
                        ideal_answer TEXT NOT NULL DEFAULT '',
                        ai_feedback TEXT NOT NULL DEFAULT '',
                        evaluated_at TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
        else:
            cur = conn.cursor()
            cur.execute(_question_bank_create_sqlite())
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS question_upload_history (
                    id TEXT PRIMARY KEY,
                    file_name TEXT NOT NULL DEFAULT '',
                    total_records INTEGER NOT NULL DEFAULT 0,
                    success_records INTEGER NOT NULL DEFAULT 0,
                    failed_records INTEGER NOT NULL DEFAULT 0,
                    uploaded_by TEXT NOT NULL DEFAULT '',
                    upload_started_at TEXT NOT NULL DEFAULT '',
                    upload_completed_at TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    error_report_path TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS interview_question (
                    id TEXT PRIMARY KEY,
                    interview_id TEXT NOT NULL,
                    question_id TEXT,
                    question_text TEXT NOT NULL,
                    expected_answer TEXT NOT NULL DEFAULT '',
                    skill TEXT NOT NULL DEFAULT '',
                    difficulty TEXT NOT NULL DEFAULT 'medium',
                    question_order INTEGER NOT NULL DEFAULT 0,
                    question_source TEXT NOT NULL DEFAULT 'QUESTION_BANK',
                    asked_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS candidate_answer (
                    id TEXT PRIMARY KEY,
                    interview_id TEXT NOT NULL,
                    candidate_id TEXT NOT NULL DEFAULT '',
                    question_id TEXT,
                    question_text_snapshot TEXT NOT NULL DEFAULT '',
                    expected_answer_snapshot TEXT NOT NULL DEFAULT '',
                    candidate_answer TEXT NOT NULL DEFAULT '',
                    answer_duration REAL NOT NULL DEFAULT 0,
                    question_source TEXT NOT NULL DEFAULT 'QUESTION_BANK',
                    question_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS evaluation_result (
                    id TEXT PRIMARY KEY,
                    candidate_answer_id TEXT NOT NULL,
                    technical_score REAL NOT NULL DEFAULT 0,
                    communication_score REAL NOT NULL DEFAULT 0,
                    confidence_score REAL NOT NULL DEFAULT 0,
                    problem_solving_score REAL NOT NULL DEFAULT 0,
                    completeness_score REAL NOT NULL DEFAULT 0,
                    overall_score REAL NOT NULL DEFAULT 0,
                    strengths TEXT NOT NULL DEFAULT '[]',
                    weaknesses TEXT NOT NULL DEFAULT '[]',
                    improvement_areas TEXT NOT NULL DEFAULT '[]',
                    ideal_answer TEXT NOT NULL DEFAULT '',
                    ai_feedback TEXT NOT NULL DEFAULT '',
                    evaluated_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.commit()
    _patch_question_bank_schema(db_target)
    _ensure_question_bank_versions_table(db_target)
    with _connect(db_target) as conn:
        index_sql = (
            "CREATE INDEX IF NOT EXISTS idx_qb_role ON question_bank (role)",
            "CREATE INDEX IF NOT EXISTS idx_qb_skill ON question_bank (skill)",
            "CREATE INDEX IF NOT EXISTS idx_qb_difficulty ON question_bank (difficulty)",
            "CREATE INDEX IF NOT EXISTS idx_qb_category ON question_bank (category)",
            "CREATE INDEX IF NOT EXISTS idx_qb_is_active ON question_bank (is_active)",
            "CREATE INDEX IF NOT EXISTS idx_qb_approval_status ON question_bank (approval_status)",
            "CREATE INDEX IF NOT EXISTS idx_qb_question_hash ON question_bank (question_hash)",
            "CREATE INDEX IF NOT EXISTS idx_iq_interview ON interview_question (interview_id)",
            "CREATE INDEX IF NOT EXISTS idx_ca_interview ON candidate_answer (interview_id)",
            "CREATE INDEX IF NOT EXISTS idx_er_candidate_answer ON evaluation_result (candidate_answer_id)",
        )
        if pg:
            with conn.cursor() as cur:
                for sql in index_sql:
                    cur.execute(sql)
        else:
            cur = conn.cursor()
            for sql in index_sql:
                cur.execute(sql)
            conn.commit()


def _patch_question_bank_schema(db_target: str | Path) -> None:
    """Backward-compatible schema evolution for legacy question_bank tables."""
    pg = _is_postgres(db_target)
    desired_pg = {
        "role": "TEXT NOT NULL DEFAULT ''",
        "skill": "TEXT NOT NULL DEFAULT ''",
        "difficulty": "TEXT NOT NULL DEFAULT 'medium'",
        "category": "TEXT NOT NULL DEFAULT 'technical'",
        "question": "TEXT NOT NULL DEFAULT ''",
        "expected_answer": "TEXT NOT NULL DEFAULT ''",
        "keywords": "TEXT NOT NULL DEFAULT ''",
        "is_active": "BOOLEAN NOT NULL DEFAULT TRUE",
        "question_hash": "TEXT NOT NULL DEFAULT ''",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "approval_status": "TEXT NOT NULL DEFAULT 'approved'",
        "created_at": "TEXT NOT NULL DEFAULT ''",
        "updated_at": "TEXT NOT NULL DEFAULT ''",
    }
    desired_sqlite = {
        "role": "TEXT NOT NULL DEFAULT ''",
        "approval_status": "TEXT NOT NULL DEFAULT 'approved'",
        "question": "TEXT NOT NULL DEFAULT ''",
        "question_hash": "TEXT NOT NULL DEFAULT ''",
        "version": "INTEGER NOT NULL DEFAULT 1",
    }
    with _connect(db_target) as conn:
        if pg:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'question_bank'
                    """
                )
                existing = {str(r[0]) for r in (cur.fetchall() or [])}
                if not existing:
                    return
                for col, ddl in desired_pg.items():
                    if col not in existing:
                        cur.execute(f"ALTER TABLE question_bank ADD COLUMN {col} {ddl}")
                        existing.add(col)
                if "question_text" in existing and "question" in existing:
                    cur.execute(
                        """
                        UPDATE question_bank
                        SET question = question_text
                        WHERE (question IS NULL OR question = '')
                          AND question_text IS NOT NULL AND question_text <> ''
                        """
                    )
                if "version_number" in existing and "version" in existing:
                    cur.execute(
                        """
                        UPDATE question_bank
                        SET version = COALESCE(version_number, 1)
                        WHERE version IS NULL OR version < 1
                        """
                    )
                if "question_hash" in existing and "question" in existing:
                    cur.execute(
                        """
                        SELECT id, question FROM question_bank
                        WHERE (question_hash IS NULL OR question_hash = '')
                          AND question IS NOT NULL AND question <> ''
                        """
                    )
                    rows = cur.fetchall() or []
                    for qid, qtext in rows:
                        cur.execute(
                            "UPDATE question_bank SET question_hash = %s WHERE id = %s",
                            (question_hash(str(qtext or "")), qid),
                        )
                for idx_sql in (
                    "CREATE INDEX IF NOT EXISTS idx_qb_role ON question_bank (role)",
                    "CREATE INDEX IF NOT EXISTS idx_qb_approval_status ON question_bank (approval_status)",
                    "CREATE INDEX IF NOT EXISTS idx_qb_question_hash ON question_bank (question_hash)",
                ):
                    cur.execute(idx_sql)
        else:
            cur = conn.cursor()
            cur.execute("PRAGMA table_info(question_bank)")
            existing = {str(r[1]) for r in (cur.fetchall() or [])}
            if not existing:
                return
            for col, ddl in desired_sqlite.items():
                if col not in existing:
                    cur.execute(f"ALTER TABLE question_bank ADD COLUMN {col} {ddl}")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_qb_role ON question_bank (role)")
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_qb_approval_status ON question_bank (approval_status)"
            )
            conn.commit()


def _ensure_question_bank_versions_table(db_target: str | Path) -> None:
    pg = _is_postgres(db_target)
    with _connect(db_target) as conn:
        if pg:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS question_bank_versions (
                        id TEXT PRIMARY KEY,
                        question_id TEXT NOT NULL,
                        version INTEGER NOT NULL DEFAULT 1,
                        question TEXT NOT NULL DEFAULT '',
                        expected_answer TEXT NOT NULL DEFAULT '',
                        approval_status TEXT NOT NULL DEFAULT 'approved',
                        changed_by TEXT NOT NULL DEFAULT '',
                        change_note TEXT NOT NULL DEFAULT '',
                        changed_at TEXT NOT NULL DEFAULT ''
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_qbv_question ON question_bank_versions (question_id, version DESC)"
                )
        else:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS question_bank_versions (
                    id TEXT PRIMARY KEY,
                    question_id TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1,
                    question TEXT NOT NULL DEFAULT '',
                    expected_answer TEXT NOT NULL DEFAULT '',
                    approval_status TEXT NOT NULL DEFAULT 'approved',
                    changed_by TEXT NOT NULL DEFAULT '',
                    change_note TEXT NOT NULL DEFAULT '',
                    changed_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.commit()


def _select_columns() -> str:
    return (
        "id, role, skill, difficulty, category, question, expected_answer, keywords, "
        "is_active, question_hash, version, approval_status, created_at, updated_at"
    )


def _question_column_expr(db_target: str | Path) -> str:
    """Legacy tables may use question_text instead of question."""
    cols = _question_bank_column_names(str(db_target))
    if "question" in cols and "question_text" in cols:
        return "COALESCE(NULLIF(question, ''), question_text)"
    if "question" in cols:
        return "question"
    if "question_text" in cols:
        return "question_text"
    return "question"


def get_dashboard_stats(db_target: str | Path) -> dict:
    pg = _is_postgres(db_target)
    with _connect(db_target) as conn:
        if pg:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM question_bank")
                total = int((cur.fetchone() or [0])[0])
                cur.execute("SELECT COUNT(*) FROM question_bank WHERE is_active = TRUE")
                active = int((cur.fetchone() or [0])[0])
                cur.execute("SELECT COUNT(DISTINCT role) FROM question_bank WHERE role <> ''")
                roles = int((cur.fetchone() or [0])[0])
                cur.execute("SELECT COUNT(DISTINCT skill) FROM question_bank WHERE skill <> ''")
                skills = int((cur.fetchone() or [0])[0])
                cur.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT question_hash FROM question_bank
                        WHERE question_hash <> ''
                        GROUP BY question_hash HAVING COUNT(*) > 1
                    ) dup
                    """
                )
                duplicates = int((cur.fetchone() or [0])[0])
                cur.execute(
                    """
                    SELECT id, file_name, total_records, success_records, failed_records,
                           uploaded_by, upload_started_at, status
                    FROM question_upload_history
                    ORDER BY upload_started_at DESC LIMIT 5
                    """
                )
                recent = [
                    {
                        "id": r[0],
                        "fileName": r[1],
                        "totalRecords": r[2],
                        "successRecords": r[3],
                        "failedRecords": r[4],
                        "uploadedBy": r[5],
                        "uploadStartedAt": r[6],
                        "status": r[7],
                    }
                    for r in (cur.fetchall() or [])
                ]
                cur.execute(
                    "SELECT COUNT(*) FROM question_upload_history WHERE status = 'failed' OR failed_records > 0"
                )
                failed_imports = int((cur.fetchone() or [0])[0])
        else:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM question_bank")
            total = int((cur.fetchone() or [0])[0])
            cur.execute("SELECT COUNT(*) FROM question_bank WHERE is_active = 1")
            active = int((cur.fetchone() or [0])[0])
            cur.execute("SELECT COUNT(DISTINCT role) FROM question_bank WHERE role <> ''")
            roles = int((cur.fetchone() or [0])[0])
            cur.execute("SELECT COUNT(DISTINCT skill) FROM question_bank WHERE skill <> ''")
            skills = int((cur.fetchone() or [0])[0])
            cur.execute(
                """
                SELECT COUNT(*) FROM (
                    SELECT question_hash FROM question_bank
                    WHERE question_hash <> ''
                    GROUP BY question_hash HAVING COUNT(*) > 1
                )
                """
            )
            duplicates = int((cur.fetchone() or [0])[0])
            cur.execute(
                """
                SELECT id, file_name, total_records, success_records, failed_records,
                       uploaded_by, upload_started_at, status
                FROM question_upload_history
                ORDER BY upload_started_at DESC LIMIT 5
                """
            )
            recent = [
                {
                    "id": r[0],
                    "fileName": r[1],
                    "totalRecords": r[2],
                    "successRecords": r[3],
                    "failedRecords": r[4],
                    "uploadedBy": r[5],
                    "uploadStartedAt": r[6],
                    "status": r[7],
                }
                for r in (cur.fetchall() or [])
            ]
            cur.execute(
                "SELECT COUNT(*) FROM question_upload_history WHERE status = 'failed' OR failed_records > 0"
            )
            failed_imports = int((cur.fetchone() or [0])[0])
    return {
        "totalQuestions": total,
        "activeQuestions": active,
        "inactiveQuestions": max(0, total - active),
        "rolesCount": roles,
        "skillsCount": skills,
        "duplicateQuestions": duplicates,
        "failedImports": failed_imports,
        "recentUploads": recent,
    }


def _build_list_filters(
    db_target: str | Path,
    *,
    role: str = "",
    skill: str = "",
    difficulty: str = "",
    category: str = "",
    search: str = "",
    is_active: bool | None = None,
    approval_status: str = "",
) -> tuple[list[str], list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    ph = "%s" if _is_postgres(db_target) else "?"
    if role:
        clauses.append(f"LOWER(role) = LOWER({ph})")
        params.append(role.strip())
    if skill:
        clauses.append(f"LOWER(skill) = LOWER({ph})")
        params.append(skill.strip())
    if difficulty:
        clauses.append(f"LOWER(difficulty) = LOWER({ph})")
        params.append(difficulty.strip())
    if category:
        clauses.append(f"LOWER(category) = LOWER({ph})")
        params.append(category.strip())
    if search:
        clauses.append(
            f"(LOWER(question) LIKE LOWER({ph}) OR LOWER(keywords) LIKE LOWER({ph}) OR LOWER(skill) LIKE LOWER({ph}))"
        )
        needle = f"%{search.strip()}%"
        params.extend([needle, needle, needle])
    if is_active is not None:
        clauses.append(f"is_active = {ph}")
        params.append(is_active if _is_postgres(db_target) else (1 if is_active else 0))
    if approval_status:
        clauses.append(f"LOWER(approval_status) = LOWER({ph})")
        params.append(approval_status.strip())
    return clauses, params


def list_questions(
    db_target: str | Path,
    *,
    page: int = 1,
    page_size: int = 25,
    role: str = "",
    skill: str = "",
    difficulty: str = "",
    category: str = "",
    search: str = "",
    is_active: bool | None = None,
    approval_status: str = "",
) -> dict:
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    offset = (page - 1) * page_size
    clauses, params = _build_list_filters(
        db_target,
        role=role,
        skill=skill,
        difficulty=difficulty,
        category=category,
        search=search,
        is_active=is_active,
        approval_status=approval_status,
    )
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    ph = "%s" if _is_postgres(db_target) else "?"
    cols = _select_columns()
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM question_bank{where}", tuple(params))
                total = int((cur.fetchone() or [0])[0])
                cur.execute(
                    f"""
                    SELECT {cols}
                    FROM question_bank{where}
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    tuple(params + [page_size, offset]),
                )
                rows = [_question_api(_row_to_dict(r)) for r in (cur.fetchall() or [])]
        else:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM question_bank{where}", tuple(params))
            total = int((cur.fetchone() or [0])[0])
            cur.execute(
                f"""
                SELECT {cols}
                FROM question_bank{where}
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                tuple(params + [page_size, offset]),
            )
            rows = []
            for r in cur.fetchall() or []:
                d = dict(r)
                d["is_active"] = bool(d.get("is_active"))
                rows.append(_question_api(d))
    return {"items": rows, "total": total, "page": page, "pageSize": page_size}


def get_question(db_target: str | Path, question_id: str) -> dict | None:
    ph = "%s" if _is_postgres(db_target) else "?"
    cols = _select_columns()
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(f"SELECT {cols} FROM question_bank WHERE id = {ph}", (question_id,))
                row = cur.fetchone()
        else:
            cur = conn.cursor()
            cur.execute(f"SELECT {cols} FROM question_bank WHERE id = {ph}", (question_id,))
            row = cur.fetchone()
    if not row:
        return None
    d = _row_to_dict(row) if _is_postgres(db_target) else dict(row)
    if not _is_postgres(db_target):
        d["is_active"] = bool(d.get("is_active"))
    return _question_api(d)


def hash_exists(db_target: str | Path, qhash: str, exclude_id: str = "") -> bool:
    ph = "%s" if _is_postgres(db_target) else "?"
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                if exclude_id:
                    cur.execute(
                        f"SELECT 1 FROM question_bank WHERE question_hash = {ph} AND id <> {ph} LIMIT 1",
                        (qhash, exclude_id),
                    )
                else:
                    cur.execute(f"SELECT 1 FROM question_bank WHERE question_hash = {ph} LIMIT 1", (qhash,))
                return cur.fetchone() is not None
        else:
            cur = conn.cursor()
            if exclude_id:
                cur.execute(
                    f"SELECT 1 FROM question_bank WHERE question_hash = {ph} AND id <> {ph} LIMIT 1",
                    (qhash, exclude_id),
                )
            else:
                cur.execute(f"SELECT 1 FROM question_bank WHERE question_hash = {ph} LIMIT 1", (qhash,))
            return cur.fetchone() is not None


def find_question_by_hash(db_target: str | Path, qhash: str) -> dict | None:
    ph = "%s" if _is_postgres(db_target) else "?"
    cols = _select_columns()
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(f"SELECT {cols} FROM question_bank WHERE question_hash = {ph} LIMIT 1", (qhash,))
                row = cur.fetchone()
        else:
            cur = conn.cursor()
            cur.execute(f"SELECT {cols} FROM question_bank WHERE question_hash = {ph} LIMIT 1", (qhash,))
            row = cur.fetchone()
    if not row:
        return None
    data = _row_to_dict(row) if _is_postgres(db_target) else dict(row)
    if not _is_postgres(db_target):
        data["is_active"] = bool(data.get("is_active"))
    return _question_api(data)


def create_question(db_target: str | Path, data: dict, *, created_by: str = "") -> dict:
    actor = str(created_by or "").strip()
    qid = str(data.get("id") or uuid4())
    qtext = str(data.get("question") or "").strip()
    if not qtext:
        raise ValueError("Question text is required")
    expected = str(data.get("expectedAnswer") or data.get("expected_answer") or "").strip()
    if not expected:
        raise ValueError("Expected answer is required")
    difficulty = str(data.get("difficulty") or "medium").strip().lower()
    if difficulty not in VALID_DIFFICULTIES:
        raise ValueError("Invalid difficulty")
    category = str(data.get("category") or "technical").strip().lower()
    if category not in VALID_CATEGORIES:
        raise ValueError("Invalid category")
    approval = str(data.get("approvalStatus") or data.get("approval_status") or "").strip().lower()
    if not approval:
        approval = "pending" if qb_require_approval() else "approved"
    if approval not in VALID_APPROVAL_STATUSES:
        raise ValueError("Invalid approval status")
    qhash = question_hash(qtext)
    if hash_exists(db_target, qhash):
        raise ValueError("Duplicate question found")
    now = _now_iso()
    is_active = data.get("isActive", data.get("is_active", True))
    active_val = bool(is_active) if _is_postgres(db_target) else (1 if bool(is_active) else 0)
    row = {
        "id": qid,
        "role": str(data.get("role") or data.get("roleName") or "").strip(),
        "skill": str(data.get("skill") or data.get("skillName") or "").strip(),
        "difficulty": difficulty,
        "category": category,
        "question": qtext,
        "expected_answer": expected,
        "keywords": str(data.get("keywords") or "").strip(),
        "is_active": active_val,
        "question_hash": qhash,
        "version": 1,
        "approval_status": approval,
        "created_at": now,
        "updated_at": now,
    }
    row = _sync_legacy_question_fields(db_target, row, qtext=qtext, actor=actor, version=1)
    ph = "%s" if _is_postgres(db_target) else "?"
    cols = ", ".join(row.keys())
    placeholders = ", ".join([ph] * len(row))
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(f"INSERT INTO question_bank ({cols}) VALUES ({placeholders})", tuple(row.values()))
        else:
            cur = conn.cursor()
            cur.execute(f"INSERT INTO question_bank ({cols}) VALUES ({placeholders})", tuple(row.values()))
            conn.commit()
    return _question_api(row)


def update_question(db_target: str | Path, question_id: str, data: dict, *, updated_by: str = "") -> dict:
    actor = str(updated_by or "").strip()
    existing = get_question(db_target, question_id)
    if not existing:
        raise ValueError("Question not found")
    _save_question_version_snapshot(db_target, existing, actor=actor, note="pre_update")
    qtext = str(data.get("question") or existing["question"]).strip()
    expected = str(data.get("expectedAnswer") or data.get("expected_answer") or existing["expectedAnswer"]).strip()
    if not qtext:
        raise ValueError("Question text is required")
    if not expected:
        raise ValueError("Expected answer is required")
    difficulty = str(data.get("difficulty") or existing["difficulty"]).strip().lower()
    if difficulty not in VALID_DIFFICULTIES:
        raise ValueError("Invalid difficulty")
    category = str(data.get("category") or existing["category"]).strip().lower()
    if category not in VALID_CATEGORIES:
        raise ValueError("Invalid category")
    approval = str(
        data.get("approvalStatus") or data.get("approval_status") or existing["approvalStatus"]
    ).strip().lower()
    material_change = (
        qtext != str(existing.get("question") or "").strip()
        or expected != str(existing.get("expectedAnswer") or "").strip()
    )
    if material_change and qb_require_approval() and approval == str(existing.get("approvalStatus") or "approved").lower():
        approval = "pending"
    if approval not in VALID_APPROVAL_STATUSES:
        raise ValueError("Invalid approval status")
    qhash = question_hash(qtext)
    if hash_exists(db_target, qhash, exclude_id=question_id):
        raise ValueError("Duplicate question found")
    now = _now_iso()
    is_active = data.get("isActive", data.get("is_active", existing["isActive"]))
    active_val = bool(is_active) if _is_postgres(db_target) else (1 if bool(is_active) else 0)
    version = int(existing.get("version") or 1) + 1
    ph = "%s" if _is_postgres(db_target) else "?"
    fields = {
        "role": str(data.get("role") or data.get("roleName") or existing["role"]).strip(),
        "skill": str(data.get("skill") or data.get("skillName") or existing["skill"]).strip(),
        "difficulty": difficulty,
        "category": category,
        "question": qtext,
        "expected_answer": expected,
        "keywords": str(data.get("keywords") or existing["keywords"]).strip(),
        "is_active": active_val,
        "question_hash": qhash,
        "version": version,
        "approval_status": approval,
        "updated_at": now,
    }
    fields = _sync_legacy_question_fields(db_target, fields, qtext=qtext, actor=actor, version=version)
    set_clause = ", ".join(f"{col} = {ph}" for col in fields)
    values = tuple(fields.values()) + (question_id,)
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE question_bank SET {set_clause} WHERE id = {ph}",
                    values,
                )
        else:
            cur = conn.cursor()
            cur.execute(
                f"UPDATE question_bank SET {set_clause} WHERE id = {ph}",
                values,
            )
            conn.commit()
    return get_question(db_target, question_id) or {}


def delete_question(db_target: str | Path, question_id: str) -> bool:
    ph = "%s" if _is_postgres(db_target) else "?"
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(f"DELETE FROM question_bank WHERE id = {ph}", (question_id,))
                return cur.rowcount > 0
        else:
            cur = conn.cursor()
            cur.execute(f"DELETE FROM question_bank WHERE id = {ph}", (question_id,))
            conn.commit()
            return cur.rowcount > 0


def set_question_active(db_target: str | Path, question_id: str, active: bool, *, updated_by: str = "") -> dict:
    return update_question(db_target, question_id, {"isActive": active}, updated_by=updated_by)


def list_roles_from_questions(db_target: str | Path) -> list[str]:
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT MIN(role) AS role
                    FROM question_bank
                    WHERE role <> ''
                    GROUP BY LOWER(role)
                    ORDER BY LOWER(MIN(role))
                    """
                )
                return [str(r[0]) for r in (cur.fetchall() or []) if r and r[0]]
        else:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT role FROM question_bank
                WHERE role <> ''
                GROUP BY LOWER(role)
                ORDER BY LOWER(role)
                """
            )
            return [str(r[0]) for r in (cur.fetchall() or [])]


def list_skills(db_target: str | Path, *, role: str = "") -> list[str]:
    clauses = ["skill <> ''"]
    params: list[Any] = []
    ph = "%s" if _is_postgres(db_target) else "?"
    if role:
        clauses.append(f"LOWER(role) = LOWER({ph})")
        params.append(role.strip())
    where = " WHERE " + " AND ".join(clauses)
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT MIN(skill) AS skill
                    FROM question_bank{where}
                    GROUP BY LOWER(skill)
                    ORDER BY LOWER(MIN(skill))
                    """,
                    tuple(params),
                )
                return [str(r[0]) for r in (cur.fetchall() or []) if r and r[0]]
        else:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT skill FROM question_bank{where}
                GROUP BY LOWER(skill)
                ORDER BY LOWER(skill)
                """,
                tuple(params),
            )
            return [str(r[0]) for r in (cur.fetchall() or [])]


def export_questions_csv(db_target: str | Path) -> str:
    """Export all question_bank rows (bypasses list_questions 100-row page cap)."""
    cols = _select_columns()
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(CSV_COLUMNS)
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {cols} FROM question_bank ORDER BY created_at DESC",
                )
                rows = cur.fetchall() or []
        else:
            cur = conn.cursor()
            cur.execute(f"SELECT {cols} FROM question_bank ORDER BY created_at DESC")
            rows = cur.fetchall() or []
    for raw in rows:
        item = _question_api(_row_to_dict(raw))
        writer.writerow(
            [
                item.get("role"),
                item.get("skill"),
                item.get("difficulty"),
                item.get("category"),
                item.get("question"),
                item.get("expectedAnswer"),
                item.get("keywords"),
                "TRUE" if item.get("isActive") else "FALSE",
            ]
        )
    return buf.getvalue()


def list_upload_history(db_target: str | Path, *, page: int = 1, page_size: int = 25) -> dict:
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    offset = (page - 1) * page_size
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM question_upload_history")
                total = int((cur.fetchone() or [0])[0])
                cur.execute(
                    """
                    SELECT id, file_name, total_records, success_records, failed_records,
                           uploaded_by, upload_started_at, upload_completed_at, status, error_report_path
                    FROM question_upload_history
                    ORDER BY upload_started_at DESC
                    LIMIT %s OFFSET %s
                    """,
                    (page_size, offset),
                )
                rows = cur.fetchall() or []
        else:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM question_upload_history")
            total = int((cur.fetchone() or [0])[0])
            cur.execute(
                """
                SELECT id, file_name, total_records, success_records, failed_records,
                       uploaded_by, upload_started_at, upload_completed_at, status, error_report_path
                FROM question_upload_history
                ORDER BY upload_started_at DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset),
            )
            rows = cur.fetchall() or []
    items = [
        {
            "id": r[0],
            "fileName": r[1],
            "totalRecords": r[2],
            "successRecords": r[3],
            "failedRecords": r[4],
            "uploadedBy": r[5],
            "uploadStartedAt": r[6],
            "uploadCompletedAt": r[7],
            "status": r[8],
            "errorReportPath": r[9],
        }
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "pageSize": page_size}


def _append_role_filter(
    clauses: list[str],
    params: list[Any],
    db_target: str | Path,
    role: str,
    skills: list[str] | None = None,
) -> None:
    """Match blank bank role, template role overlap, or bank row tagged with a requested skill.

    Bank rows often use a generic role (e.g. "Java Developer") with a specific skill column
    (e.g. "Spring Boot"). When HR lists multiple required skills, those rows must not be
    rejected because the role column differs from the template title.
    """
    r = str(role or "").strip()
    norm_skills = [s.strip() for s in (skills or []) if str(s).strip()]
    if not r and not norm_skills:
        return
    ph = "%s" if _is_postgres(db_target) else "?"
    parts: list[str] = ["COALESCE(role, '') = ''"]
    if r:
        parts.extend(
            [
                f"LOWER(role) = LOWER({ph})",
                f"LOWER({ph}) LIKE '%%' || LOWER(role) || '%%'",
                f"LOWER(role) LIKE '%%' || LOWER({ph}) || '%%'",
            ]
        )
        params.extend([r, r, r])
    for sk in norm_skills:
        # Match when role OR skill column equals the requested skill label.
        parts.append(f"LOWER(role) = LOWER({ph})")
        parts.append(f"LOWER(skill) = LOWER({ph})")
        params.extend([sk, sk])
    clauses.append("(" + " OR ".join(parts) + ")")


def _append_skills_filter(clauses: list[str], params: list[Any], db_target: str | Path, skills: list[str]) -> None:
    """Match skill column or keywords (case-insensitive, partial)."""
    norm_skills = [s.strip() for s in (skills or []) if str(s).strip()]
    if not norm_skills:
        return
    ph = "%s" if _is_postgres(db_target) else "?"
    groups: list[str] = []
    for sk in norm_skills:
        groups.append(
            f"""(
                LOWER(skill) = LOWER({ph})
                OR LOWER(skill) LIKE LOWER({ph})
                OR LOWER(COALESCE(keywords, '')) LIKE LOWER({ph})
            )"""
        )
        params.extend([sk, f"%{sk}%", f"%{sk}%"])
    clauses.append("(" + " OR ".join(groups) + ")")


def _should_apply_role_filter(role: str, skills: list[str]) -> bool:
    """When HR lists required skills, match on skill column only — not bank role labels."""
    if [s.strip() for s in (skills or []) if str(s).strip()]:
        return False
    return bool(str(role or "").strip())


def _normalize_filter_values(value: str | list[str] | None, *, allowed: set[str] | None = None) -> list[str]:
    if isinstance(value, list):
        items = [str(v).strip().lower() for v in value if str(v).strip()]
    elif value:
        items = [str(value).strip().lower()]
    else:
        items = []
    if allowed:
        items = [x for x in items if x in allowed]
    return items


def _append_in_filter(
    clauses: list[str],
    params: list[Any],
    db_target: str | Path,
    column: str,
    values: list[str],
) -> None:
    if not values:
        return
    ph = "%s" if _is_postgres(db_target) else "?"
    placeholders = ", ".join([f"LOWER({ph})"] * len(values))
    clauses.append(f"LOWER({column}) IN ({placeholders})")
    params.extend(values)


def _append_excluded_ids_filter(
    clauses: list[str],
    params: list[Any],
    db_target: str | Path,
    excluded_ids: set[str] | list[str] | None,
) -> None:
    ids = [str(x).strip() for x in (excluded_ids or []) if str(x).strip()]
    if not ids:
        return
    ph = "%s" if _is_postgres(db_target) else "?"
    placeholders = ", ".join([ph] * len(ids))
    clauses.append(f"id NOT IN ({placeholders})")
    params.extend(ids)


def _append_interview_filters(
    clauses: list[str],
    params: list[Any],
    db_target: str | Path,
    *,
    difficulty: str | list[str] = "",
    category: str | list[str] = "",
    excluded_ids: set[str] | list[str] | None = None,
) -> None:
    ph = "%s" if _is_postgres(db_target) else "?"
    clauses.append(f"LOWER(approval_status) = LOWER({ph})")
    params.append("approved")
    diffs = _normalize_filter_values(difficulty, allowed={"easy", "medium", "hard"})
    cats = _normalize_filter_values(category, allowed={"technical", "behavioral", "situational", "general"})
    _append_in_filter(clauses, params, db_target, "difficulty", diffs)
    _append_in_filter(clauses, params, db_target, "category", cats)
    _append_excluded_ids_filter(clauses, params, db_target, excluded_ids)


def _row_matches_requested_skill(row: dict, requested_skills: list[str]) -> str | None:
    """Return the canonical requested skill label that matches this bank row, if any."""
    row_skill = str(row.get("skill") or "").strip().lower()
    if not row_skill:
        return None
    for sk in requested_skills:
        sk_norm = sk.strip()
        if not sk_norm:
            continue
        sk_lower = sk_norm.lower()
        if row_skill == sk_lower or sk_lower in row_skill or row_skill in sk_lower:
            return sk_norm
    return None


def _row_bucket_key(row: dict, requested_skills: list[str]) -> tuple[str, str, str] | None:
    """Bucket key (skill, category, difficulty) for balanced selection."""
    skill_label = (
        _row_matches_requested_skill(row, requested_skills)
        if requested_skills
        else str(row.get("skill") or "").strip()
    )
    if requested_skills and not skill_label:
        return None
    skill = (skill_label or "_any").strip().lower()
    category = str(row.get("category") or "").strip().lower() or "_any"
    difficulty = str(row.get("difficulty") or "").strip().lower() or "_any"
    return (skill, category, difficulty)


def _pick_balanced_selection(
    rows: list[dict],
    *,
    requested_skills: list[str],
    requested_categories: list[str],
    requested_difficulties: list[str],
    count: int,
    randomize: bool,
    rng: Any,
) -> list[dict]:
    """Round-robin across skill × category × difficulty buckets for even coverage."""
    if not rows:
        return []
    count = max(1, count)
    skills = [s.strip() for s in requested_skills if str(s).strip()]
    categories = [c.strip().lower() for c in requested_categories if str(c).strip()]
    difficulties = [d.strip().lower() for d in requested_difficulties if str(d).strip()]

    buckets: dict[tuple[str, str, str], list[dict]] = {}
    overflow: list[dict] = []
    for row in rows:
        key = _row_bucket_key(row, skills)
        if key is None:
            overflow.append(row)
            continue
        buckets.setdefault(key, []).append(row)

    if not buckets:
        if randomize:
            rng.shuffle(rows)
        return rows[:count]

    if randomize:
        for pool in buckets.values():
            rng.shuffle(pool)
        rng.shuffle(overflow)

    def _bucket_order(key: tuple[str, str, str]) -> tuple[int, int, int]:
        sk, cat, diff = key
        sk_idx = next((i for i, s in enumerate(skills) if s.lower() == sk), 999)
        cat_idx = next((i for i, c in enumerate(categories) if c == cat), 999) if categories else 0
        diff_idx = next((i for i, d in enumerate(difficulties) if d == diff), 999) if difficulties else 0
        return (sk_idx, diff_idx, cat_idx)

    selected: list[dict] = []
    seen_ids: set[str] = set()
    active_keys = sorted(buckets.keys(), key=_bucket_order)

    while len(selected) < count and active_keys:
        progressed = False
        next_keys: list[tuple[str, str, str]] = []
        for key in active_keys:
            if len(selected) >= count:
                break
            pool = buckets.get(key) or []
            picked: dict | None = None
            while pool:
                candidate = pool.pop(0)
                cid = str(candidate.get("id") or "")
                if cid and cid in seen_ids:
                    continue
                picked = candidate
                break
            if picked is not None:
                selected.append(picked)
                cid = str(picked.get("id") or "")
                if cid:
                    seen_ids.add(cid)
                progressed = True
            if pool:
                next_keys.append(key)
        active_keys = next_keys
        if not progressed:
            break

    if len(selected) < count:
        remainder: list[dict] = []
        for key in sorted(buckets.keys(), key=_bucket_order):
            remainder.extend(buckets.get(key) or [])
        remainder.extend(overflow)
        if randomize:
            rng.shuffle(remainder)
        for row in remainder:
            if len(selected) >= count:
                break
            cid = str(row.get("id") or "")
            if cid and cid in seen_ids:
                continue
            selected.append(row)
            if cid:
                seen_ids.add(cid)

    if randomize and len(selected) > 1:
        rng.shuffle(selected)
    return selected[:count]


def _pick_balanced_by_skill(
    rows: list[dict],
    requested_skills: list[str],
    count: int,
    *,
    randomize: bool,
    rng: Any,
) -> list[dict]:
    """Backward-compatible wrapper — balances by skill only."""
    return _pick_balanced_selection(
        rows,
        requested_skills=requested_skills,
        requested_categories=[],
        requested_difficulties=[],
        count=count,
        randomize=randomize,
        rng=rng,
    )


def count_questions_for_interview(
    db_target: str | Path,
    *,
    role: str = "",
    skills: list[str],
    difficulty: str | list[str] = "",
    category: str | list[str] = "",
    excluded_ids: set[str] | list[str] | None = None,
) -> int:
    clauses = ["is_active = TRUE"] if _is_postgres(db_target) else ["is_active = 1"]
    params: list[Any] = []
    norm_skills = [s.strip() for s in (skills or []) if str(s).strip()]
    if _should_apply_role_filter(role, norm_skills):
        _append_role_filter(clauses, params, db_target, role, norm_skills)
    _append_skills_filter(clauses, params, db_target, norm_skills)
    _append_interview_filters(
        clauses,
        params,
        db_target,
        difficulty=difficulty,
        category=category,
        excluded_ids=excluded_ids,
    )
    where = " WHERE " + " AND ".join(clauses)
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM question_bank{where}", tuple(params))
                return int((cur.fetchone() or [0])[0])
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM question_bank{where}", tuple(params))
        return int((cur.fetchone() or [0])[0])


def select_questions_for_interview(
    db_target: str | Path,
    *,
    role: str = "",
    skills: list[str],
    difficulty: str | list[str] = "",
    category: str | list[str] = "",
    count: int = 10,
    randomize: bool = True,
    avoid_hashes: set[str] | None = None,
    excluded_ids: set[str] | list[str] | None = None,
    seed: str = "",
    balance_skills: list[str] | None = None,
    balance_categories: list[str] | None = None,
    balance_difficulties: list[str] | None = None,
) -> list[dict]:
    import hashlib
    import random

    clauses = ["is_active = TRUE"] if _is_postgres(db_target) else ["is_active = 1"]
    params: list[Any] = []
    norm_skills = [s.strip() for s in (skills or []) if str(s).strip()]
    if _should_apply_role_filter(role, norm_skills):
        _append_role_filter(clauses, params, db_target, role, norm_skills)
    _append_skills_filter(clauses, params, db_target, norm_skills)
    _append_interview_filters(
        clauses,
        params,
        db_target,
        difficulty=difficulty,
        category=category,
        excluded_ids=excluded_ids,
    )
    where = " WHERE " + " AND ".join(clauses)
    qcol = _question_column_expr(db_target)
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, role, skill, difficulty, category,
                           {qcol} AS question,
                           expected_answer, keywords, question_hash
                    FROM question_bank{where}
                    """,
                    tuple(params),
                )
                raw = [
                    dict(
                        zip(
                            [
                                "id",
                                "role",
                                "skill",
                                "difficulty",
                                "category",
                                "question",
                                "expected_answer",
                                "keywords",
                                "question_hash",
                            ],
                            r,
                        )
                    )
                    for r in (cur.fetchall() or [])
                ]
        else:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT id, role, skill, difficulty, category,
                       {qcol} AS question,
                       expected_answer, keywords, question_hash
                FROM question_bank{where}
                """,
                tuple(params),
            )
            raw = [dict(r) for r in (cur.fetchall() or [])]
    avoid = avoid_hashes or set()
    seen_hashes: set[str] = set()
    unique: list[dict] = []
    for row in raw:
        h = row.get("question_hash") or question_hash(row.get("question") or "")
        if h in avoid or h in seen_hashes:
            continue
        seen_hashes.add(h)
        unique.append(row)
    rng = random.Random(int(hashlib.sha256(seed.encode()).hexdigest()[:16], 16) if seed else None)
    balance_skill_list = [s.strip() for s in (balance_skills or norm_skills) if str(s).strip()]
    balance_cat_list = _normalize_filter_values(
        balance_categories if balance_categories is not None else category,
        allowed={"technical", "behavioral", "situational", "general"},
    )
    balance_diff_list = _normalize_filter_values(
        balance_difficulties if balance_difficulties is not None else difficulty,
        allowed={"easy", "medium", "hard"},
    )
    if unique:
        return _pick_balanced_selection(
            unique,
            requested_skills=balance_skill_list,
            requested_categories=balance_cat_list,
            requested_difficulties=balance_diff_list,
            count=count,
            randomize=randomize,
            rng=rng,
        )
    return []


def lookup_expected_answers_by_hashes(
    db_target: str | Path,
    hashes: Sequence[str],
) -> dict[str, str]:
    """Return question_hash -> expected_answer for active bank rows."""
    wanted = sorted({str(h or "").strip() for h in (hashes or []) if str(h or "").strip()})
    if not wanted:
        return {}
    out: dict[str, str] = {}
    ph = "%s" if _is_postgres(db_target) else "?"
    placeholders = ", ".join([ph] * len(wanted))
    approval_clause = "AND approval_status = 'approved'" if qb_require_approval() else ""
    if _is_postgres(db_target):
        sql = f"""
            SELECT question_hash, expected_answer
            FROM question_bank
            WHERE is_active = TRUE
              AND COALESCE(TRIM(expected_answer), '') <> ''
              {approval_clause}
              AND question_hash IN ({placeholders})
        """
    else:
        sql = f"""
            SELECT question_hash, expected_answer
            FROM question_bank
            WHERE is_active = 1
              AND TRIM(COALESCE(expected_answer, '')) <> ''
              {approval_clause}
              AND question_hash IN ({placeholders})
        """
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(sql, tuple(wanted))
                rows = cur.fetchall() or []
        else:
            cur = conn.cursor()
            cur.execute(sql, tuple(wanted))
            rows = cur.fetchall() or []
    for row in rows:
        if isinstance(row, dict):
            h = str(row.get("question_hash") or "").strip()
            expected = str(row.get("expected_answer") or "").strip()
        else:
            h = str(row[0] or "").strip()
            expected = str(row[1] or "").strip()
        if h and expected and h not in out:
            out[h] = expected
    return out


def persist_interview_questions(
    db_target: str | Path,
    interview_id: str,
    items: list[dict],
    *,
    question_source: str = "QUESTION_BANK",
) -> None:
    now = _now_iso()
    ph = "%s" if _is_postgres(db_target) else "?"
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                for i, item in enumerate(items):
                    cur.execute(
                        f"""
                        INSERT INTO interview_question
                        (id, interview_id, question_id, question_text, expected_answer, skill,
                         difficulty, question_order, question_source, asked_at)
                        VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                        """,
                        (
                            str(uuid4()),
                            interview_id,
                            item.get("id"),
                            item.get("question") or "",
                            item.get("expected_answer") or "",
                            item.get("skill") or "",
                            item.get("difficulty") or "medium",
                            i + 1,
                            question_source,
                            now,
                        ),
                    )
        else:
            cur = conn.cursor()
            for i, item in enumerate(items):
                cur.execute(
                    f"""
                    INSERT INTO interview_question
                    (id, interview_id, question_id, question_text, expected_answer, skill,
                     difficulty, question_order, question_source, asked_at)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    """,
                    (
                        str(uuid4()),
                        interview_id,
                        item.get("id"),
                        item.get("question") or "",
                        item.get("expected_answer") or "",
                        item.get("skill") or "",
                        item.get("difficulty") or "medium",
                        i + 1,
                        question_source,
                        now,
                    ),
                )
            conn.commit()


def save_candidate_answer(
    db_target: str | Path,
    *,
    interview_id: str,
    candidate_id: str,
    question_id: str | None,
    question_text: str,
    expected_answer: str,
    candidate_answer: str,
    answer_duration: float = 0,
    question_source: str = "QUESTION_BANK",
    question_order: int = 0,
) -> str:
    aid = str(uuid4())
    now = _now_iso()
    ph = "%s" if _is_postgres(db_target) else "?"
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO candidate_answer
                    (id, interview_id, candidate_id, question_id, question_text_snapshot,
                     expected_answer_snapshot, candidate_answer, answer_duration, question_source,
                     question_order, created_at)
                    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                    """,
                    (
                        aid,
                        interview_id,
                        candidate_id,
                        question_id,
                        question_text,
                        expected_answer,
                        candidate_answer,
                        answer_duration,
                        question_source,
                        int(question_order or 0),
                        now,
                    ),
                )
        else:
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO candidate_answer
                (id, interview_id, candidate_id, question_id, question_text_snapshot,
                 expected_answer_snapshot, candidate_answer, answer_duration, question_source,
                 question_order, created_at)
                VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
                """,
                (
                    aid,
                    interview_id,
                    candidate_id,
                    question_id,
                    question_text,
                    expected_answer,
                    candidate_answer,
                    answer_duration,
                    question_source,
                    int(question_order or 0),
                    now,
                ),
            )
            conn.commit()
    return aid


def save_evaluation_result(db_target: str | Path, candidate_answer_id: str, row: dict) -> str:
    eid = str(uuid4())
    now = _now_iso()

    def _list_field(key: str) -> str:
        val = row.get(key)
        if isinstance(val, list):
            return json.dumps([str(x) for x in val if str(x).strip()])
        return json.dumps([])

    dims = row.get("dimension_scores") if isinstance(row.get("dimension_scores"), dict) else {}
    try:
        technical = float(dims.get("technical_accuracy") or row.get("technical_score") or row.get("score") or 0)
    except (TypeError, ValueError):
        technical = 0.0
    try:
        communication = float(dims.get("communication") or row.get("communication_score") or 0)
    except (TypeError, ValueError):
        communication = 0.0
    try:
        confidence = float(dims.get("confidence") or row.get("confidence_score") or 0)
    except (TypeError, ValueError):
        confidence = 0.0
    try:
        problem_solving = float(dims.get("depth") or row.get("problem_solving_score") or row.get("score") or 0)
    except (TypeError, ValueError):
        problem_solving = 0.0
    try:
        completeness = float(dims.get("concept_coverage") or row.get("completeness_score") or 0)
    except (TypeError, ValueError):
        completeness = 0.0
    try:
        overall = float(row.get("overall_rating") or row.get("score") or 0)
    except (TypeError, ValueError):
        overall = 0.0

    ideal = str(
        row.get("ideal_answer") or row.get("expected_answer") or row.get("reference_expected_answer") or ""
    ).strip()
    feedback = str(
        row.get("interview_feedback") or row.get("feedback") or row.get("evaluation_summary") or row.get("summary") or ""
    ).strip()
    improvements = row.get("improvement_areas")
    if isinstance(improvements, list) and improvements and isinstance(improvements[0], dict):
        improvement_json = json.dumps(improvements)
    else:
        improvement_json = _list_field("improvement_areas") if row.get("improvement_areas") else _list_field("weaknesses")

    ph = "%s" if _is_postgres(db_target) else "?"
    payload = (
        eid,
        candidate_answer_id,
        technical,
        communication,
        confidence,
        problem_solving,
        completeness,
        overall,
        _list_field("strengths"),
        _list_field("weaknesses"),
        improvement_json,
        ideal,
        feedback,
        now,
    )
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO evaluation_result
                    (id, candidate_answer_id, technical_score, communication_score, confidence_score,
                     problem_solving_score, completeness_score, overall_score, strengths, weaknesses,
                     improvement_areas, ideal_answer, ai_feedback, evaluated_at)
                    VALUES ({", ".join([ph] * 14)})
                    """,
                    payload,
                )
        else:
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO evaluation_result
                (id, candidate_answer_id, technical_score, communication_score, confidence_score,
                 problem_solving_score, completeness_score, overall_score, strengths, weaknesses,
                 improvement_areas, ideal_answer, ai_feedback, evaluated_at)
                VALUES ({", ".join([ph] * 14)})
                """,
                payload,
            )
            conn.commit()
    return eid


def _save_question_version_snapshot(
    db_target: str | Path,
    question_row: dict,
    *,
    actor: str = "",
    note: str = "",
) -> None:
    _ensure_question_bank_versions_table(db_target)
    qid = str(question_row.get("id") or "").strip()
    if not qid:
        return
    vid = str(uuid4())
    ver = int(question_row.get("version") or 1)
    row = (
        vid,
        qid,
        ver,
        str(question_row.get("question") or ""),
        str(question_row.get("expectedAnswer") or question_row.get("expected_answer") or ""),
        str(question_row.get("approvalStatus") or question_row.get("approval_status") or "approved"),
        actor,
        note,
        _now_iso(),
    )
    ph = "%s" if _is_postgres(db_target) else "?"
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO question_bank_versions
                    (id, question_id, version, question, expected_answer, approval_status,
                     changed_by, change_note, changed_at)
                    VALUES ({", ".join([ph] * 9)})
                    """,
                    row,
                )
        else:
            cur = conn.cursor()
            cur.execute(
                f"""
                INSERT INTO question_bank_versions
                (id, question_id, version, question, expected_answer, approval_status,
                 changed_by, change_note, changed_at)
                VALUES ({", ".join([ph] * 9)})
                """,
                row,
            )
            conn.commit()


def get_question_versions(db_target: str | Path, question_id: str) -> list[dict]:
    _ensure_question_bank_versions_table(db_target)
    ph = "%s" if _is_postgres(db_target) else "?"
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, question_id, version, question, expected_answer, approval_status,
                           changed_by, change_note, changed_at
                    FROM question_bank_versions
                    WHERE question_id = {ph}
                    ORDER BY version DESC, changed_at DESC
                    """,
                    (question_id,),
                )
                rows = cur.fetchall() or []
        else:
            cur = conn.cursor()
            cur.execute(
                f"""
                SELECT id, question_id, version, question, expected_answer, approval_status,
                       changed_by, change_note, changed_at
                FROM question_bank_versions
                WHERE question_id = ?
                ORDER BY version DESC, changed_at DESC
                """,
                (question_id,),
            )
            rows = [dict(r) for r in (cur.fetchall() or [])]
    out: list[dict] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(dict(row))
        else:
            out.append(
                {
                    "id": row[0],
                    "question_id": row[1],
                    "version": row[2],
                    "question": row[3],
                    "expected_answer": row[4],
                    "approval_status": row[5],
                    "changed_by": row[6],
                    "change_note": row[7],
                    "changed_at": row[8],
                }
            )
    return out


def list_pending_questions(db_target: str | Path, *, page: int = 1, page_size: int = 25) -> dict:
    page = max(1, int(page or 1))
    page_size = max(1, min(int(page_size or 25), 200))
    offset = (page - 1) * page_size
    ph = "%s" if _is_postgres(db_target) else "?"
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) FROM question_bank WHERE approval_status = 'pending' AND is_active = TRUE"
                )
                total = int((cur.fetchone() or [0])[0])
                cur.execute(
                    f"""
                    SELECT {_select_columns()}
                    FROM question_bank
                    WHERE approval_status = 'pending' AND is_active = TRUE
                    ORDER BY updated_at DESC
                    LIMIT {ph} OFFSET {ph}
                    """,
                    (page_size, offset),
                )
                rows = [_question_api(_row_to_dict(r)) for r in (cur.fetchall() or [])]
        else:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM question_bank WHERE approval_status = 'pending' AND is_active = 1"
            )
            total = int((cur.fetchone() or [0])[0])
            cur.execute(
                f"""
                SELECT {_select_columns()}
                FROM question_bank
                WHERE approval_status = 'pending' AND is_active = 1
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset),
            )
            rows = [_question_api(_row_to_dict(dict(r))) for r in (cur.fetchall() or [])]
    return {"items": rows, "total": total, "page": page, "pageSize": page_size}


def set_question_approval_status(
    db_target: str | Path,
    question_id: str,
    status: str,
    *,
    actor: str = "",
    note: str = "",
) -> dict:
    status_clean = str(status or "").strip().lower()
    if status_clean not in VALID_APPROVAL_STATUSES:
        raise ValueError("Invalid approval status")
    existing = get_question(db_target, question_id)
    if not existing:
        raise ValueError("Question not found")
    if status_clean == existing.get("approvalStatus"):
        return existing
    _save_question_version_snapshot(db_target, existing, actor=actor, note=note or f"approval:{status_clean}")
    ph = "%s" if _is_postgres(db_target) else "?"
    now = _now_iso()
    with _connect(db_target) as conn:
        if _is_postgres(db_target):
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE question_bank SET approval_status = {ph}, updated_at = {ph} WHERE id = {ph}",
                    (status_clean, now, question_id),
                )
        else:
            cur = conn.cursor()
            cur.execute(
                "UPDATE question_bank SET approval_status = ?, updated_at = ? WHERE id = ?",
                (status_clean, now, question_id),
            )
            conn.commit()
    return get_question(db_target, question_id) or {}
