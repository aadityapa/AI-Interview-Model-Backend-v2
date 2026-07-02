"""Job handlers — import lazily to avoid circular imports with main."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def handle_report_upgrade(payload: dict[str, Any]) -> None:
    snap = payload.get("session_snapshot") or {}
    reason = str(payload.get("reason") or "background_upgrade")
    final_status = str(payload.get("final_status") or "completed")
    import main as app_main

    app_main._upgrade_interview_report_background(snap, reason, final_status)


def handle_report_finalize(payload: dict[str, Any]) -> None:
    snap = payload.get("session_snapshot") or {}
    reason = str(payload.get("reason") or "background_finalize")
    final_status = str(payload.get("final_status") or "completed")
    import main as app_main

    app_main._background_finalize_report(snap)


def handle_bulk_rescore(payload: dict[str, Any]) -> None:
    ids = payload.get("interview_ids") or []
    actor = payload.get("actor") or {}
    import main as app_main

    app_main._bulk_rescore_interviews(list(ids), actor=actor)
