"""Admin / observability routes: prompt logs.

These routes are read-only and isolated; moving them out of main.py keeps the
core app assembly small. URL paths are unchanged.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from prompt_logger import (
    cleanup_old_db_logs,
    cleanup_old_file_logs,
    get_distinct_values,
    get_prompt_log_by_id,
    get_token_usage_stats,
    query_prompt_logs,
)

logger = logging.getLogger("karnex.routers.admin")

router = APIRouter()

# Filled by configure() from main.py once dependencies are available.
_AUTH_DB_TARGET: str = ""
_REQUIRE_USER: Callable[[Request, set[str] | None], tuple[dict | None, Any]] | None = None


def configure(auth_db_target: str, require_user: Callable) -> None:
    """main.py calls this once at startup."""
    global _AUTH_DB_TARGET, _REQUIRE_USER
    _AUTH_DB_TARGET = auth_db_target
    _REQUIRE_USER = require_user


def _auth(request: Request) -> tuple[dict | None, Any]:
    if _REQUIRE_USER is None:
        return None, JSONResponse({"error": "Server not initialized."}, status_code=500)
    return _REQUIRE_USER(request, {"hr"})


@router.get("/api/prompt-logs")
def api_prompt_logs(
    request: Request,
    call_type: str = "",
    model: str = "",
    status: str = "",
    candidate_id: str = "",
    interview_id: str = "",
    template_id: str = "",
    date_from: str = "",
    date_to: str = "",
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    sort_by: str = "created_at_ist",
    sort_order: str = "desc",
):
    _, err = _auth(request)
    if err:
        return err
    return query_prompt_logs(
        _AUTH_DB_TARGET,
        call_type=call_type,
        model=model,
        status=status,
        candidate_id=candidate_id,
        interview_id=interview_id,
        template_id=template_id,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=max(1, min(int(limit or 50), 200)),
        offset=max(0, int(offset or 0)),
        sort_by=sort_by,
        sort_order=sort_order,
    )


@router.get("/api/prompt-logs/stats")
def api_prompt_logs_stats(request: Request, days: int = 30):
    _, err = _auth(request)
    if err:
        return err
    return get_token_usage_stats(_AUTH_DB_TARGET, days=max(1, min(int(days or 30), 365)))


@router.get("/api/prompt-logs/filters")
def api_prompt_logs_filters(request: Request):
    _, err = _auth(request)
    if err:
        return err
    return {
        "call_types": get_distinct_values(_AUTH_DB_TARGET, "call_type"),
        "models": get_distinct_values(_AUTH_DB_TARGET, "model"),
        "statuses": get_distinct_values(_AUTH_DB_TARGET, "status"),
        "difficulties": get_distinct_values(_AUTH_DB_TARGET, "difficulty"),
        "templates": get_distinct_values(_AUTH_DB_TARGET, "template_name"),
    }


@router.get("/api/prompt-logs/{log_id}")
def api_prompt_log_detail(log_id: str, request: Request):
    _, err = _auth(request)
    if err:
        return err
    entry = get_prompt_log_by_id(_AUTH_DB_TARGET, log_id)
    if not entry:
        return JSONResponse({"error": "Log not found."}, status_code=404)
    return {"log": entry}


@router.post("/api/prompt-logs/cleanup")
def api_prompt_logs_cleanup(request: Request):
    _, err = _auth(request)
    if err:
        return err
    file_removed = cleanup_old_file_logs()
    db_removed = cleanup_old_db_logs(_AUTH_DB_TARGET)
    return {"status": "ok", "file_dirs_removed": file_removed, "db_rows_removed": db_removed}


@router.get("/api/prompt-logs/export")
def api_prompt_logs_export(
    request: Request,
    call_type: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 1000,
):
    _, err = _auth(request)
    if err:
        return err
    result = query_prompt_logs(
        _AUTH_DB_TARGET,
        call_type=call_type,
        date_from=date_from,
        date_to=date_to,
        limit=max(1, min(int(limit or 1000), 5000)),
        offset=0,
    )
    logs = result.get("logs", [])
    content = json.dumps(logs, ensure_ascii=False, indent=2, default=str)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=prompt_logs_export.json"},
    )
