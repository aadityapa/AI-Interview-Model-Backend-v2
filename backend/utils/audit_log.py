"""Immutable HR audit trail."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect(db_target: str | Path):
    from auth_db import _connect_postgres, _connect_sqlite, _is_postgres

    if _is_postgres(db_target):
        return _connect_postgres(str(db_target))
    import sqlite3

    conn = sqlite3.connect(str(db_target))
    conn.row_factory = sqlite3.Row
    return conn


def ensure_audit_log_table(db_target: str | Path) -> None:
    from auth_db import _is_postgres

    pg = _is_postgres(db_target)
    with _connect(db_target) as conn:
        if pg:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS hr_audit_log (
                        id TEXT PRIMARY KEY,
                        actor_email TEXT NOT NULL DEFAULT '',
                        actor_username TEXT NOT NULL DEFAULT '',
                        actor_role TEXT NOT NULL DEFAULT '',
                        hr_sub_role TEXT NOT NULL DEFAULT '',
                        action TEXT NOT NULL,
                        resource_type TEXT NOT NULL DEFAULT '',
                        resource_id TEXT NOT NULL DEFAULT '',
                        details JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_hr_audit_resource ON hr_audit_log (resource_type, resource_id)"
                )
        else:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS hr_audit_log (
                    id TEXT PRIMARY KEY,
                    actor_email TEXT NOT NULL DEFAULT '',
                    actor_username TEXT NOT NULL DEFAULT '',
                    actor_role TEXT NOT NULL DEFAULT '',
                    hr_sub_role TEXT NOT NULL DEFAULT '',
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL DEFAULT '',
                    resource_id TEXT NOT NULL DEFAULT '',
                    details TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL DEFAULT ''
                )
                """
            )
            conn.commit()


def write_audit_log(
    db_target: str | Path,
    *,
    actor: dict | None,
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    details: dict | None = None,
) -> str:
    from utils.rbac import resolve_hr_sub_role

    ensure_audit_log_table(db_target)
    from auth_db import _is_postgres

    pg = _is_postgres(db_target)
    row_id = str(uuid4())
    actor = actor or {}
    payload = details if isinstance(details, dict) else {}
    values = (
        row_id,
        str(actor.get("email") or "").strip().lower(),
        str(actor.get("sub") or actor.get("username") or "").strip().lower(),
        str(actor.get("role") or "").strip().lower(),
        resolve_hr_sub_role(actor),
        str(action or "").strip(),
        str(resource_type or "").strip(),
        str(resource_id or "").strip(),
        json.dumps(payload, default=str) if not pg else payload,
        _now_iso(),
    )
    with _connect(db_target) as conn:
        if pg:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO hr_audit_log
                    (id, actor_email, actor_username, actor_role, hr_sub_role, action,
                     resource_type, resource_id, details, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                    """,
                    values,
                )
        else:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO hr_audit_log
                (id, actor_email, actor_username, actor_role, hr_sub_role, action,
                 resource_type, resource_id, details, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
            conn.commit()
    return row_id
