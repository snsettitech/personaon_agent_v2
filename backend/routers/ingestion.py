import json
import logging
import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Request, status
from pydantic import BaseModel

from modules.auth_guard import verify_owner, get_current_user, verify_twin_ownership, verify_source_ownership
from modules.health_checks import calculate_content_hash, run_all_health_checks
from modules.ingestion import detect_url_provider, extract_text_from_docx, extract_text_from_excel, extract_text_from_pdf
from modules.ingestion_diagnostics import start_step, finish_step
from modules.ingestion_identity import (
    enrich_profile_from_resume as _enrich_profile_from_resume,
    persist_source_label_metadata as _persist_source_label_metadata,
    propose_claims_for_duplicate_identity as _propose_claims_for_duplicate_identity,
)
from modules.ingestion_url import validate_url_for_ingestion
from modules.job_queue import enqueue_job
from modules.observability import supabase, log_ingestion_event
from modules.training_jobs import create_training_job, get_training_job, process_training_queue, list_training_jobs
from routers.twins_helpers import _is_missing_column_error
import contextlib

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ingestion"])

# =============================================================================
# SECURITY: FILE SIZE LIMITS (CRITICAL BUG FIX)
# =============================================================================

# Max file size: 50MB (configurable via environment)
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024

# Allowed file extensions
ALLOWED_EXTENSIONS = {
    '.pdf': 'PDF document',
    '.docx': 'Word document',
    '.xlsx': 'Excel spreadsheet',
    '.txt': 'Text file',
    '.md': 'Markdown file',
    '.csv': 'CSV file',
    '.json': 'JSON file',
}

ALLOWED_SOURCE_LABELS = {"identity", "knowledge", "policies"}


def _insert_source_with_schema_fallback(payload: dict) -> None:
    """
    Insert into sources table with backward-compatible column fallback.

    Some environments may not yet include newer optional columns.
    """
    mutable_payload = dict(payload)
    removable_columns = [
        "staging_status",
        "health_status",
        "extracted_text_length",
        "content_hash",
        "citation_url",
    ]

    while True:
        try:
            supabase.table("sources").insert(mutable_payload).execute()
            return
        except Exception as insert_error:
            removed = None
            for column in removable_columns:
                if column in mutable_payload and _is_missing_column_error(insert_error, column):
                    removed = column
                    break

            if removed:
                mutable_payload.pop(removed, None)
                continue

            raise


def _validate_file_size(content_length: int) -> None:
    """
    Validate file size before processing.

    Args:
        content_length: File size in bytes

    Raises:
        HTTPException: If file exceeds size limit
    """
    if content_length > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE_MB}MB. "
                   f"Received {content_length / (1024*1024):.1f}MB."
        )


def _validate_file_extension(filename: str) -> None:
    """
    Validate file extension is allowed.

    Args:
        filename: Name of the file

    Raises:
        HTTPException: If extension not allowed
    """
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"File type '{ext}' not supported. Allowed: {', '.join(ALLOWED_EXTENSIONS.keys())}"
        )

class YouTubeIngestRequest(BaseModel):
    url: str

class PodcastIngestRequest(BaseModel):
    url: str

class XThreadIngestRequest(BaseModel):
    url: str

class URLIngestRequest(BaseModel):
    url: str
    source_label: str | None = None
    identity_confirmed: bool | None = False

class URLIngestWithTwinRequest(BaseModel):
    url: str
    twin_id: str
    source_label: str | None = None
    identity_confirmed: bool | None = False


class IngestTextRequest(BaseModel):
    twin_id: str
    content: str
    source_type: str = "manual"
    source_id: str | None = None
    metadata: dict | None = {}

def _get_correlation_id(request: Request) -> str | None:
    return request.headers.get("x-correlation-id") or request.headers.get("x-request-id")

def _normalize_source_label(label: str | None) -> str | None:
    if not isinstance(label, str):
        return None
    normalized = label.strip().lower()
    if normalized in ALLOWED_SOURCE_LABELS:
        return normalized
    return None


def _validate_source_label(
    source_label: str | None,
    identity_confirmed: bool | None,
) -> str | None:
    normalized = _normalize_source_label(source_label)
    if not normalized:
        if not source_label:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"source_label is required. Allowed values: {', '.join(sorted(ALLOWED_SOURCE_LABELS))}",
            )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid source_label. Allowed values: {', '.join(sorted(ALLOWED_SOURCE_LABELS))}",
        )
    if normalized == "identity" and not bool(identity_confirmed):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Identity sources require identity_confirmed=true",
        )
    return normalized


def _insert_source_row(
    *,
    source_id: str,
    twin_id: str,
    provider: str,
    filename: str,
    citation_url: str | None = None,
    source_label: str | None = None,
    identity_confirmed: bool | None = False,
):
    # Keep insert minimal and safe; later steps will update content_text, hashes, etc.
    _insert_source_with_schema_fallback({
        "id": source_id,
        "twin_id": twin_id,
        "filename": filename,
        "file_size": 0,
        "content_text": "",
        "status": "pending",
        "staging_status": "staged",
        "health_status": "healthy",
        "citation_url": citation_url,
    })
    _persist_source_label_metadata(
        source_id=source_id,
        twin_id=twin_id,
        source_label=source_label,
        identity_confirmed=identity_confirmed,
    )


def _persist_source_metadata(source_id: str, metadata: dict | None) -> None:
    if not isinstance(metadata, dict) or not metadata:
        return
    try:
        existing = supabase.table("sources").select("metadata").eq("id", source_id).single().execute()
        merged = {}
        if existing.data and isinstance(existing.data.get("metadata"), dict):
            merged = dict(existing.data["metadata"])
        merged.update(metadata)
        supabase.table("sources").update({"metadata": merged}).eq("id", source_id).execute()
    except Exception:
        pass

def _queue_ingestion_job(*, source_id: str, twin_id: str, provider: str, url: str | None, correlation_id: str | None) -> str:
    return create_training_job(
        source_id=source_id,
        twin_id=twin_id,
        job_type="ingestion",
        priority=0,
        metadata={
            "provider": provider,
            "url": url,
            "correlation_id": correlation_id,
            "ingest_mode": "ingest",
        }
    )

@router.post("/ingest/youtube/{twin_id}")
async def ingest_youtube(twin_id: str, request: YouTubeIngestRequest, http_req: Request, user=Depends(verify_owner)):
    # SECURITY: Verify user owns this twin before ingesting content
    verify_twin_ownership(twin_id, user)
    try:
        source_id = str(uuid.uuid4())
        provider = "youtube"
        _insert_source_row(
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            filename="YouTube: queued",
            citation_url=request.url,
        )
        corr = _get_correlation_id(http_req)
        ev = start_step(source_id=source_id, twin_id=twin_id, provider=provider, step="queued", correlation_id=corr)
        finish_step(event_id=ev, source_id=source_id, twin_id=twin_id, provider=provider, step="queued", status="completed", correlation_id=corr)
        job_id = _queue_ingestion_job(source_id=source_id, twin_id=twin_id, provider=provider, url=request.url, correlation_id=corr)
        return {"source_id": source_id, "job_id": job_id, "status": "pending"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/ingest/podcast/{twin_id}")
async def ingest_podcast(twin_id: str, request: PodcastIngestRequest, http_req: Request, user=Depends(verify_owner)):
    # SECURITY: Verify user owns this twin before ingesting content
    verify_twin_ownership(twin_id, user)
    try:
        source_id = str(uuid.uuid4())
        provider = "podcast"
        _insert_source_row(
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            filename="Podcast: queued",
            citation_url=request.url,
        )
        corr = _get_correlation_id(http_req)
        ev = start_step(source_id=source_id, twin_id=twin_id, provider=provider, step="queued", correlation_id=corr)
        finish_step(event_id=ev, source_id=source_id, twin_id=twin_id, provider=provider, step="queued", status="completed", correlation_id=corr)
        job_id = _queue_ingestion_job(source_id=source_id, twin_id=twin_id, provider=provider, url=request.url, correlation_id=corr)
        return {"source_id": source_id, "job_id": job_id, "status": "pending"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/ingest/x/{twin_id}")
async def ingest_x(twin_id: str, request: XThreadIngestRequest, http_req: Request, user=Depends(verify_owner)):
    # SECURITY: Verify user owns this twin before ingesting content
    verify_twin_ownership(twin_id, user)
    try:
        source_id = str(uuid.uuid4())
        provider = "x"
        _insert_source_row(
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            filename="X: queued",
            citation_url=request.url,
        )
        corr = _get_correlation_id(http_req)
        ev = start_step(source_id=source_id, twin_id=twin_id, provider=provider, step="queued", correlation_id=corr)
        finish_step(event_id=ev, source_id=source_id, twin_id=twin_id, provider=provider, step="queued", status="completed", correlation_id=corr)
        job_id = _queue_ingestion_job(source_id=source_id, twin_id=twin_id, provider=provider, url=request.url, correlation_id=corr)
        return {"source_id": source_id, "job_id": job_id, "status": "pending"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/ingest/file/{twin_id}")
async def ingest_file_endpoint(
    twin_id: str,
    file: UploadFile = File(...),
    source_label: str | None = Form(None),
    identity_confirmed: bool | None = Form(False),
    http_req: Request = None,
    user=Depends(verify_owner)
):
    """
    Ingest a file for the specified twin.

    Args:
        twin_id: Owner twin ID
        file: The file to upload
        Note: uploads are auto-indexed.

    Security:
        - Max file size: 50MB (configurable via MAX_FILE_SIZE_MB env var)
        - Only allowed file extensions
        - Content validated before processing

    Deduplication:
        - Content hash (SHA-256) is calculated after text extraction
        - If identical content exists for this twin, returns existing source
        - Prevents duplicate vectors and wasted processing
    """
    # SECURITY: Verify user owns this twin before ingesting content
    verify_twin_ownership(twin_id, user)
    normalized_label = _validate_source_label(source_label, identity_confirmed)

    temp_file_path = None
    try:
        provider = "file"
        corr = _get_correlation_id(http_req) if http_req else None
        filename = file.filename or "upload"

        # Step 0: Validate file extension
        _validate_file_extension(filename)
        file_extension = os.path.splitext(filename)[1]

        # Step 1: Read file content with size validation
        # Cache content_type before read — Starlette clears it after await
        file_content_type = file.content_type or "application/octet-stream"
        content = await file.read()
        _validate_file_size(len(content))

        # Step 2: Save uploaded file temporarily for extraction
        temp_dir = "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)
        temp_filename = f"temp_{uuid.uuid4()}{file_extension}"
        temp_file_path = os.path.join(temp_dir, temp_filename)

        with open(temp_file_path, "wb") as f:
            f.write(content)

        # Step 2: Extract text
        text = ""
        try:
            if temp_file_path.endswith(".pdf"):
                text = extract_text_from_pdf(temp_file_path)
            elif temp_file_path.endswith(".docx"):
                text = extract_text_from_docx(temp_file_path)
            elif temp_file_path.endswith(".xlsx"):
                text = extract_text_from_excel(temp_file_path)
            else:
                with open(temp_file_path, encoding="utf-8", errors="ignore") as f:
                    text = f.read()
        except Exception as extract_error:
            raise HTTPException(
                status_code=400,
                detail=f"Failed to extract text from file: {str(extract_error)}"
            )

        if not text or len(text.strip()) == 0:
            raise HTTPException(
                status_code=400,
                detail="File uploaded but no text could be extracted. Try a different file or export as PDF with selectable text."
            )

        # Step 3: Calculate content hash for deduplication
        content_hash = calculate_content_hash(text)

        # Step 4: Check for existing duplicate by content hash
        existing_source = supabase.table("sources").select("id, status, content_hash, content_text") \
            .eq("twin_id", twin_id) \
            .eq("content_hash", content_hash) \
            .execute()

        if existing_source.data and len(existing_source.data) > 0:
            # Duplicate detected - clean up and return existing
            existing = existing_source.data[0]

            # Log deduplication event
            log_ingestion_event(
                existing["id"],
                twin_id,
                "info",
                "Duplicate file detected by hash. Returning existing source.",
                metadata={"original_filename": filename, "existing_source_id": existing["id"]}
            )

            duplicate_response = {
                "source_id": existing["id"],
                "job_id": None,
                "status": existing.get("status", "live"),
                "duplicate": True,
                "message": "This file has already been uploaded. Returning existing source."
            }
            if normalized_label == "identity":
                duplicate_response["proposed_count"] = await _propose_claims_for_duplicate_identity(
                    existing=existing,
                    twin_id=twin_id,
                    extracted_text=text,
                    identity_confirmed=identity_confirmed,
                    user=user,
                    correlation_id=corr,
                )
            return duplicate_response

        # Step 5: No duplicate - create new source
        source_id = str(uuid.uuid4())

        _insert_source_with_schema_fallback({
            "id": source_id,
            "twin_id": twin_id,
            "filename": filename,
            "file_size": len(content),
            "content_text": text,
            "content_hash": content_hash,
            "status": "processing",
            "staging_status": "staged",
            "health_status": "healthy",
            "extracted_text_length": len(text),
        })

        _persist_source_label_metadata(
            source_id=source_id,
            twin_id=twin_id,
            source_label=normalized_label,
            identity_confirmed=identity_confirmed,
        )

        # Log creation event
        ev_q = start_step(source_id=source_id, twin_id=twin_id, provider=provider, step="queued", correlation_id=corr)
        finish_step(event_id=ev_q, source_id=source_id, twin_id=twin_id, provider=provider, step="queued", status="completed", correlation_id=corr)

        # Run health checks
        ev_p = start_step(source_id=source_id, twin_id=twin_id, provider=provider, step="parsed", correlation_id=corr)
        health = run_all_health_checks(
            source_id,
            twin_id,
            text,
            source_data={"filename": filename, "twin_id": twin_id}
        )
        try:
            supabase.table("sources").update({
                "health_status": health.get("overall_status", "healthy")
            }).eq("id", source_id).execute()
        except Exception as health_update_error:
            if not _is_missing_column_error(health_update_error, "health_status"):
                raise

        finish_step(event_id=ev_p, source_id=source_id, twin_id=twin_id, provider=provider, step="parsed", status="completed", correlation_id=corr, metadata={"text_len": len(text)})

        # Embed inline — no worker dependency.
        # User-uploaded documents may contain internal/sensitive material, so
        # tag as `team` by default: excluded from marketplace global search,
        # still visible to the twin owner and in their own meeting context.
        from adk_core.services.vector_store import upsert_text_chunks
        chunk_count = await upsert_text_chunks(
            text=text,
            twin_id=twin_id,
            source=filename,
            source_id=source_id,
            privacy_level="team",
        )

        # If this is an identity document (resume/CV), propose Passport claims (PON-8).
        # Never silently approve into persona_profile / public_profile.
        proposed_count: int | None = None
        if normalized_label == "identity":
            _tenant = user.get("tenant_id") if isinstance(user, dict) else None
            proposed_count = await _enrich_profile_from_resume(
                twin_id,
                text,
                source_id=source_id,
                tenant_id=_tenant,
                correlation_id=corr,
            )

        # Mark source as live and record chunk count
        try:
            supabase.table("sources").update({
                "status": "live",
                "chunk_count": chunk_count,
                "last_step": "indexed",
            }).eq("id", source_id).execute()
        except Exception:
            pass  # status column may not exist in older schemas

        # GCS upload — fire-and-forget, non-blocking
        _tenant_id = user.get("tenant_id", "unknown") if isinstance(user, dict) else "unknown"
        _gcs_source_id = source_id
        _gcs_content = content
        _gcs_filename = filename
        _gcs_twin_id = twin_id
        _gcs_content_type = file_content_type

        import asyncio as _asyncio

        async def _gcs_upload_task() -> None:
            try:
                from modules.gcs_storage import upload_file_bytes
                loop = _asyncio.get_event_loop()
                gcs_uri = await loop.run_in_executor(
                    None,
                    lambda: upload_file_bytes(
                        file_bytes=_gcs_content,
                        tenant_id=_tenant_id,
                        twin_id=_gcs_twin_id,
                        source_id=_gcs_source_id,
                        filename=_gcs_filename,
                        content_type=_gcs_content_type,
                    ),
                )
                supabase.table("sources").update({"file_url": gcs_uri}).eq("id", _gcs_source_id).execute()
            except Exception as _gcs_err:
                logger.error("[GCS] upload failed for source %s (non-fatal): %s", _gcs_source_id, _gcs_err)

        _asyncio.create_task(_gcs_upload_task())

        response = {
            "source_id": source_id,
            "job_id": None,
            "status": "live",
            "duplicate": False,
            "chunks": chunk_count,
        }
        if proposed_count is not None:
            response["proposed_count"] = proposed_count
        return response

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # Clean up temp file
        if temp_file_path and os.path.exists(temp_file_path):
            with contextlib.suppress(Exception):
                os.remove(temp_file_path)

@router.get("/sources/{source_id}/download-url")
async def get_source_download_url(source_id: str, user=Depends(verify_owner)) -> dict:
    """Return a short-lived signed URL for a privately stored GCS file."""
    from modules.gcs_storage import generate_signed_url
    row = supabase.table("sources").select("id, twin_id, file_url").eq("id", source_id).single().execute()
    if not row.data:
        raise HTTPException(status_code=404, detail="Source not found")
    verify_twin_ownership(row.data["twin_id"], user)
    gcs_uri = row.data.get("file_url") or ""
    if not gcs_uri.startswith("gs://"):
        raise HTTPException(status_code=404, detail="No file stored for this source")
    try:
        signed_url = generate_signed_url(gcs_uri, expiration_seconds=3600)
    except Exception as e:
        logger.error("[GCS] signed URL generation failed for source %s: %s", source_id, e)
        raise HTTPException(status_code=502, detail="Could not generate download URL")
    return {"download_url": signed_url, "expires_in": 3600}


@router.post("/ingest/url/{twin_id}")
async def ingest_url_endpoint(twin_id: str, request: URLIngestRequest, http_req: Request, user=Depends(verify_owner)):
    """Ingest content from URL - auto-detects type (YouTube, X, Podcast, or generic page)."""
    # SECURITY: Verify user owns this twin before ingesting content
    verify_twin_ownership(twin_id, user)
    normalized_label = _validate_source_label(request.source_label, request.identity_confirmed)
    try:
        url = request.url.strip()
        validate_url_for_ingestion(url)
        provider = detect_url_provider(url)
        source_id = str(uuid.uuid4())
        _insert_source_row(
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            filename=f"{provider.upper()}: queued",
            citation_url=url,
            source_label=normalized_label,
            identity_confirmed=request.identity_confirmed,
        )
        corr = _get_correlation_id(http_req)
        ev = start_step(source_id=source_id, twin_id=twin_id, provider=provider, step="queued", correlation_id=corr)
        finish_step(event_id=ev, source_id=source_id, twin_id=twin_id, provider=provider, step="queued", status="completed", correlation_id=corr)
        job_id = _queue_ingestion_job(source_id=source_id, twin_id=twin_id, provider=provider, url=url, correlation_id=corr)
        return {"source_id": source_id, "job_id": job_id, "status": "pending"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ---------------------------------------------------------------------------
# Compatibility shims (Phase 2)
# ---------------------------------------------------------------------------

@router.post(
    "/ingest",
    include_in_schema=True,
    summary="Ingest raw text content into a twin's knowledge base",
)
async def ingest_text(
    request: IngestTextRequest,
    user=Depends(verify_owner),
):
    verify_twin_ownership(request.twin_id, user)
    content = (request.content or "").strip()
    if not content:
        raise HTTPException(status_code=422, detail="content is required")

    content_hash = calculate_content_hash(content)
    existing_source = (
        supabase.table("sources")
        .select("id, status, content_hash")
        .eq("twin_id", request.twin_id)
        .eq("content_hash", content_hash)
        .execute()
    )
    if existing_source.data:
        existing = existing_source.data[0]
        return {
            "source_id": existing["id"],
            "job_id": None,
            "status": existing.get("status", "live"),
            "duplicate": True,
            "message": "This content has already been uploaded. Returning existing source.",
        }

    internal_source_id = str(uuid.uuid4())
    external_source_id = request.source_id or internal_source_id
    _insert_source_with_schema_fallback({
        "id": internal_source_id,
        "twin_id": request.twin_id,
        "filename": f"{request.source_type or 'manual'}.txt",
        "file_size": len(content.encode("utf-8")),
        "content_text": content,
        "content_hash": content_hash,
        "status": "processing",
        "staging_status": "staged",
        "health_status": "healthy",
        "extracted_text_length": len(content),
    })
    _persist_source_metadata(
        internal_source_id,
        {
            **(request.metadata or {}),
            "external_source_id": external_source_id,
            "source_type": request.source_type or "manual",
            "ingest_kind": "text",
        },
    )
    job_id = _queue_ingestion_job(
        source_id=internal_source_id,
        twin_id=request.twin_id,
        provider=request.source_type or "manual",
        url=None,
        correlation_id=None,
    )
    return {
        "source_id": internal_source_id,
        "external_source_id": external_source_id,
        "job_id": job_id,
        "status": "processing",
        "duplicate": False,
    }

@router.post("/ingest/document")
async def ingest_document_compat(
    file: UploadFile = File(...),
    twin_id: str = Form(...),
    source_label: str | None = Form(None),
    identity_confirmed: bool | None = Form(False),
    http_req: Request = None,
    user=Depends(verify_owner)
):
    """
    Compatibility shim for onboarding:
    Accepts form-data with file + twin_id and forwards to canonical /ingest/file/{twin_id}.
    """
    logger.warning("[DEPRECATED] /ingest/document called. Use /ingest/file/{twin_id}.")
    verify_twin_ownership(twin_id, user)
    try:
        return await ingest_file_endpoint(
            twin_id=twin_id,
            file=file,
            source_label=source_label,
            identity_confirmed=identity_confirmed,
            http_req=http_req,
            user=user,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ingest/url")
async def ingest_url_compat(request: URLIngestWithTwinRequest, http_req: Request, user=Depends(verify_owner)):
    """
    Compatibility shim for onboarding:
    Accepts JSON { url, twin_id } and forwards to canonical /ingest/url/{twin_id}.
    """
    logger.warning("[DEPRECATED] /ingest/url called without twin_id in path. Use /ingest/url/{twin_id}.")
    verify_twin_ownership(request.twin_id, user)
    try:
        return await ingest_url_endpoint(
            twin_id=request.twin_id,
            request=URLIngestRequest(
                url=request.url,
                source_label=request.source_label,
                identity_confirmed=request.identity_confirmed,
            ),
            http_req=http_req,
            user=user,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/training-jobs/process-queue")
async def process_queue_endpoint(twin_id: str | None = None, user=Depends(verify_owner)):
    """
    Process queued training jobs for the authenticated user's twins.
    Returns status: "success", "partial", or "error" with details.
    """
    # Get user's twin IDs
    user_id = user.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="User not authenticated")

    # Get user's twins - use tenant_id NOT user_id!
    # CRITICAL FIX: user_id is auth UUID, tenant_id is the actual tenant association
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        return {
            "status": "error",
            "processed": 0,
            "failed": 0,
            "remaining": 0,
            "message": "User has no tenant association"
        }
    twins_result = supabase.table("twins").select("id").eq("tenant_id", tenant_id).execute()
    user_twin_ids = [t["id"] for t in (twins_result.data or [])]

    if not user_twin_ids:
        return {
            "status": "success",
            "processed": 0,
            "failed": 0,
            "remaining": 0,
            "message": "No twins found for this user"
        }

    # Filter by twin_id if provided
    if twin_id:
        if twin_id not in user_twin_ids:
            raise HTTPException(status_code=403, detail="Not authorized to process jobs for this twin")
        twin_ids_to_process = [twin_id]
    else:
        twin_ids_to_process = user_twin_ids

    # Process queue (async function - must await)
    results = await process_training_queue(twin_ids_to_process)

    processed = results.get("processed", 0)
    failed = results.get("failed", 0)
    remaining = results.get("remaining", 0)
    errors = results.get("errors", [])

    # Determine overall status
    if failed == 0:
        status = "success"
    elif processed > 0:
        status = "partial"
    else:
        status = "error"

    response_data = {
        "status": status,
        "processed": processed,
        "failed": failed,
        "remaining": remaining,
        "errors": errors[:5]  # Limit to first 5 errors
    }

    # If all failed, include first error in message
    if processed == 0 and failed > 0:
        response_data["message"] = f"Failed to process {failed} job(s). First error: {errors[0]}"

    # Return appropriate HTTP status codes
    # Note: Always return 200 OK to maintain backward compatibility
    # Frontend can check response_data.status === "error" to handle errors appropriately
    # This prevents breaking changes for clients expecting HTTP 200 OK
    return response_data

@router.get("/training-jobs/{job_id}")
async def get_training_job_endpoint(job_id: str, user=Depends(get_current_user)):
    """Get job details"""
    try:
        job = get_training_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        # Verify user has access to this job's twin
        if job.get("twin_id"):
            verify_twin_ownership(job["twin_id"], user)

        return job
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/training-jobs")
async def list_training_jobs_endpoint(
    twin_id: str,
    status: str | None = None,
    limit: int = 100,
    user=Depends(get_current_user)
):
    """List training jobs for a twin."""
    verify_twin_ownership(twin_id, user)
    try:
        return list_training_jobs(twin_id=twin_id, status=status, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/training-jobs/{job_id}/retry")
async def retry_training_job_endpoint(job_id: str, user=Depends(verify_owner)):
    """Retry a failed training job by re-queueing it."""
    job = get_training_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Verify user has access to this job's twin
    if job.get("twin_id"):
        verify_twin_ownership(job["twin_id"], user)

    try:
        # Reset status and error before re-queue
        supabase.table("training_jobs").update({
            "status": "queued",
            "error_message": None,
            "started_at": None,
            "completed_at": None,
        }).eq("id", job_id).execute()

        enqueue_job(
            job_id=job_id,
            job_type=job.get("job_type", "ingestion"),
            priority=job.get("priority", 0),
            metadata=job.get("metadata", {})
        )

        return {"status": "queued", "job_id": job_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# ISSUE-001: /ingestion-jobs aliases (backward compatible)
# These endpoints mirror /training-jobs but use clearer terminology.
# The /training-jobs endpoints remain functional for backward compatibility.
# ============================================================================

@router.post("/ingestion-jobs/process-queue")
async def process_ingestion_queue_endpoint(twin_id: str | None = None, user=Depends(verify_owner)):
    """
    Process queued ingestion jobs for the authenticated user's twins.
    Alias for /training-jobs/process-queue with clearer terminology.
    """
    # Delegate to existing training-jobs implementation
    return await process_queue_endpoint(twin_id=twin_id, user=user)


@router.get("/ingestion-jobs/{job_id}")
async def get_ingestion_job_endpoint(job_id: str, user=Depends(get_current_user)):
    """Get ingestion job details. Alias for /training-jobs/{job_id}."""
    return await get_training_job_endpoint(job_id=job_id, user=user)


@router.get("/ingestion-jobs")
async def list_ingestion_jobs_endpoint(
    twin_id: str,
    status: str | None = None,
    limit: int = 100,
    user=Depends(get_current_user)
):
    """List ingestion jobs for a twin. Alias for /training-jobs."""
    return await list_training_jobs_endpoint(twin_id=twin_id, status=status, limit=limit, user=user)


@router.post("/ingestion-jobs/{job_id}/retry")
async def retry_ingestion_job_endpoint(job_id: str, user=Depends(verify_owner)):
    """Retry a failed ingestion job. Alias for /training-jobs/{job_id}/retry."""
    return await retry_training_job_endpoint(job_id=job_id, user=user)


class ExtractNodesRequest(BaseModel):
    """Request to extract graph nodes from an ingested source."""
    max_chunks: int | None = 10  # Limit chunks to control cost


@router.post("/ingest/extract-nodes/{source_id}")
async def extract_nodes_from_source(
    source_id: str,
    request: ExtractNodesRequest = None,
    user=Depends(get_current_user)
):
    """
    Extract graph nodes/edges from an ingested source's content.

    Takes the content_text from an ingested source and runs it through
    the Scribe Engine to create graph_nodes and graph_edges.

    This bridges content ingestion with the cognitive graph.
    """
    from modules._core.scribe_engine import extract_from_content

    # HARDENED: Verify source ownership and tenant/twin association
    # This ensures the source belongs to a twin owned by the user's tenant.
    twin_id = verify_source_ownership(source_id, user)

    # Fetch source content (now that ownership is verified)
    source_result = supabase.table("sources").select(
        "id, content_text, filename, status"
    ).eq("id", source_id).single().execute()

    if not source_result.data:
        raise HTTPException(status_code=404, detail="Source not found or access denied")

    source = source_result.data


    content_text = source.get("content_text")
    if not content_text:
        raise HTTPException(status_code=400, detail="Source has no content_text to extract from")

    # Determine source type from filename
    filename = source.get("filename", "")
    source_type = "ingested_content"
    if "YouTube" in filename:
        source_type = "youtube"
    elif "Podcast" in filename:
        source_type = "podcast"
    elif filename.endswith(".pdf"):
        source_type = "pdf"
    elif "X Thread" in filename:
        source_type = "twitter"

    # Run extraction
    try:
        max_chunks = request.max_chunks if request else 10

        result = await extract_from_content(
            twin_id=twin_id,
            content_text=content_text,
            source_id=source_id,
            source_type=source_type,
            max_chunks=max_chunks,
            tenant_id=user.get("user_id")
        )

        return {
            "status": "success",
            "source_id": source_id,
            "nodes_created": len(result.get("all_nodes", [])),
            "edges_created": len(result.get("all_edges", [])),
            "chunks_processed": result.get("chunks_processed", 0),
            "confidence": result.get("total_confidence", 0.0)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")
