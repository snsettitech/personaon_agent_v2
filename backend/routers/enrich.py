"""Background web enrichment for persona profiles."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from modules.auth_guard import require_tenant, verify_twin_ownership
from modules.graph_outbox import GraphOperationType, GraphOutbox
from modules.observability import get_supabase_client

logger = logging.getLogger(__name__)

router = APIRouter(tags=["enrich"])


class EnrichStartResponse(BaseModel):
    job_id: str
    status: str = "queued"


@router.post("/v2/enrich/{twin_id}/start", response_model=EnrichStartResponse)
async def start_enrichment(
    twin_id: str,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Enqueue a background web enrichment job for a twin.

    Searches the web for interviews, articles, and news about the person
    and adds new knowledge to the persona's Pinecone namespace.
    """
    verify_twin_ownership(twin_id, user)

    sb = get_supabase_client()
    resp = sb.table("twins").select("id, name, settings").eq("id", twin_id).single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Twin not found")

    twin = resp.data
    settings = twin.get("settings") or {}
    public_profile = settings.get("public_profile") or {}
    persona_profile = settings.get("persona_profile") or {}

    subject_name = (
        public_profile.get("name")
        or public_profile.get("display_name")
        or persona_profile.get("name")
        or twin.get("name", "")
    )
    organization = public_profile.get("organization", "")
    headline = public_profile.get("headline") or public_profile.get("occupation", "")
    bio = (
        public_profile.get("bio")
        or public_profile.get("short_description")
        or persona_profile.get("bio")
        or persona_profile.get("short_description")
        or ""
    )

    tenant_id = str(user.get("tenant_id") or "")

    outbox = GraphOutbox()
    job_id = outbox.submit(
        tenant_id=tenant_id,
        twin_id=twin_id,
        operation=GraphOperationType.ENRICH_FROM_WEB,
        idempotency_key=f"enrich_web:{twin_id}",
        payload={
            "subject_name": subject_name,
            "organization": organization,
            "headline": headline,
            "bio": bio[:500] if bio else "",
        },
        priority=1,
    )

    logger.info("[Enrich] Queued web enrichment job %s for twin %s", job_id, twin_id)
    return {"job_id": str(job_id), "status": "queued"}


@router.post("/v2/enrich/{twin_id}/profile", response_model=EnrichStartResponse)
async def reenrich_profile(
    twin_id: str,
    user: dict = Depends(require_tenant),
) -> dict[str, Any]:
    """Re-run Firecrawl profile enrichment for a twin.

    Enqueues a profile_enrichment training job identical to the one created
    during onboarding. Safe to call multiple times — the enrichment status is
    reset to 'queued' so callers can poll for completion.
    """
    from routers.auto_create import _enqueue_enrichment

    verify_twin_ownership(twin_id, user)

    sb = get_supabase_client()
    resp = sb.table("twins").select("id, name, settings").eq("id", twin_id).single().execute()
    if not resp.data:
        raise HTTPException(status_code=404, detail="Twin not found")

    twin = resp.data
    settings = dict(twin.get("settings") or {})
    public_profile = settings.get("public_profile") or {}
    persona_profile = settings.get("persona_profile") or {}
    social_links = public_profile.get("social_links") or {}

    name = (
        public_profile.get("display_name")
        or public_profile.get("name")
        or persona_profile.get("name")
        or twin.get("name", "")
    )
    headline = (
        public_profile.get("headline")
        or public_profile.get("role")
        or persona_profile.get("occupation")
        or ""
    )
    linkedin_url = social_links.get("linkedin") or None
    tenant_id = str(user.get("tenant_id") or "")

    # Reset enrichment_status so the frontend can poll for completion.
    settings["enrichment_status"] = "queued"
    settings["persona_quality"] = "enhancing"
    sb.table("twins").update({"settings": settings}).eq("id", twin_id).execute()

    _enqueue_enrichment(
        twin_id=twin_id,
        name=name,
        context=headline or None,
        linkedin_url=linkedin_url,
        linkedin_snapshot={},
        tenant_id=tenant_id,
    )

    logger.info("[Enrich] Re-queued profile enrichment for twin %s (name=%s)", twin_id, name)
    return {"job_id": twin_id, "status": "queued"}
