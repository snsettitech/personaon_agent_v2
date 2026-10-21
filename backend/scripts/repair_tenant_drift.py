#!/usr/bin/env python3
"""
Repair tenant drift for a twin that became orphaned or detached from an active owner tenant.

Usage (dry-run):
  python scripts/repair_tenant_drift.py --twin-id <TWIN_ID> --target-email <EMAIL>

Apply:
  python scripts/repair_tenant_drift.py --twin-id <TWIN_ID> --target-email <EMAIL> --apply

Behavior:
- Resolves target user by email (most recently active non-deleted user).
- Archives active name-conflicting twins in the target tenant.
- Moves target twin into the target tenant.
- Retags tenant-scoped tables (`owner_beliefs`, `clarification_threads`, `audit_logs`).
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import create_client


def _load_env() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    backend_root = Path(__file__).resolve().parents[1]
    load_dotenv(repo_root / ".env")
    load_dotenv(backend_root / ".env")


def _is_deleted_email(email: str) -> bool:
    value = (email or "").lower().strip()
    return value.startswith("deleted_") or value.endswith("@deleted.local")


def _pick_target_user(sb, email: str, user_id: str | None) -> dict[str, Any]:
    if user_id:
        user = sb.table("users").select("id,email,tenant_id,last_active_at,created_at").eq("id", user_id).single().execute().data
        if not user:
            raise RuntimeError(f"Target user_id not found: {user_id}")
        if not user.get("tenant_id"):
            raise RuntimeError(f"Target user has no tenant_id: {user_id}")
        return user

    rows = sb.table("users").select("id,email,tenant_id,last_active_at,created_at").eq("email", email).execute().data or []
    candidates = [r for r in rows if r.get("tenant_id") and not _is_deleted_email(r.get("email", ""))]
    if not candidates:
        raise RuntimeError(f"No active user row found for email: {email}")
    candidates.sort(key=lambda r: ((r.get("last_active_at") or ""), (r.get("created_at") or "")), reverse=True)
    return candidates[0]


def _summarize_twin(sb, twin_id: str) -> dict[str, Any]:
    twin = sb.table("twins").select("*").eq("id", twin_id).single().execute().data
    if not twin:
        raise RuntimeError(f"Twin not found: {twin_id}")
    settings = twin.get("settings") or {}

    def _count(table: str) -> int:
        return int(sb.table(table).select("id", count="exact").eq("twin_id", twin_id).limit(1).execute().count or 0)

    return {
        "id": twin["id"],
        "tenant_id": twin.get("tenant_id"),
        "name": twin.get("name"),
        "created_at": twin.get("created_at"),
        "deleted_at": settings.get("deleted_at") if isinstance(settings, dict) else None,
        "share_token": ((settings.get("widget_settings") or {}).get("share_token")) if isinstance(settings, dict) else None,
        "source_count": _count("sources"),
        "owner_memory_count": _count("owner_beliefs"),
        "conversation_count": _count("conversations"),
        "interview_sessions": _count("interview_sessions"),
    }


def _archive_conflict(sb, twin: dict[str, Any], actor_user_id: str, dry_run: bool, actions: list[dict[str, Any]]) -> None:
    now = datetime.now(timezone.utc).isoformat()
    settings = twin.get("settings") or {}
    ws = settings.get("widget_settings") or {}
    settings["deleted_at"] = now
    settings["deleted_by"] = actor_user_id
    settings["deleted_reason"] = "auto_archived_duplicate_during_tenant_drift_repair"
    settings["is_public"] = False
    ws["public_share_enabled"] = False
    ws.pop("share_token", None)
    ws.pop("share_token_expires_at", None)
    settings["widget_settings"] = ws

    payload = {"name": f"{twin['name']} (archived {now[:10]})", "settings": settings}
    actions.append({"archive_conflict_twin": {"id": twin["id"], "payload": payload}})
    if not dry_run:
        sb.table("twins").update(payload).eq("id", twin["id"]).execute()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--twin-id", required=True)
    parser.add_argument("--target-email", required=True)
    parser.add_argument("--target-user-id", required=False)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    _load_env()
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_KEY/SUPABASE_KEY")
    sb = create_client(url, key)

    dry_run = not args.apply
    actions: list[dict[str, Any]] = []

    target_user = _pick_target_user(sb, args.target_email, args.target_user_id)
    target_tenant_id = target_user["tenant_id"]

    twin = sb.table("twins").select("*").eq("id", args.twin_id).single().execute().data
    if not twin:
        raise RuntimeError(f"Twin not found: {args.twin_id}")

    source_tenant_id = twin["tenant_id"]
    twin_name = twin["name"]

    conflicts = (
        sb.table("twins")
        .select("*")
        .eq("tenant_id", target_tenant_id)
        .eq("name", twin_name)
        .execute()
        .data
        or []
    )
    conflicts = [row for row in conflicts if row["id"] != args.twin_id and not ((row.get("settings") or {}).get("deleted_at"))]

    for conflict in conflicts:
        _archive_conflict(sb, conflict, target_user["id"], dry_run, actions)

    if source_tenant_id != target_tenant_id:
        move_payload = {"tenant_id": target_tenant_id}
        actions.append(
            {
                "move_twin": {
                    "id": args.twin_id,
                    "from_tenant": source_tenant_id,
                    "to_tenant": target_tenant_id,
                    "payload": move_payload,
                }
            }
        )
        if not dry_run:
            sb.table("twins").update(move_payload).eq("id", args.twin_id).execute()

        for table in ("owner_beliefs", "clarification_threads", "audit_logs"):
            patch = {"tenant_id": target_tenant_id}
            actions.append({"retag_tenant": {"table": table, "patch": patch}})
            if not dry_run:
                sb.table(table).update(patch).eq("twin_id", args.twin_id).eq("tenant_id", source_tenant_id).execute()
    else:
        actions.append(
            {
                "noop": {
                    "reason": "Twin already belongs to target tenant",
                    "twin_id": args.twin_id,
                    "tenant_id": target_tenant_id,
                }
            }
        )

    output = {
        "mode": "apply" if args.apply else "dry_run",
        "target_user": target_user,
        "before": _summarize_twin(sb, args.twin_id),
        "actions": actions,
        "after": _summarize_twin(sb, args.twin_id) if args.apply else None,
    }
    print(json.dumps(output, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
