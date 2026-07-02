"""Question Bank REST API — Super Admin only."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, File, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from services.question_bank.csv_import import import_csv
from services.question_bank.repository import (
    create_question,
    delete_question,
    export_questions_csv,
    get_dashboard_stats,
    get_question,
    get_question_versions,
    list_pending_questions,
    list_questions,
    list_roles_from_questions,
    list_skills,
    list_upload_history,
    set_question_active,
    set_question_approval_status,
    update_question,
)

router = APIRouter(prefix="/api/question-bank", tags=["question-bank"])

_AUTH_DB_TARGET: str = ""
_REQUIRE_USER: Callable[[Request, set[str] | None], tuple[dict | None, Any]] | None = None


def configure(auth_db_target: str, require_user: Callable) -> None:
    global _AUTH_DB_TARGET, _REQUIRE_USER
    _AUTH_DB_TARGET = auth_db_target
    _REQUIRE_USER = require_user


def _super_admin_emails() -> set[str]:
    raw = (os.getenv("SUPER_ADMIN_EMAILS") or "").strip()
    if not raw:
        return set()
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _super_admin_usernames() -> set[str]:
    raw = (os.getenv("SUPER_ADMIN_USERNAMES") or "").strip()
    if not raw:
        return set()
    return {u.strip().lower() for u in raw.split(",") if u.strip()}


def _lookup_email_for_username(username: str) -> str:
    if not username or not _AUTH_DB_TARGET:
        return ""
    try:
        from auth_db import _connect_postgres, _connect_sqlite, _is_postgres

        if _is_postgres(_AUTH_DB_TARGET):
            with _connect_postgres(str(_AUTH_DB_TARGET)) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT email FROM registration_data WHERE LOWER(username) = LOWER(%s) LIMIT 1",
                        (username,),
                    )
                    row = cur.fetchone()
                    return str(row[0] or "").strip().lower() if row else ""
        with _connect_sqlite(Path(_AUTH_DB_TARGET)) as conn:
            row = conn.execute(
                "SELECT email FROM registration_data WHERE LOWER(username) = LOWER(?) LIMIT 1",
                (username,),
            ).fetchone()
            return str(row[0] or "").strip().lower() if row else ""
    except Exception:
        return ""


def is_super_admin(payload: dict) -> bool:
    """Public helper shared with /auth/me."""
    role = str(payload.get("role") or "").strip().lower()
    if role == "admin":
        return True
    username = str(payload.get("sub") or payload.get("username") or "").strip().lower()
    allowed_emails = _super_admin_emails()
    allowed_usernames = _super_admin_usernames()
    if username and username in allowed_usernames:
        return True
    emails_to_check: list[str] = []
    jwt_email = str(payload.get("email") or "").strip().lower()
    if jwt_email:
        emails_to_check.append(jwt_email)
    if username:
        db_email = _lookup_email_for_username(username)
        if db_email and db_email not in emails_to_check:
            emails_to_check.append(db_email)
    for email in emails_to_check:
        if email in allowed_emails:
            return True
    return bool(username and username in allowed_emails)


def _auth_super_admin(request: Request) -> tuple[dict | None, Any]:
    if _REQUIRE_USER is None:
        return None, JSONResponse({"error": "Server not initialized."}, status_code=500)
    payload, err = _REQUIRE_USER(request, {"hr", "admin", "manager"})
    if err:
        return None, err
    if not is_super_admin(payload or {}):
        return None, JSONResponse(
            {
                "error": (
                    "Question Bank is restricted to Super Admin. "
                    "Set SUPER_ADMIN_USERNAMES or SUPER_ADMIN_EMAILS in .env."
                )
            },
            status_code=403,
        )
    return payload, None


@router.get("/dashboard")
def dashboard(request: Request):
    _, err = _auth_super_admin(request)
    if err:
        return err
    return get_dashboard_stats(_AUTH_DB_TARGET)


@router.get("/questions")
def questions_list(
    request: Request,
    page: int = 1,
    pageSize: int = 25,
    role: str = "",
    skill: str = "",
    difficulty: str = "",
    category: str = "",
    search: str = "",
    isActive: str = "",
    approvalStatus: str = "",
):
    _, err = _auth_super_admin(request)
    if err:
        return err
    active_filter = None
    if isActive.lower() in {"true", "1"}:
        active_filter = True
    elif isActive.lower() in {"false", "0"}:
        active_filter = False
    return list_questions(
        _AUTH_DB_TARGET,
        page=page,
        page_size=pageSize,
        role=role,
        skill=skill,
        difficulty=difficulty,
        category=category,
        search=search,
        is_active=active_filter,
        approval_status=approvalStatus,
    )


@router.get("/questions/{question_id}")
def question_get(request: Request, question_id: str):
    _, err = _auth_super_admin(request)
    if err:
        return err
    row = get_question(_AUTH_DB_TARGET, question_id)
    if not row:
        return JSONResponse({"error": "Not found"}, status_code=404)
    return row


@router.post("/questions")
async def question_create(request: Request):
    user, err = _auth_super_admin(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        created_by = str((user or {}).get("sub") or (user or {}).get("email") or "")
        return create_question(_AUTH_DB_TARGET, body, created_by=created_by)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.put("/questions/{question_id}")
async def question_update(request: Request, question_id: str):
    user, err = _auth_super_admin(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:
        body = {}
    try:
        updated_by = str((user or {}).get("sub") or (user or {}).get("email") or "")
        return update_question(_AUTH_DB_TARGET, question_id, body, updated_by=updated_by)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.delete("/questions/{question_id}")
def question_delete(request: Request, question_id: str):
    _, err = _auth_super_admin(request)
    if err:
        return err
    if not delete_question(_AUTH_DB_TARGET, question_id):
        return JSONResponse({"error": "Not found"}, status_code=404)
    return {"status": "ok"}


@router.patch("/questions/{question_id}/activate")
def question_activate(request: Request, question_id: str):
    user, err = _auth_super_admin(request)
    if err:
        return err
    updated_by = str((user or {}).get("sub") or (user or {}).get("email") or "")
    try:
        return set_question_active(_AUTH_DB_TARGET, question_id, True, updated_by=updated_by)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.patch("/questions/{question_id}/deactivate")
def question_deactivate(request: Request, question_id: str):
    user, err = _auth_super_admin(request)
    if err:
        return err
    updated_by = str((user or {}).get("sub") or (user or {}).get("email") or "")
    try:
        return set_question_active(_AUTH_DB_TARGET, question_id, False, updated_by=updated_by)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


@router.get("/roles")
def roles_list(request: Request):
    _, err = _auth_super_admin(request)
    if err:
        return err
    return {"roles": list_roles_from_questions(_AUTH_DB_TARGET)}


@router.get("/skills")
def skills_list(request: Request, role: str = ""):
    _, err = _auth_super_admin(request)
    if err:
        return err
    return {"skills": list_skills(_AUTH_DB_TARGET, role=role)}


@router.post("/import/csv")
async def csv_upload(request: Request, file: UploadFile = File(...)):
    user, err = _auth_super_admin(request)
    if err:
        return err
    content = await file.read()
    if not content:
        return JSONResponse({"error": "Empty file"}, status_code=400)
    from paths import DATA_DIR

    uploaded_by = str((user or {}).get("sub") or (user or {}).get("email") or "")
    result = import_csv(
        _AUTH_DB_TARGET,
        content,
        file_name=file.filename or "upload.csv",
        uploaded_by=uploaded_by,
        error_report_dir=DATA_DIR / "question_bank_errors",
    )
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return result


@router.get("/upload-history")
def upload_history(request: Request, page: int = 1, pageSize: int = 25):
    _, err = _auth_super_admin(request)
    if err:
        return err
    return list_upload_history(_AUTH_DB_TARGET, page=page, page_size=pageSize)


@router.get("/export")
def export_csv(request: Request):
    _, err = _auth_super_admin(request)
    if err:
        return err
    csv_text = export_questions_csv(_AUTH_DB_TARGET)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="question_bank_export.csv"'},
    )


@router.post("/seed-sample")
def seed_sample_questions(request: Request):
    """Import bundled sample CSV (dev/demo). Skips rows that already exist as duplicates."""
    user, err = _auth_super_admin(request)
    if err:
        return err
    from paths import DATA_DIR

    sample_path = DATA_DIR / "question_bank" / "sample_questions.csv"
    if not sample_path.is_file():
        return JSONResponse({"error": f"Sample file not found: {sample_path}"}, status_code=404)
    content = sample_path.read_bytes()
    uploaded_by = str((user or {}).get("sub") or (user or {}).get("email") or "seed-sample")
    try:
        result = import_csv(
            _AUTH_DB_TARGET,
            content,
            file_name="sample_questions.csv",
            uploaded_by=uploaded_by,
            error_report_dir=DATA_DIR / "question_bank_errors",
        )
    except Exception as exc:
        return JSONResponse({"error": f"Import failed: {exc}"}, status_code=500)
    if result.get("error"):
        return JSONResponse(result, status_code=400)
    return result


@router.get("/pending")
def pending_questions(request: Request, page: int = 1, pageSize: int = 25):
    user, err = _auth_super_admin(request)
    if err:
        return err
    from utils.rbac import has_permission

    if not has_permission(user, "qb.approve", is_super_admin=True):
        return JSONResponse({"error": "Forbidden for this role."}, status_code=403)
    return list_pending_questions(_AUTH_DB_TARGET, page=page, page_size=pageSize)


@router.post("/questions/{question_id}/approve")
async def approve_question(request: Request, question_id: str):
    user, err = _auth_super_admin(request)
    if err:
        return err
    from utils.rbac import has_permission

    if not has_permission(user, "qb.approve", is_super_admin=True):
        return JSONResponse({"error": "Forbidden for this role."}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    note = str((body or {}).get("note") or "").strip()
    actor = str((user or {}).get("sub") or (user or {}).get("email") or "")
    try:
        row = set_question_approval_status(_AUTH_DB_TARGET, question_id, "approved", actor=actor, note=note)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"status": "ok", "question": row}


@router.post("/questions/{question_id}/reject")
async def reject_question(request: Request, question_id: str):
    user, err = _auth_super_admin(request)
    if err:
        return err
    from utils.rbac import has_permission

    if not has_permission(user, "qb.approve", is_super_admin=True):
        return JSONResponse({"error": "Forbidden for this role."}, status_code=403)
    try:
        body = await request.json()
    except Exception:
        body = {}
    note = str((body or {}).get("note") or "").strip()
    actor = str((user or {}).get("sub") or (user or {}).get("email") or "")
    try:
        row = set_question_approval_status(_AUTH_DB_TARGET, question_id, "rejected", actor=actor, note=note)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return {"status": "ok", "question": row}


@router.get("/questions/{question_id}/versions")
def question_versions(request: Request, question_id: str):
    _, err = _auth_super_admin(request)
    if err:
        return err
    return {"versions": get_question_versions(_AUTH_DB_TARGET, question_id)}
