"""Interview session persistence — in-memory or Redis-backed for multi-worker deploys."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

logger = logging.getLogger(__name__)

_SESSION_PREFIX = "karnex:session:"
_PROCTOR_PREFIX = "karnex:proctor:"
_LOCK_PREFIX = "karnex:lock:"
_DEFAULT_TTL_SEC = 6 * 60 * 60


def _session_ttl_sec() -> int:
    try:
        return max(300, int(str(os.getenv("SESSION_TTL_SEC") or _DEFAULT_TTL_SEC).strip()))
    except ValueError:
        return _DEFAULT_TTL_SEC


def _redis_url() -> str:
    return (os.getenv("REDIS_URL") or os.getenv("SESSION_REDIS_URL") or "").strip()


def _session_store_mode() -> str:
    mode = str(os.getenv("SESSION_STORE") or "auto").strip().lower()
    if mode in {"memory", "redis"}:
        return mode
    return "redis" if _redis_url() else "memory"


class _RedisClient:
  """Lazy Redis client — never raises at import time."""

  def __init__(self) -> None:
      self._client: Any = None
      self._available: bool | None = None

  @property
  def enabled(self) -> bool:
      if _session_store_mode() == "memory":
          return False
      if not _redis_url():
          return False
      return self._ensure() is not None

  def _ensure(self) -> Any | None:
      if self._available is False:
          return None
      if self._client is not None:
          return self._client
      try:
          import redis  # type: ignore

          self._client = redis.Redis.from_url(_redis_url(), decode_responses=True)
          self._client.ping()
          self._available = True
          return self._client
      except Exception as exc:
          self._available = False
          logger.warning(
              "session_store.redis.unavailable",
              extra={"event": "session_store.redis.unavailable", "error": str(exc)[:200]},
          )
          return None

  def ping(self) -> bool:
      client = self._ensure()
      if not client:
          return False
      try:
          client.ping()
          return True
      except Exception:
          return False


_redis = _RedisClient()


def redis_available() -> bool:
    return _redis.enabled


def session_backend() -> str:
    return "redis" if _redis.enabled else "memory"


class SessionStore:
    """Dict-like store with optional Redis write-through."""

    def __init__(self, *, prefix: str = _SESSION_PREFIX) -> None:
        self._prefix = prefix
        self._local: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _key(self, session_key: str) -> str:
        return f"{self._prefix}{session_key}"

    def _serialize(self, value: dict) -> str:
        return json.dumps(value, default=str, separators=(",", ":"))

    def _deserialize(self, raw: str) -> dict:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}

    def _load_from_redis(self, session_key: str) -> dict | None:
        if not _redis.enabled:
            return None
        client = _redis._ensure()
        if not client:
            return None
        try:
            raw = client.get(self._key(session_key))
            if not raw:
                return None
            return self._deserialize(raw)
        except Exception as exc:
            logger.warning("session_store.redis.get_failed", extra={"key": session_key, "error": str(exc)[:120]})
            return None

    def _save_to_redis(self, session_key: str, value: dict) -> None:
        if not _redis.enabled:
            return
        client = _redis._ensure()
        if not client:
            return
        try:
            client.setex(self._key(session_key), _session_ttl_sec(), self._serialize(value))
        except Exception as exc:
            logger.warning("session_store.redis.set_failed", extra={"key": session_key, "error": str(exc)[:120]})

    def _delete_from_redis(self, session_key: str) -> None:
        if not _redis.enabled:
            return
        client = _redis._ensure()
        if not client:
            return
        try:
            client.delete(self._key(session_key))
        except Exception:
            pass

    def get(self, session_key: str, default: Any = None) -> Any:
        key = str(session_key or "").strip()
        if not key:
            return default
        with self._lock:
            if key in self._local:
                return self._local[key]
            loaded = self._load_from_redis(key)
            if loaded is not None:
                self._local[key] = loaded
                return loaded
        return default

    def __contains__(self, session_key: object) -> bool:
        key = str(session_key or "").strip()
        if not key:
            return False
        return self.get(key) is not None

    def __getitem__(self, session_key: str) -> dict:
        val = self.get(session_key)
        if val is None:
            raise KeyError(session_key)
        return val

    def __setitem__(self, session_key: str, value: dict) -> None:
        key = str(session_key or "").strip()
        if not key:
            return
        with self._lock:
            self._local[key] = value
        self._save_to_redis(key, value)

    def pop(self, session_key: str, default: Any = None) -> Any:
        key = str(session_key or "").strip()
        if not key:
            return default
        with self._lock:
            val = self._local.pop(key, default)
        if val is default and _redis.enabled:
            loaded = self._load_from_redis(key)
            if loaded is not None:
                val = loaded
        self._delete_from_redis(key)
        return val

    def persist(self, session_key: str) -> None:
        key = str(session_key or "").strip()
        if not key:
            return
        with self._lock:
            val = self._local.get(key)
        if isinstance(val, dict):
            self._save_to_redis(key, val)

    def keys(self) -> list[str]:
        with self._lock:
            local_keys = set(self._local.keys())
        if _redis.enabled:
            client = _redis._ensure()
            if client:
                try:
                    for raw in client.scan_iter(match=f"{self._prefix}*", count=200):
                        local_keys.add(str(raw)[len(self._prefix) :])
                except Exception:
                    pass
        return list(local_keys)

    def values(self) -> list[dict]:
        return [self.get(k) for k in self.keys() if isinstance(self.get(k), dict)]

    def items(self) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        for key in self.keys():
            val = self.get(key)
            if isinstance(val, dict):
                out.append((key, val))
        return out


_local_locks: dict[str, threading.Lock] = {}
_local_locks_guard = threading.Lock()


def _local_lock(session_key: str) -> threading.Lock:
    key = str(session_key or "").strip() or "default"
    with _local_locks_guard:
        lock = _local_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _local_locks[key] = lock
        return lock


def release_session_lock(session_key: str) -> None:
    key = str(session_key or "").strip()
    if not key:
        return
    with _local_locks_guard:
        _local_locks.pop(key, None)


@contextmanager
def session_lock(session_key: str, store: SessionStore | None = None) -> Iterator[threading.Lock]:
    """Per-session mutex; persists to Redis on exit when configured."""
    key = str(session_key or "").strip() or "default"
    lock = _acquire_distributed_lock(key)
    try:
        yield lock
    finally:
        if store is not None:
            store.persist(key)
        _release_distributed_lock(key, lock)


def _acquire_distributed_lock(session_key: str) -> threading.Lock:
    key = str(session_key or "").strip() or "default"
    if _redis.enabled:
        client = _redis._ensure()
        if client:
            token = f"{threading.get_ident()}:{time.time()}"
            lock_key = f"{_LOCK_PREFIX}{key}"
            deadline = time.time() + 30
            while time.time() < deadline:
                try:
                    if client.set(lock_key, token, nx=True, ex=45):
                        local = _local_lock(key)
                        local.acquire()
                        local._redis_token = token  # type: ignore[attr-defined]
                        local._redis_lock_key = lock_key  # type: ignore[attr-defined]
                        return local
                except Exception:
                    break
                time.sleep(0.05)
    local = _local_lock(key)
    local.acquire()
    return local


def _release_distributed_lock(session_key: str, lock: threading.Lock) -> None:
    key = str(session_key or "").strip() or "default"
    try:
        lock.release()
    except RuntimeError:
        pass
    token = getattr(lock, "_redis_token", None)
    lock_key = getattr(lock, "_redis_lock_key", None)
    if token and lock_key and _redis.enabled:
        client = _redis._ensure()
        if client:
            try:
                script = (
                    "if redis.call('get', KEYS[1]) == ARGV[1] then "
                    "return redis.call('del', KEYS[1]) else return 0 end"
                )
                client.eval(script, 1, lock_key, token)
            except Exception:
                pass
