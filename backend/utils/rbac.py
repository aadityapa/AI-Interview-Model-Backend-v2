"""HR RBAC — recruiter, hiring_manager, super_admin."""

from __future__ import annotations

import os
from typing import Any

VALID_HR_SUB_ROLES = frozenset({"recruiter", "hiring_manager", "super_admin"})

# permission -> roles allowed
PERMISSIONS: dict[str, frozenset[str]] = {
    "reports.view": frozenset({"recruiter", "hiring_manager", "super_admin"}),
    "schedule.create": frozenset({"recruiter", "hiring_manager", "super_admin"}),
    "candidates.view": frozenset({"recruiter", "hiring_manager", "super_admin"}),
    "score.moderate": frozenset({"hiring_manager", "super_admin"}),
    "candidate.decide": frozenset({"hiring_manager", "super_admin"}),
    "template.manage": frozenset({"hiring_manager", "super_admin"}),
    "reports.rescore": frozenset({"hiring_manager", "super_admin"}),
    "qb.write": frozenset({"super_admin"}),
    "qb.approve": frozenset({"super_admin"}),
    "audit.view": frozenset({"hiring_manager", "super_admin"}),
}


def _env_super_admin_emails() -> set[str]:
    raw = (os.getenv("SUPER_ADMIN_EMAILS") or "").strip()
    return {e.strip().lower() for e in raw.split(",") if e.strip()}


def _env_super_admin_usernames() -> set[str]:
    raw = (os.getenv("SUPER_ADMIN_USERNAMES") or "").strip()
    return {u.strip().lower() for u in raw.split(",") if u.strip()}


def resolve_hr_sub_role(user: dict | None, *, is_super_admin: bool = False) -> str:
    if not user:
        return "recruiter"
    if is_super_admin:
        return "super_admin"
    role = str(user.get("role") or "").strip().lower()
    if role != "hr":
        return ""
    sub = str(user.get("hr_sub_role") or user.get("hrSubRole") or "").strip().lower()
    if sub in VALID_HR_SUB_ROLES:
        return sub
    email = str(user.get("email") or "").strip().lower()
    username = str(user.get("username") or user.get("sub") or "").strip().lower()
    if email in _env_super_admin_emails() or username in _env_super_admin_usernames():
        return "super_admin"
    return "recruiter"


def has_permission(payload: dict | None, permission: str, *, is_super_admin: bool = False) -> bool:
    if not payload:
        return False
    role = str(payload.get("role") or "").strip().lower()
    if role in {"admin", "manager"}:
        return True
    if role != "hr":
        return False
    sub_role = resolve_hr_sub_role(payload, is_super_admin=is_super_admin)
    allowed = PERMISSIONS.get(permission)
    if not allowed:
        return False
    return sub_role in allowed


def permission_denied_message(permission: str) -> str:
    return f"Forbidden — requires permission: {permission}"
