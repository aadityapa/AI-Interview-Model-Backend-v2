"""Celery application — optional; only used when CELERY_ENABLED=true."""

from __future__ import annotations

import os

broker = (os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL") or "").strip()
backend = (os.getenv("CELERY_RESULT_BACKEND") or broker or "").strip()

try:
    from celery import Celery

    celery_app = Celery("karnex", broker=broker or "memory://", backend=backend or "cache+memory://")
    celery_app.conf.task_routes = {"karnex.*": {"queue": "karnex"}}
except Exception:  # pragma: no cover
    celery_app = None  # type: ignore
