"""Enterprise infrastructure tests — sync fallbacks (no Redis required)."""

from __future__ import annotations

import os

import pytest


def test_session_store_memory_backend():
    os.environ.pop("REDIS_URL", None)
    os.environ["SESSION_STORE"] = "memory"
    from session_store import SessionStore, session_backend

    store = SessionStore(prefix="test:session:")
    assert session_backend() == "memory"
    store["k1"] = {"meta": {"x": 1}, "answers": []}
    assert store.get("k1")["meta"]["x"] == 1
    store.persist("k1")
    assert "k1" in store.keys()
    store.pop("k1")
    assert store.get("k1") is None


def test_rbac_permissions():
    from utils.rbac import has_permission, resolve_hr_sub_role

    recruiter = {"role": "hr", "hr_sub_role": "recruiter", "sub": "rec@test"}
    manager = {"role": "hr", "hr_sub_role": "hiring_manager", "sub": "mgr@test"}
    assert resolve_hr_sub_role(recruiter) == "recruiter"
    assert has_permission(recruiter, "reports.view")
    assert not has_permission(recruiter, "score.moderate")
    assert has_permission(manager, "score.moderate")
    assert has_permission(manager, "reports.rescore")


def test_job_queue_sync_fallback(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    monkeypatch.setenv("JOB_QUEUE_MODE", "sync")
    from jobs.queue import enqueue, job_backend

    assert job_backend() == "sync"
    seen: list[str] = []

    def _handler(payload):
        seen.append(str(payload.get("id")))

    backend = enqueue("reports.bulk_rescore", {"id": "abc"}, sync_fn=_handler)
    assert backend == "thread"
    import time

    time.sleep(0.2)
    assert seen == ["abc"]
