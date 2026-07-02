"""Interview session state — memory or Redis (see session_store.py)."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator
import threading

from session_store import (
    SessionStore,
    redis_available,
    release_session_lock as _release_session_lock,
    session_backend,
    session_lock as _session_lock_impl,
)

sessions: SessionStore = SessionStore()
proctor_sessions: SessionStore = SessionStore(prefix="karnex:proctor:")


@contextmanager
def session_lock(session_key: str) -> Iterator[threading.Lock]:
    with _session_lock_impl(session_key, store=sessions):
        yield


def release_session_lock(session_key: str) -> None:
    _release_session_lock(session_key)


__all__ = [
    "sessions",
    "proctor_sessions",
    "session_lock",
    "release_session_lock",
    "redis_available",
    "session_backend",
    "SessionStore",
]
