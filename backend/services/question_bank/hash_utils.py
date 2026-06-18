from __future__ import annotations

import hashlib


def question_hash(text: str) -> str:
    """Stable SHA-256 hex digest for deduplicating question text."""
    normalized = " ".join(str(text or "").strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
