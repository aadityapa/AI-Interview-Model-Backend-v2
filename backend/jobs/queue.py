"""Background jobs — Celery/Redis when configured, in-process thread fallback otherwise."""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)

_QUEUE_KEY = "karnex:jobs"
_consumer_started = False
_consumer_lock = threading.Lock()


def _job_queue_mode() -> str:
    mode = str(os.getenv("JOB_QUEUE_MODE") or "auto").strip().lower()
    if mode in {"sync", "redis", "celery"}:
        return mode
    if (os.getenv("CELERY_BROKER_URL") or "").strip() and _celery_enabled():
        return "celery"
    if (os.getenv("REDIS_URL") or "").strip():
        return "redis"
    return "sync"


def _celery_enabled() -> bool:
    return str(os.getenv("CELERY_ENABLED") or "false").strip().lower() in {"1", "true", "yes", "on"}


def job_backend() -> str:
    return _job_queue_mode()


def _run_sync(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    try:
        fn(*args, **kwargs)
    except Exception as exc:
        logger.warning("job.sync.failed", extra={"fn": getattr(fn, "__name__", ""), "error": str(exc)[:300]}, exc_info=True)


def _enqueue_redis(job_type: str, payload: dict) -> bool:
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return False
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(url, decode_responses=True)
        client.lpush(_QUEUE_KEY, json.dumps({"type": job_type, "payload": payload}, default=str))
        _ensure_redis_consumer()
        return True
    except Exception as exc:
        logger.warning("job.redis.enqueue_failed", extra={"type": job_type, "error": str(exc)[:200]})
        return False


def _enqueue_celery(job_type: str, payload: dict) -> bool:
    if not _celery_enabled():
        return False
    try:
        from jobs.celery_app import celery_app

        celery_app.send_task(f"karnex.{job_type}", args=[payload])
        return True
    except Exception as exc:
        logger.warning("job.celery.enqueue_failed", extra={"type": job_type, "error": str(exc)[:200]})
        return False


def enqueue(job_type: str, payload: dict, *, sync_fn: Callable[[dict], None] | None = None) -> str:
    """Enqueue a job; always succeeds via sync fallback."""
    mode = _job_queue_mode()
    body = dict(payload or {})
    if mode == "celery" and _enqueue_celery(job_type, body):
        return "celery"
    if mode in {"redis", "celery"} and _enqueue_redis(job_type, body):
        return "redis"
    if sync_fn is not None:
        threading.Thread(target=_run_sync, args=(sync_fn, body), daemon=True).start()
        return "thread"
    return "noop"


def _dispatch(job_type: str, payload: dict) -> None:
    if job_type == "report.upgrade":
        from jobs.handlers import handle_report_upgrade

        handle_report_upgrade(payload)
    elif job_type == "report.finalize":
        from jobs.handlers import handle_report_finalize

        handle_report_finalize(payload)
    elif job_type == "reports.bulk_rescore":
        from jobs.handlers import handle_bulk_rescore

        handle_bulk_rescore(payload)
    else:
        logger.warning("job.unknown_type", extra={"type": job_type})


def _redis_consumer_loop() -> None:
    url = (os.getenv("REDIS_URL") or "").strip()
    if not url:
        return
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(url, decode_responses=True)
    except Exception:
        return
    while True:
        try:
            item = client.brpop(_QUEUE_KEY, timeout=5)
            if not item:
                continue
            _, raw = item
            data = json.loads(raw)
            if isinstance(data, dict):
                _dispatch(str(data.get("type") or ""), data.get("payload") or {})
        except Exception as exc:
            logger.warning("job.redis.consumer_error", extra={"error": str(exc)[:200]})
            threading.Event().wait(1)


def _ensure_redis_consumer() -> None:
    global _consumer_started
    if _job_queue_mode() == "sync":
        return
    with _consumer_lock:
        if _consumer_started:
            return
        _consumer_started = True
        t = threading.Thread(target=_redis_consumer_loop, daemon=True, name="karnex-job-consumer")
        t.start()


def start_job_worker() -> None:
    """Start in-process Redis consumer when JOB_QUEUE_MODE=redis."""
    if _job_queue_mode() in {"redis", "celery"}:
        _ensure_redis_consumer()


def enqueue_report_upgrade(session_snapshot: dict, reason: str, final_status: str) -> str:
    payload = {
        "session_snapshot": session_snapshot,
        "reason": reason,
        "final_status": final_status,
    }
    from jobs.handlers import handle_report_upgrade

    return enqueue("report.upgrade", payload, sync_fn=lambda p: handle_report_upgrade(p))


def enqueue_report_finalize(session_snapshot: dict, reason: str, final_status: str) -> str:
    payload = {
        "session_snapshot": session_snapshot,
        "reason": reason,
        "final_status": final_status,
    }
    from jobs.handlers import handle_report_finalize

    return enqueue("report.finalize", payload, sync_fn=lambda p: handle_report_finalize(p))


def enqueue_bulk_rescore(interview_ids: list[str], *, actor: dict | None = None) -> str:
    payload = {"interview_ids": list(interview_ids or []), "actor": actor or {}}
    from jobs.handlers import handle_bulk_rescore

    return enqueue("reports.bulk_rescore", payload, sync_fn=lambda p: handle_bulk_rescore(p))
