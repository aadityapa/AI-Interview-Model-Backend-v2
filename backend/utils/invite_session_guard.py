"""Invite session validation — detect stale restored sessions vs current job template."""

from __future__ import annotations

from auth_db import _coerce_question_type, get_job_template
from utils.interview_limits import clamp_count_mode_questions, resolve_template_num_q

_SKIP_TOKENS = frozenset({"skip", "skipped", "[skipped]"})


def expected_question_source(job: dict | None) -> str:
    qt = _coerce_question_type((job or {}).get("questionType"))
    if qt == "manual":
        return "manual"
    if qt == "question_bank":
        return "QUESTION_BANK"
    return "dynamic"


def _normalize_question_source(raw: str) -> str:
    src = str(raw or "").strip()
    if not src:
        return ""
    if src.upper() == "QUESTION_BANK":
        return "QUESTION_BANK"
    if src.lower() == "manual":
        return "manual"
    return "dynamic"


def is_locked_question_source(meta: dict | None) -> bool:
    """True when the template forbids AI question generation or in-turn replacement (manual / question bank)."""
    if not isinstance(meta, dict):
        return False
    src = _normalize_question_source(str(meta.get("question_source") or ""))
    if src in ("manual", "QUESTION_BANK"):
        return True
    gen = str(meta.get("generation_mode") or "").strip().lower()
    return gen in ("manual", "question_bank")


def invite_session_has_substantive_answers(session: dict) -> bool:
    meta = session.get("meta") or {}
    warm = {
        int(i)
        for i in (meta.get("warmup_indices") or [])
        if isinstance(i, (int, float, str)) and str(i).lstrip("-").isdigit()
    }
    for i, ans in enumerate(session.get("answers") or []):
        if i in warm:
            continue
        text = str(ans or "").strip()
        if text and text.lower() not in _SKIP_TOKENS:
            return True
    return False


def invite_session_playable(session: dict | None) -> bool:
    """True when the session can serve /next (non-empty pool, cursor not past end)."""
    if not isinstance(session, dict):
        return False
    qs = list(session.get("questions") or [])
    if not qs:
        return False
    if session.get("completed"):
        return False
    cur = int(session.get("current") or 0)
    if cur < len(qs):
        return True
    cap = _count_mode_cap(session)
    if cap is not None and cur < cap:
        return True
    return False


def invite_session_safe_to_rebuild(session: dict) -> bool:
    if not isinstance(session, dict):
        return True
    if invite_session_has_substantive_answers(session):
        return False
    return True


def invite_session_matches_template(
    session: dict | None,
    job: dict | None,
    invite_cfg: dict | None,
) -> bool:
    if not isinstance(session, dict) or not session.get("questions"):
        return False
    if not job:
        return True
    meta = session.get("meta") or {}
    expected_src = expected_question_source(job)
    actual_src = _normalize_question_source(str(meta.get("question_source") or ""))
    if not actual_src:
        gen = str(meta.get("generation_mode") or "").strip().lower()
        if gen == "question_bank":
            actual_src = "QUESTION_BANK"
        elif gen == "manual":
            actual_src = "manual"
        else:
            actual_src = "dynamic"
    if actual_src != expected_src:
        return False

    expected_job = str((job or {}).get("jobId") or "").strip()
    actual_job = str(meta.get("job_id") or "").strip()
    if expected_job and actual_job and expected_job != actual_job:
        return False

    if expected_src == "QUESTION_BANK" and not meta.get("question_bank_snapshot"):
        return False

    timing = str(meta.get("timing_mode") or (invite_cfg or {}).get("timing_mode") or "count").strip().lower()
    if timing == "count" and expected_src == "QUESTION_BANK":
        warm_n = len(meta.get("warmup_indices") or [])
        try:
            session_nq = int(meta.get("num_q") or 0)
        except (TypeError, ValueError):
            session_nq = 0
        expected_n = session_nq if session_nq > 0 else resolve_template_num_q(invite_cfg, job, env_num=None, skills_fallback=5)
        min_total = clamp_count_mode_questions(expected_n) + warm_n
        if len(session.get("questions") or []) < min_total:
            return False
    return True


def _count_mode_cap(session: dict) -> int | None:
    meta = session.get("meta") or {}
    if str(meta.get("timing_mode") or "count").strip().lower() != "count":
        return None
    try:
        nq = int(meta.get("num_q") or 0)
    except (TypeError, ValueError):
        nq = 0
    if nq <= 0:
        return None
    warm = meta.get("warmup_indices") or []
    return nq + len(warm)


def refill_question_bank_pool_if_needed(session: dict, db_target: str) -> bool:
    """Append Question Bank items when a session pool is shorter than the template cap."""
    meta = session.get("meta") or {}
    if _normalize_question_source(str(meta.get("question_source") or "")) != "QUESTION_BANK":
        return False
    cap = _count_mode_cap(session)
    cur = int(session.get("current") or 0)
    qs = list(session.get("questions") or [])
    if cap is None or cur < len(qs) or cur >= cap:
        return False

    job_id = str(meta.get("job_id") or "").strip()
    if not job_id:
        return False
    job = get_job_template(db_target, job_id)
    if not job or expected_question_source(job) != "QUESTION_BANK":
        return False

    weights = job.get("weights") if isinstance(job.get("weights"), dict) else {}
    need = cap - len(qs)
    if need <= 0:
        return False

    from services.question_bank.selection import bootstrap_question_bank_session

    seed = str(meta.get("question_seed") or meta.get("interview_id") or job_id)
    more, snap_extra, _items = bootstrap_question_bank_session(
        db_target,
        weights=weights,
        job=job,
        num_q=need,
        seed=f"{seed}:refill:{len(qs)}",
        avoid_question_texts=qs,
    )
    if not more:
        return False

    base_idx = len(qs)
    session["questions"] = qs + more[:need]
    snapshot = dict(meta.get("question_bank_snapshot") or {})
    if isinstance(snap_extra, dict):
        for key, val in snap_extra.items():
            try:
                snapshot[str(base_idx + int(key))] = val
            except (TypeError, ValueError):
                continue
    meta["question_bank_snapshot"] = snapshot
    meta["pool_generated"] = len(session["questions"])
    return True
