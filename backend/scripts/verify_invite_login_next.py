"""POST invite login then GET /next — smoke test for candidate startup."""

from __future__ import annotations

import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

BASE = "https://192.168.1.87:2020"
DEVICE = "verify-script-device-1"


def _ssl_ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _find_token() -> tuple[str, str] | tuple[None, None]:
    with psycopg2.connect(
        host="localhost", port=5432, dbname="karnex_db", user="postgres", password="root"
    ) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT invite_token, session_status, candidate_name, active_device_id
                FROM interview_schedule
                WHERE session_status IN ('pending', 'verified', 'active')
                  AND invite_token IS NOT NULL AND invite_token <> ''
                ORDER BY created_at_ist DESC NULLS LAST
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                return None, None
            print(
                "token",
                row["invite_token"],
                "status",
                row["session_status"],
                "name",
                row["candidate_name"],
                "device",
                row.get("active_device_id"),
            )
            device = str(row.get("active_device_id") or DEVICE)
            return str(row["invite_token"]), device


def main() -> int:
    token, device = _find_token()
    if not token:
        print("No invite token found in DB")
        return 0

    ctx = _ssl_ctx()
    login_req = urllib.request.Request(
        f"{BASE}/candidate/invite/{token}/login",
        data=b"",
        method="POST",
        headers={"x-device-id": device, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(login_req, context=ctx, timeout=90) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        print("login HTTP", exc.code, exc.read().decode()[:500])
        return 1

    print("login ok", "boot_reused", body.get("boot_reused"), "question_count", body.get("question_count"))
    access = str(body.get("access_token") or "")
    if not access:
        print("login missing access_token", body)
        return 1

    next_req = urllib.request.Request(
        f"{BASE}/next",
        method="GET",
        headers={"Authorization": f"Bearer {access}"},
    )
    try:
        with urllib.request.urlopen(next_req, context=ctx, timeout=45) as resp:
            nxt = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        print("/next HTTP", exc.code, exc.read().decode()[:500])
        return 1

    print("/next ok", "index", nxt.get("index"), "question", (nxt.get("question") or "")[:120])
    if nxt.get("error"):
        print("error", nxt["error"])
        return 1
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
