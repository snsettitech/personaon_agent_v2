"""HTTP-level proof for the desktop capture auth -> persist -> stop path.

This is the harness the State-of-Product assessment called for: it isolates
"is the BACKEND half of capture sound?" from "is the DESKTOP token handoff
broken?". It exercises the EXACT endpoints the desktop renderer calls, over
HTTP, with a real Supabase-shaped HS256 token minted from the local JWT secret
(byte-for-byte the same as a token Supabase issues), and asserts:

  POSITIVE (valid token):
    1. POST /segments          -> 200, only is_final rows persist
    2. GET  /segments          -> 200, rows come back ordered by seq
    3. PATCH /notes            -> 200, user notes saved
    4. POST /stop              -> 200, status flips, ENHANCE_NOTES enqueued
    5. POST /stop (again)      -> 200, idempotent no-op (stopped=false)

  NEGATIVE (the desktop bug's mechanism):
    6. POST /segments NO token       -> 401
    7. POST /segments EXPIRED token  -> 401   <- if the desktop sends a stale
                                                token, the backend 401s exactly
                                                like this. Proves WHY transcript
                                                stays empty on real desktop.

If POSITIVE all pass and NEGATIVE both 401, the backend is sound and the real
desktop failure is purely the renderer->main token handoff (getAccessToken
returning a missing/stale token). That is what P0 then fixes.

Usage:
  backend/.venv/Scripts/python.exe backend/scripts/_proof_desktop_capture_auth.py

print() is allowed here (scripts/). Hermetic: creates and deletes its own
meetings row + transcript segments + outbox job.
"""

from __future__ import annotations

import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_BACKEND_DIR / ".env", override=False)
load_dotenv(_BACKEND_DIR.parent / ".env", override=False)

import jwt  # noqa: E402
import requests  # noqa: E402

from modules.observability import supabase  # noqa: E402

API_BASE = os.getenv("PROOF_API_BASE", "http://127.0.0.1:8006").rstrip("/")
JWT_SECRET = os.getenv("JWT_SECRET") or os.getenv("SUPABASE_JWT_SECRET") or ""
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "authenticated")
TEST_EMAIL = os.getenv("PROOF_USER_EMAIL", "sai@sai.com")

_PASS = "[PASS]"
_FAIL = "[FAIL]"
_failures: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    mark = _PASS if ok else _FAIL
    print(f"  {mark} {label}" + (f" -- {detail}" if detail else ""))
    if not ok:
        _failures.append(label)


def _mint_token(user_id: str, *, expired: bool = False) -> str:
    now = datetime.now(timezone.utc)
    exp = now - timedelta(minutes=5) if expired else now + timedelta(hours=1)
    iat = now - timedelta(hours=2) if expired else now
    payload = {
        "sub": user_id,
        "email": TEST_EMAIL,
        "role": "authenticated",
        "aud": JWT_AUDIENCE,
        "iss": f"{os.getenv('SUPABASE_URL', '').rstrip('/')}/auth/v1",
        "iat": int(iat.timestamp()),
        "exp": int(exp.timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def _lookup_user_and_twin() -> tuple[str, str, str | None]:
    """Resolve (user_id, tenant_id, twin_id) for the test user from the DB."""
    urow = (
        supabase.table("users")
        .select("id, tenant_id")
        .eq("email", TEST_EMAIL)
        .limit(1)
        .execute()
        .data
    )
    if not urow:
        raise SystemExit(f"No public.users row for {TEST_EMAIL}; seed the local user first.")
    user_id = urow[0]["id"]
    tenant_id = urow[0]["tenant_id"]
    twrow = (
        supabase.table("twins")
        .select("id")
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
        .data
    )
    twin_id = twrow[0]["id"] if twrow else None
    return user_id, tenant_id, twin_id


def main() -> int:
    if not JWT_SECRET:
        raise SystemExit("JWT_SECRET not configured in backend/.env — cannot mint a token.")

    print(f"API_BASE={API_BASE}  user={TEST_EMAIL}  aud={JWT_AUDIENCE}")
    user_id, tenant_id, twin_id = _lookup_user_and_twin()
    print(f"user_id={user_id}\ntenant_id={tenant_id}\ntwin_id={twin_id}")

    token = _mint_token(user_id)
    auth = {"Authorization": f"Bearer {token}"}

    # --- setup: insert a hermetic recording row (only tenant_id is required) ---
    meeting_id = str(uuid.uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    supabase.table("meetings").insert({
        "id": meeting_id,
        "tenant_id": tenant_id,
        "twin_id": twin_id,
        "title": "AUTH PROOF — desktop capture",
        "status": "recording",
        "source": "desktop_sdk",
        "meeting_start": now_iso,
    }).execute()
    print(f"\nseeded meeting_id={meeting_id} status=recording\n")

    seg_url = f"{API_BASE}/v2/desktop-recordings/{meeting_id}/segments"
    notes_url = f"{API_BASE}/v2/desktop-recordings/{meeting_id}/notes"
    stop_url = f"{API_BASE}/v2/desktop-recordings/{meeting_id}/stop"

    try:
        # ============ POSITIVE PATH ============
        print("POSITIVE PATH (valid token):")

        # 1. POST segments — 2 final + 1 partial; only finals persist.
        seg_body = {"segments": [
            {"seq": 1, "speaker": "Sai", "text": "Let's lock the roadmap today.", "is_final": True, "start_ms": 1000},
            {"seq": 2, "speaker": "Maya", "text": "Shipping the editor by July.", "is_final": True, "start_ms": 8000},
            {"seq": 3, "speaker": "Sai", "text": "partial fragment...", "is_final": False, "start_ms": 12000},
        ]}
        r = requests.post(seg_url, json=seg_body, headers=auth, timeout=15)
        ok = r.status_code == 200 and r.json().get("data", {}).get("inserted") == 2
        _check("POST /segments -> 200, inserted=2 (partial dropped)", ok,
               f"status={r.status_code} body={r.text[:160]}")

        # 2. GET segments — ordered by seq, partial absent.
        r = requests.get(seg_url, headers=auth, timeout=15)
        items = r.json().get("data", {}).get("items", []) if r.status_code == 200 else []
        seqs = [it.get("seq") for it in items]
        ok = r.status_code == 200 and seqs == [1, 2]
        _check("GET /segments -> 200, persisted [1,2] in order", ok,
               f"status={r.status_code} seqs={seqs}")

        # 3. PATCH notes.
        r = requests.patch(notes_url, json={"user_notes_json": {"text": "roadmap sync - ship editor by July"}}, headers=auth, timeout=15)
        _check("PATCH /notes -> 200", r.status_code == 200, f"status={r.status_code} body={r.text[:160]}")

        # 4. POST stop — flips status, enqueues ENHANCE_NOTES.
        r = requests.post(stop_url, headers=auth, timeout=20)
        data = r.json().get("data", {}) if r.status_code == 200 else {}
        _check("POST /stop -> 200, stopped=true", r.status_code == 200 and data.get("stopped") is True,
               f"status={r.status_code} body={r.text[:200]}")

        # verify DB: status flipped + enhance job enqueued
        mrow = supabase.table("meetings").select("status, recap_stage, enhanced_notes_status").eq("id", meeting_id).single().execute().data
        _check("meetings.status flipped to processing/enhancing",
               mrow.get("status") == "processing" and mrow.get("recap_stage") == "enhancing",
               f"row={mrow}")
        job = (supabase.table("graph_outbox").select("operation, status")
               .eq("idempotency_key", f"enhance_notes:{meeting_id}").limit(1).execute().data)
        _check("ENHANCE_NOTES job enqueued (idempotency_key=enhance_notes:{id})", bool(job),
               f"job={job}")

        # 5. POST stop again — idempotent no-op.
        r = requests.post(stop_url, headers=auth, timeout=15)
        data = r.json().get("data", {}) if r.status_code == 200 else {}
        _check("POST /stop (again) -> 200, idempotent no-op (stopped=false)",
               r.status_code == 200 and data.get("stopped") is False,
               f"status={r.status_code} body={r.text[:160]}")

        # ============ NEGATIVE PATH (the desktop bug's mechanism) ============
        print("\nNEGATIVE PATH (auth failures the desktop hits):")

        # 6. No token -> 401.
        r = requests.post(seg_url, json=seg_body, timeout=15)
        _check("POST /segments NO token -> 401", r.status_code == 401, f"status={r.status_code}")

        # 7. Expired token -> 401 (this is EXACTLY what a stale desktop token does).
        expired = {"Authorization": f"Bearer {_mint_token(user_id, expired=True)}"}
        r = requests.post(seg_url, json=seg_body, headers=expired, timeout=15)
        _check("POST /segments EXPIRED token -> 401 (= stale desktop token)", r.status_code == 401,
               f"status={r.status_code}")

    finally:
        # --- teardown ---
        supabase.table("meeting_transcript_segments").delete().eq("meeting_id", meeting_id).execute()
        supabase.table("graph_outbox").delete().eq("idempotency_key", f"enhance_notes:{meeting_id}").execute()
        supabase.table("meetings").delete().eq("id", meeting_id).execute()
        print(f"\ncleaned up meeting_id={meeting_id}")

    print("\n" + "=" * 60)
    if _failures:
        print(f"RESULT: {len(_failures)} FAILED -> {_failures}")
        print("If POSITIVE failed: backend bug. If only NEGATIVE behaves wrong: auth-guard bug.")
        return 1
    print("RESULT: ALL PASSED -> backend capture+auth path is SOUND.")
    print("=> The empty-transcript bug is the DESKTOP token handoff, not the backend.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
