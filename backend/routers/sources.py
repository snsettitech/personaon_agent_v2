import logging
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from modules.auth_guard import verify_owner, get_current_user, verify_twin_ownership

logger = logging.getLogger(__name__)
from modules.observability import supabase
from modules.ingestion import delete_source
from modules.training_jobs import create_training_job
from modules.ingestion import detect_url_provider
from modules.ingestion_diagnostics import diagnostics_schema_status

router = APIRouter(tags=["sources"])

def _normalize_source(source: dict):
    if not source:
        return source
    status = source.get("status")
    if status == "approved":
        source["status"] = "live"
    elif status in ("staged", "training"):
        source["status"] = "processing"
    source.pop("staging_status", None)
    return source


@router.get("/sources/{twin_id}")
async def list_sources(twin_id: str, status: str | None = None, user=Depends(get_current_user)):
    """
    List all sources for a twin.
    Optional status filter: 'processing', 'processed', 'error', 'live'
    """
    # Verify user has access to this twin
    verify_twin_ownership(twin_id, user)

    try:
        query = supabase.table("sources").select("*").eq("twin_id", twin_id).order("created_at", desc=True)

        if status:
            query = query.eq("status", status)

        response = query.execute()
        data = response.data or []
        return [_normalize_source(item) for item in data]
    except Exception as e:
        logger.warning("Error listing sources: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/twins/{twin_id}/sources")
async def list_sources_twin_alias(twin_id: str, status: str | None = None, user=Depends(get_current_user)):
    """
    Compatibility alias for twin-scoped frontend clients.

    Canonical route remains GET /sources/{twin_id}.
    """
    return await list_sources(twin_id=twin_id, status=status, user=user)


_DOCUMENT_EXTENSIONS = (".pdf", ".docx", ".xlsx", ".txt", ".md", ".csv", ".json")


def _infer_source_type(source: dict) -> str:
    """Derive source_type from filename prefix, extension, and citation_url."""
    fn = (source.get("filename") or "").strip()
    fn_lower = fn.lower()
    if fn.startswith("YouTube:"):
        return "youtube"
    if fn.startswith("Podcast:"):
        return "podcast"
    if fn.startswith("X:") or fn.startswith("X Thread:"):
        return "x_thread"
    if any(fn_lower.endswith(ext) for ext in _DOCUMENT_EXTENSIONS):
        return "document"
    if source.get("citation_url"):
        return "web"
    return "document"


@router.get("/sources/{twin_id}/grouped")
async def list_sources_grouped(twin_id: str, user=Depends(get_current_user)):
    """Return sources grouped by source_type for the Knowledge Source Explorer."""
    verify_twin_ownership(twin_id, user)

    try:
        query = (
            supabase.table("sources")
            .select(
                "id, twin_id, filename, file_size, status, created_at, "
                "citation_url, file_url, chunk_count, last_event_at, health_status"
            )
            .eq("twin_id", twin_id)
            .neq("status", "deleted")
            .order("created_at", desc=True)
        )
        response = query.execute()
        data = response.data or []

        groups: dict[str, list] = {}
        for item in data:
            st = _infer_source_type(item)
            item["source_type"] = st
            _normalize_source(item)
            groups.setdefault(st, []).append(item)

        # Inject synthetic profile entry if persona_profile exists
        twin_res = (
            supabase.table("twins")
            .select("settings, created_at")
            .eq("id", twin_id)
            .single()
            .execute()
        )
        if twin_res.data:
            profile = (twin_res.data.get("settings") or {}).get("persona_profile")
            if profile:
                groups.setdefault("profile", []).append({
                    "id": f"profile-{twin_id}",
                    "filename": "Persona Profile (auto-generated)",
                    "source_type": "profile",
                    "status": "live",
                    "created_at": twin_res.data.get("created_at"),
                    "file_size": 0,
                    "chunk_count": None,
                    "citation_url": None,
                    "file_url": None,
                    "last_event_at": None,
                    "health_status": "healthy",
                })

        return {"status": "ok", "data": groups}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[sources] grouped listing failed twin_id=%s", twin_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources/{source_id}/health")
async def get_source_health(source_id: str, user=Depends(get_current_user)):
    """Get health check results for a source."""
    try:
        # First get source to verify ownership
        source = supabase.table("sources").select("twin_id, health_status").eq("id", source_id).single().execute()
        if not source.data:
            raise HTTPException(status_code=404, detail="Source not found")

        # Verify user owns this twin
        verify_twin_ownership(source.data["twin_id"], user)

        # Get health checks from ingestion_logs
        response = supabase.table("ingestion_logs").select("*").eq("source_id", source_id).order("created_at", desc=True).limit(20).execute()
        logs = response.data or []
        checks = [
            {
                "id": log.get("id"),
                "check_type": "ingestion_log",
                "status": log.get("log_level", "info"),
                "message": log.get("message"),
                "metadata": log.get("metadata"),
                "created_at": log.get("created_at")
            }
            for log in logs
        ]

        return {
            "health_status": source.data.get("health_status"),
            "logs": logs,
            "checks": checks
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Error getting source health: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/sources/{twin_id}/{source_id}")
async def delete_source_endpoint(twin_id: str, source_id: str, user=Depends(verify_owner)):
    """Delete a source and its associated vectors."""
    try:
        await delete_source(source_id, twin_id)
        return {"status": "success", "message": "Source deleted"}
    except Exception as e:
        logger.warning("Error deleting source: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources/{source_id}/logs")
async def get_source_logs(source_id: str, user=Depends(get_current_user)):
    """Get ingestion logs for a source."""
    try:
        # First get source to verify ownership
        source = supabase.table("sources").select("twin_id").eq("id", source_id).single().execute()
        if not source.data:
            raise HTTPException(status_code=404, detail="Source not found")

        # Verify user owns this twin
        verify_twin_ownership(source.data["twin_id"], user)

        response = supabase.table("ingestion_logs").select("*").eq("source_id", source_id).order("created_at", desc=True).limit(50).execute()
        return response.data or []
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Error getting source logs: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/sources/{source_id}/events")
async def get_source_events(source_id: str, user=Depends(get_current_user)):
    """Get step timeline events for a source."""
    try:
        source = supabase.table("sources").select("twin_id").eq("id", source_id).single().execute()
        if not source.data:
            raise HTTPException(status_code=404, detail="Source not found")

        verify_twin_ownership(source.data["twin_id"], user)

        res = supabase.table("source_events").select("*").eq("source_id", source_id).order("created_at", desc=False).limit(200).execute()
        return res.data or []
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Error getting source events: %s", e)
        msg = str(e)
        if "source_events" in msg and ("schema cache" in msg or "PGRST205" in msg):
            raise HTTPException(
                status_code=503,
                detail=(
                    "Ingestion diagnostics schema is not installed (missing source_events/last_error columns). "
                    "Apply backend/database/migrations/20260207_ingestion_diagnostics.sql in Supabase SQL editor, "
                    "then redeploy/restart the backend."
                ),
            )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sources/{source_id}/re-extract")
async def re_extract_source(source_id: str, user=Depends(verify_owner)):
    """Compatibility shim: re-queue processing for a source (use /sources/{source_id}/retry)."""
    try:
        # Delegate to the canonical retry logic.
        return await retry_source(source_id, user)
    except Exception as e:
        logger.warning("Error re-extracting source: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sources/{source_id}/retry")
async def retry_source(source_id: str, user=Depends(verify_owner)):
    """
    Retry ingestion/indexing for a source.

    - If `citation_url` exists, re-runs URL ingestion.
    - Otherwise, re-runs indexing over existing `content_text`.
    """
    try:
        source_res = supabase.table("sources").select("id, twin_id, citation_url, content_text").eq("id", source_id).single().execute()
        if not source_res.data:
            raise HTTPException(status_code=404, detail="Source not found")

        twin_id = source_res.data["twin_id"]
        verify_twin_ownership(twin_id, user)

        citation_url = source_res.data.get("citation_url")
        provider = detect_url_provider(citation_url) if citation_url else "file"

        # Clear last error and reset status to queued/pending. Diagnostics fields are best-effort
        # and may not exist until the migration is applied.
        update = {
            "status": "pending",
            "staging_status": "staged",
            "health_status": "healthy",
        }
        available, _err = diagnostics_schema_status()
        if available:
            update.update(
                {
                    "last_error": None,
                    "last_error_at": None,
                    "last_provider": provider,
                    "last_step": "queued",
                    "last_event_at": None,
                }
            )
        try:
            supabase.table("sources").update(update).eq("id", source_id).execute()
        except Exception as e:
            # If some deployments have staging_status removed, retry without it.
            msg = str(e)
            if "staging_status" in msg:
                update.pop("staging_status", None)
                supabase.table("sources").update(update).eq("id", source_id).execute()
            else:
                raise

        job_id = create_training_job(
            source_id=source_id,
            twin_id=twin_id,
            job_type="ingestion",
            priority=0,
            metadata={
                "provider": provider,
                "url": citation_url,
                "ingest_mode": "retry",
            }
        )

        return {"status": "queued", "source_id": source_id, "job_id": job_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Error retrying source %s: %s", source_id, e)
        raise HTTPException(status_code=500, detail=str(e))


class SourcePatchRequest(BaseModel):
    filename: str | None = None


@router.patch("/sources/{source_id}")
async def patch_source(source_id: str, body: SourcePatchRequest, user=Depends(get_current_user)):
    """Partial update: rename filename and/or assign a custom folder."""
    try:
        src = supabase.table("sources").select("twin_id").eq("id", source_id).single().execute()
        if not src.data:
            raise HTTPException(status_code=404, detail="Source not found")

        verify_twin_ownership(src.data["twin_id"], user)

        payload: dict = {}
        if "filename" in body.model_fields_set:
            name = (body.filename or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="filename cannot be empty")
            payload["filename"] = name
        if not payload:
            raise HTTPException(status_code=400, detail="No updatable fields provided")

        updated = supabase.table("sources").update(payload).eq("id", source_id).execute()
        if not updated.data:
            raise HTTPException(status_code=404, detail="Source not found after update")

        data = _normalize_source(updated.data[0])
        data["source_type"] = _infer_source_type(data)
        return {"status": "ok", "data": data}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[sources] patch failed source_id=%s", source_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources/{twin_id}/{source_id}/chunks")
async def get_source_chunks(twin_id: str, source_id: str, user=Depends(get_current_user)):
    """Return text content of all chunks for a source, ordered by creation time."""
    verify_twin_ownership(twin_id, user)
    try:
        response = (
            supabase.table("chunks")
            .select("id, content, privacy_level, created_at")
            .eq("source_id", source_id)
            .eq("twin_id", twin_id)
            .order("created_at")
            .execute()
        )
        return {"status": "ok", "data": response.data or []}
    except Exception as e:
        logger.exception("[sources] get_source_chunks failed source_id=%s", source_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sources/{twin_id}/{source_id}")
async def get_source(twin_id: str, source_id: str, user=Depends(get_current_user)):
    """
    Get a specific source with its details.

    NOTE: This route is intentionally declared after /sources/{source_id}/events|logs
    so diagnostics endpoints are not shadowed by the dual-param path.
    """
    verify_twin_ownership(twin_id, user)

    try:
        response = supabase.table("sources").select("*").eq("id", source_id).eq("twin_id", twin_id).single().execute()

        if not response.data:
            raise HTTPException(status_code=404, detail="Source not found")

        return _normalize_source(response.data)
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("Error getting source: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
