"""Admin: moderation — persona take-down/restore + lead inspection.

A twin is publicly accessible only when ``status == 'active'`` and
``settings.deleted_at`` is unset (see modules/share_links.has_public_twin_status).
Take-down therefore sets ``settings.deleted_at`` (the lever the public/marketplace
code already respects) plus ``is_active=False``, and records a moderation marker.
Restore clears both. Fully reversible; no data is destroyed.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from modules import admin_audit
from modules.auth_guard import require_admin, require_admin_write

from ._common import _safe_query, _supabase

logger = logging.getLogger(__name__)
router = APIRouter()

PUBLIC_STATUS = "active"


class TakedownRequest(BaseModel):
    reason: str | None = None


def _settings(twin: dict[str, Any]) -> dict[str, Any]:
    s = twin.get("settings")
    return s if isinstance(s, dict) else {}


def _is_public(twin: dict[str, Any]) -> bool:
    return str(twin.get("status") or "").lower() == PUBLIC_STATUS and not _settings(twin).get("deleted_at")


@router.get("/moderation/twins")
def list_personas(
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, le=300),
    user: dict = Depends(require_admin),
) -> list[dict[str, Any]]:
    """List personas with public-accessibility + take-down status."""
    sb = _supabase()
    query = (
        sb.table("twins")
        .select("id, tenant_id, name, status, is_active, settings, created_at, updated_at")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if status_filter:
        query = query.eq("status", status_filter)
    rows = _safe_query(query)
    return [
        {
            "id": t.get("id"),
            "tenant_id": t.get("tenant_id"),
            "name": t.get("name"),
            "status": t.get("status"),
            "is_active": t.get("is_active"),
            "public": _is_public(t),
            "taken_down": bool(_settings(t).get("moderation_takedown")),
            "created_at": t.get("created_at"),
        }
        for t in rows
    ]


@router.post("/twins/{twin_id}/takedown")
def takedown_persona(
    twin_id: str,
    body: TakedownRequest,
    user: dict = Depends(require_admin_write),
) -> dict[str, Any]:
    """Remove a persona from public/marketplace access (reversible). Audited."""
    sb = _supabase()
    rows = _safe_query(sb.table("twins").select("id, name, status, is_active, settings").eq("id", twin_id).limit(1))
    if not rows:
        raise HTTPException(status_code=404, detail="twin not found")
    twin = rows[0]
    now = datetime.now(timezone.utc).isoformat()
    new_settings = {
        **_settings(twin),
        "deleted_at": now,
        "moderation_takedown": {"at": now, "by": user.get("user_id"), "reason": body.reason},
    }
    sb.table("twins").update({"settings": new_settings, "is_active": False}).eq("id", twin_id).execute()
    admin_audit.record_admin_action(
        actor=user, action=admin_audit.ACTION_PERSONA_TAKEDOWN, target_type="twin", target_id=twin_id,
        before={"status": twin.get("status"), "is_active": twin.get("is_active")},
        after={"taken_down": True}, details={"reason": body.reason},
    )
    return {"status": "ok", "data": {"twin_id": twin_id, "taken_down": True}}


@router.post("/twins/{twin_id}/restore")
def restore_persona(twin_id: str, user: dict = Depends(require_admin_write)) -> dict[str, Any]:
    """Reverse a take-down: clear the moderation marker + deleted_at. Audited."""
    sb = _supabase()
    rows = _safe_query(sb.table("twins").select("id, settings").eq("id", twin_id).limit(1))
    if not rows:
        raise HTTPException(status_code=404, detail="twin not found")
    new_settings = {k: v for k, v in _settings(rows[0]).items() if k not in ("deleted_at", "moderation_takedown")}
    sb.table("twins").update({"settings": new_settings, "is_active": True}).eq("id", twin_id).execute()
    admin_audit.record_admin_action(
        actor=user, action=admin_audit.ACTION_PERSONA_RESTORED, target_type="twin",
        target_id=twin_id, after={"taken_down": False},
    )
    return {"status": "ok", "data": {"twin_id": twin_id, "taken_down": False}}


@router.get("/moderation/leads")
def list_leads(limit: int = Query(default=100, le=300), user: dict = Depends(require_admin)) -> list:
    """Recent captured leads for inspection."""
    sb = _supabase()
    return _safe_query(
        sb.table("widget_leads")
        .select("id, twin_id, visitor_name, visitor_email, source_domain, inferred_intent, created_at")
        .order("created_at", desc=True)
        .limit(limit)
    )


@router.get("/moderation/leads/export")
def export_leads(user: dict = Depends(require_admin)) -> Response:
    """Export captured leads as CSV (up to 5000 rows)."""
    sb = _supabase()
    rows = _safe_query(
        sb.table("widget_leads")
        .select("id, twin_id, visitor_name, visitor_email, source_domain, inferred_intent, created_at")
        .order("created_at", desc=True)
        .limit(5000)
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "twin_id", "visitor_name", "visitor_email", "source_domain", "inferred_intent", "created_at"])
    for r in rows:
        writer.writerow([
            r.get("id"), r.get("twin_id"), r.get("visitor_name"), r.get("visitor_email"),
            r.get("source_domain"), r.get("inferred_intent"), r.get("created_at"),
        ])
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=personaon-leads.csv"},
    )
