"""
Ingestion module -- facade that re-exports symbols from extracted sub-modules
and keeps only the code that hasn't been extracted yet (source lifecycle,
wrappers, podcast / X ingestion, etc.).

Sub-modules:
  ingestion_config   -- YouTubeConfig, ErrorClassifier, LanguageDetector, PIIScrubber, helpers
  ingestion_file     -- PDF / DOCX / XLSX extraction
  ingestion_youtube  -- YouTube transcript pipeline
  ingestion_url      -- URL strategies, metadata, LinkedIn, Instagram
  ingestion_chunking -- chunk_text, process_and_index_text
"""

import os
import re
import uuid
import asyncio
import html as html_lib
import logging
from typing import Any

logger = logging.getLogger(__name__)

import feedparser
import httpx

from modules.clients import get_openai_client
from modules.observability import supabase, log_ingestion_event
from modules.ingestion_diagnostics import start_step, finish_step, build_error
from modules.health_checks import run_all_health_checks, calculate_content_hash
from modules.governance import AuditLogger

# ---------------------------------------------------------------------------
# Re-exports from extracted sub-modules
# ---------------------------------------------------------------------------
from modules.ingestion_config import (  # noqa: F401
    YouTubeConfig,
    ErrorClassifier,
    LanguageDetector,
    PIIScrubber,
    _to_bool,
    _truncate_text,
    _resolve_tenant_id,
)

from modules.ingestion_file import (  # noqa: F401
    extract_text_from_pdf,
    extract_pdf_text_and_chunk_entries,
    extract_text_from_docx,
    extract_text_from_excel,
    _extract_pdf_pages,
    _safe_doc_name,
    _build_pdf_chunk_entries,
)

from modules.ingestion_youtube import (  # noqa: F401
    extract_video_id,
    ingest_youtube_transcript,
    fetch_youtube_transcript_compat,
    _build_yt_dlp_opts,
    _transcript_items_to_text,
)

from modules.ingestion_url import (  # noqa: F401
    detect_url_provider,
    ingest_web_url,
    ingest_linkedin_open_graph,
    ingest_instagram_profile,
    ingest_url_metadata_fallback,
    _extract_og,
    _extract_meta_name,
    _extract_canonical,
    _linkedin_login_wall,
    _provider_display_name,
    _source_update_missing_column,
    _upsert_source_resilient,
    _update_source_resilient,
    _mark_source_live_resilient,
)

from modules.ingestion_chunking import (  # noqa: F401
    chunk_text,
    chunk_text_with_metadata,
    process_and_index_text,
    analyze_chunk_content,
    _build_embedding_text,
)
import contextlib


# ============================================================================
# Podcast RSS ingestion
# ============================================================================

async def ingest_podcast_rss(source_id: str, twin_id: str, url: str):
    """
    Ingests the latest episode from a podcast RSS feed.
    """
    try:
        feed = feedparser.parse(url)
        if not feed.entries:
            raise ValueError("No episodes found in RSS feed")

        latest_episode = feed.entries[0]
        audio_url = None
        for enclosure in latest_episode.enclosures:
            if enclosure.type.startswith('audio'):
                audio_url = enclosure.href
                break

        if not audio_url:
            raise ValueError("No audio URL found in the latest episode")

        # Download audio temporarily
        temp_dir = "temp_uploads"
        os.makedirs(temp_dir, exist_ok=True)
        filename = f"{uuid.uuid4()}.mp3"
        file_path = os.path.join(temp_dir, filename)

        async with httpx.AsyncClient() as client:
            response = await client.get(audio_url)
            with open(file_path, "wb") as f:
                f.write(response.content)

        # Transcribe and index (auto-indexed)
        num_chunks = await ingest_source(source_id, twin_id, file_path, f"Podcast: {latest_episode.title}")
        return num_chunks
    except Exception as e:
        logger.error("Error ingesting podcast: %s", e)
        raise e


# ============================================================================
# X (Twitter) thread ingestion
# ============================================================================

async def ingest_x_thread(source_id: str, twin_id: str, url: str, correlation_id: str | None = None):
    """
    Ingests an X (Twitter) thread using multiple fallback strategies.
    """
    tweet_id_match = re.search(r'status/(\d+)', url)
    if not tweet_id_match:
        raise ValueError("Invalid X (Twitter) URL")

    provider = "x"
    tweet_id = tweet_id_match.group(1)
    text = ""
    user = "Unknown"

    # Ensure source row exists
    with contextlib.suppress(Exception):
        supabase.table("sources").upsert({
            "id": source_id,
            "twin_id": twin_id,
            "filename": f"X Thread: {tweet_id}",
            "file_size": 0,
            "content_text": "",
            "status": "processing",
            "citation_url": url,
        }).execute()

    fetch_event_id = start_step(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step="fetching",
        correlation_id=correlation_id,
        message="Fetching X thread content",
        metadata={"tweet_id": tweet_id, "url": url},
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    # -----------------------------------------------------------------
    # Strategy 1: cdn.syndication.twimg.com (legacy, often fails)
    # -----------------------------------------------------------------
    try:
        syndication_url = f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=0"
        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            response = await client.get(syndication_url)
            if response.status_code == 200:
                data = response.json()
                text = data.get("text", "")
                user = data.get("user", {}).get("name", "Unknown")
                if text:
                    logger.info("[X Thread] Syndication API returned %s chars", len(text))
    except Exception as e:
        logger.warning("[X Thread] Syndication API failed: %s", e)

    # -----------------------------------------------------------------
    # Strategy 2: Nitter instances (public Twitter readers)
    # -----------------------------------------------------------------
    if not text:
        nitter_instances = [
            "nitter.privacydev.net",
            "nitter.poast.org",
            "nitter.1d4.us",
        ]
        for instance in nitter_instances:
            try:
                nitter_url = f"https://{instance}/i/status/{tweet_id}"
                async with httpx.AsyncClient(timeout=15, headers=headers, follow_redirects=True) as client:
                    response = await client.get(nitter_url)
                    if response.status_code == 200:
                        page = response.text
                        content_match = re.search(r'<div class="tweet-content[^"]*"[^>]*>(.*?)</div>', page, re.DOTALL)
                        if content_match:
                            raw_text = content_match.group(1)
                            text = re.sub(r'<[^>]+>', ' ', raw_text)
                            text = html_lib.unescape(text)
                            text = re.sub(r'\s+', ' ', text).strip()

                            user_match = re.search(r'<a class="fullname"[^>]*>([^<]+)</a>', page)
                            if user_match:
                                user = user_match.group(1).strip()

                            if text:
                                logger.info("[X Thread] Nitter %s returned %s chars", instance, len(text))
                                break
            except Exception as e:
                logger.warning("[X Thread] Nitter %s failed: %s", instance, e)
                continue

    # -----------------------------------------------------------------
    # Strategy 3: FxTwitter API (embed generator)
    # -----------------------------------------------------------------
    if not text:
        try:
            fx_url = f"https://api.fxtwitter.com/status/{tweet_id}"
            async with httpx.AsyncClient(timeout=15, headers=headers) as client:
                response = await client.get(fx_url)
                if response.status_code == 200:
                    data = response.json()
                    tweet = data.get("tweet", {})
                    text = tweet.get("text", "")
                    user = tweet.get("author", {}).get("name", "Unknown")
                    if text:
                        logger.info("[X Thread] FxTwitter API returned %s chars", len(text))
        except Exception as e:
            logger.warning("[X Thread] FxTwitter API failed: %s", e)

    # -----------------------------------------------------------------
    # Strategy 4: VxTwitter API (another embed generator)
    # -----------------------------------------------------------------
    if not text:
        try:
            vx_url = f"https://api.vxtwitter.com/status/{tweet_id}"
            async with httpx.AsyncClient(timeout=15, headers=headers) as client:
                response = await client.get(vx_url)
                if response.status_code == 200:
                    data = response.json()
                    text = data.get("text", "")
                    user = data.get("user_name", "Unknown")
                    if text:
                        logger.info("[X Thread] VxTwitter API returned %s chars", len(text))
        except Exception as e:
            logger.warning("[X Thread] VxTwitter API failed: %s", e)

    # -----------------------------------------------------------------
    # Final: Handle result
    # -----------------------------------------------------------------
    if not text:
        log_ingestion_event(source_id, twin_id, "error", "All X thread extraction methods failed")
        err = build_error(
            code="X_BLOCKED_OR_UNSUPPORTED",
            message=(
                "Could not extract X thread content. X/Twitter may be blocking requests from this server. "
                "Try copying the tweet text manually and uploading it as a text file."
            ),
            provider=provider,
            step="fetching",
            correlation_id=correlation_id,
            raw={"tweet_id": tweet_id, "url": url},
        )
        finish_step(
            event_id=fetch_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="fetching",
            status="error",
            correlation_id=correlation_id,
            error=err,
        )
        raise ValueError(err["message"])

    finish_step(
        event_id=fetch_event_id,
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step="fetching",
        status="completed",
        correlation_id=correlation_id,
        metadata={"text_len": len(text)},
    )

    parsed_event_id = start_step(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step="parsed",
        correlation_id=correlation_id,
        message="Persisting extracted X thread text",
        metadata={"tweet_id": tweet_id},
    )

    try:
        content_hash = calculate_content_hash(text)

        supabase.table("sources").upsert({
            "id": source_id,
            "twin_id": twin_id,
            "filename": f"X Thread: {tweet_id} by {user}",
            "file_size": len(text),
            "content_text": text,
            "content_hash": content_hash,
            "status": "processing",
            "extracted_text_length": len(text)
        }).execute()

        finish_step(
            event_id=parsed_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="parsed",
            status="completed",
            correlation_id=correlation_id,
            metadata={"text_len": len(text), "user": user},
        )

        # Small verification wait to settle FK
        await asyncio.sleep(1)

        log_ingestion_event(source_id, twin_id, "info", f"X thread extracted: {len(text)} characters")

        # Direct indexing
        num_chunks = await process_and_index_text(source_id, twin_id, text, metadata_override={
            "filename": f"X Thread: {tweet_id} by {user}",
            "type": "x_thread",
            "tweet_id": tweet_id
        }, provider=provider, correlation_id=correlation_id)

        tenant_id = _resolve_tenant_id(twin_id, source_id=source_id)

        AuditLogger.log(
            tenant_id=tenant_id,
            twin_id=twin_id,
            event_type="KNOWLEDGE_UPDATE",
            action="SOURCE_INDEXED",
            metadata={"source_id": source_id, "filename": f"X Thread: {tweet_id} by {user}", "type": "x_thread", "chunks": num_chunks}
        )

        # Set status to live after successful Pinecone upsert
        supabase.table("sources").update({
            "status": "live",
            "chunk_count": num_chunks
        }).eq("id", source_id).execute()

        log_ingestion_event(source_id, twin_id, "info", f"X Thread content indexed: {num_chunks} chunks, status=live")

        live_event_id = start_step(
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="live",
            correlation_id=correlation_id,
            message="Source is live",
        )
        finish_step(
            event_id=live_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="live",
            status="completed",
            correlation_id=correlation_id,
            metadata={"chunks": num_chunks},
        )

        # Enqueue async content extraction to build graph nodes/edges
        try:
            from modules._core.scribe_engine import enqueue_content_extraction_job
            max_chunks = int(os.getenv("CONTENT_EXTRACT_MAX_CHUNKS", "6"))
            enqueue_content_extraction_job(
                twin_id=twin_id,
                source_id=source_id,
                tenant_id=tenant_id,
                source_type="twitter",
                max_chunks=max_chunks
            )
            log_ingestion_event(source_id, twin_id, "info", f"Graph extraction queued (max_chunks={max_chunks})")
        except Exception as e:
            log_ingestion_event(source_id, twin_id, "warning", f"Graph extraction enqueue failed: {e}")
            logger.warning("[Ingestion] Warning: Failed to enqueue graph extraction for source %s: %s", source_id, e)

        return num_chunks
    except Exception as e:
        try:
            err = build_error(
                code="X_INDEXING_FAILED",
                message=str(e),
                provider=provider,
                step="indexed",
                correlation_id=correlation_id,
                raw={"tweet_id": tweet_id, "url": url},
                exc=e,
            )
            finish_step(
                event_id="",
                source_id=source_id,
                twin_id=twin_id,
                provider=provider,
                step="indexed",
                status="error",
                correlation_id=correlation_id,
                error=err,
            )
        except Exception:
            pass
        logger.error("Error processing X thread: %s", e)
        log_ingestion_event(source_id, twin_id, "error", f"Error processing X thread: {e}")
        supabase.table("sources").update({"status": "error", "health_status": "failed"}).eq("id", source_id).execute()
        raise e


# ============================================================================
# URL routing
# ============================================================================

async def ingest_url_to_source(
    source_id: str,
    twin_id: str,
    url: str,
    provider: str | None = None,
    correlation_id: str | None = None
) -> int:
    """Route a URL ingestion to the correct provider handler using an existing source_id."""
    detected = provider or detect_url_provider(url)
    if detected == "youtube":
        return await ingest_youtube_transcript(source_id, twin_id, url, correlation_id=correlation_id)
    if detected == "x":
        return await ingest_x_thread(source_id, twin_id, url, correlation_id=correlation_id)
    if detected == "podcast":
        return await ingest_podcast_rss(source_id, twin_id, url)
    if detected == "linkedin":
        return await ingest_linkedin_open_graph(source_id, twin_id, url, correlation_id=correlation_id)
    if detected == "instagram":
        return await ingest_instagram_profile(source_id, twin_id, url, correlation_id=correlation_id)
    if detected in ("facebook", "web"):
        return await ingest_web_url(source_id, twin_id, url, correlation_id=correlation_id)
    raise ValueError(f"Unsupported URL provider: {detected}")


# ============================================================================
# Audio transcription
# ============================================================================

async def transcribe_audio(file_path: str) -> str:
    """Transcribes audio using OpenAI Whisper API."""
    client = get_openai_client()
    with open(file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file
        )
    return transcript.text


# ============================================================================
# Source lifecycle
# ============================================================================

def _infer_source_type(filename: str) -> str:
    name = (filename or "").lower()
    if "youtube" in name or "youtu.be" in name:
        return "youtube"
    if "podcast" in name or "rss" in name or "anchor.fm" in name or "podbean" in name:
        return "podcast"
    if "x thread" in name or "twitter.com" in name or "x.com" in name:
        return "twitter"
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".docx"):
        return "docx"
    if name.endswith(".xlsx"):
        return "xlsx"
    if name.startswith("http://") or name.startswith("https://"):
        return "url"
    return "ingested_content"


async def ingest_source(source_id: str, twin_id: str, file_path: str, filename: str = None):
    """Ingest a file - extracts text and indexes to Pinecone.

    Args:
        source_id: Unique identifier for this source
        twin_id: Owner twin ID
        file_path: Path to the file to ingest
        filename: Optional display name for the file
    """
    # 0. Check for existing sources with same name to handle "update"
    has_duplicate = False
    if filename:
        existing = supabase.table("sources").select("id").eq("twin_id", twin_id).eq("filename", filename).execute()
        if existing.data:
            logger.info("File %s already exists. Updating source(s)...", filename)
            has_duplicate = True
            for record in existing.data:
                old_source_id = record["id"]
                await delete_source(old_source_id, twin_id)

    # 0.1 Record source in Supabase FIRST (before logging - prevents FK error).
    if filename:
        file_size = os.path.getsize(file_path)
        supabase.table("sources").upsert({
            "id": source_id,
            "twin_id": twin_id,
            "filename": filename,
            "file_size": file_size,
            "status": "processing"
        }).execute()

    if has_duplicate:
        log_ingestion_event(source_id, twin_id, "info", "Duplicate filename detected, removed old sources")

    # 1. Extract text (PDF, Docx, Excel, or Audio)
    pdf_chunk_entries: list[dict[str, Any]] | None = None
    text = ""
    if file_path.endswith('.pdf'):
        text, pdf_chunk_entries = extract_pdf_text_and_chunk_entries(
            file_path,
            doc_name=filename or os.path.basename(file_path) or "document",
        )
    elif file_path.endswith('.docx'):
        text = extract_text_from_docx(file_path)
    elif file_path.endswith('.xlsx'):
        text = extract_text_from_excel(file_path)
    elif file_path.endswith(('.mp3', '.wav', '.m4a', '.webm')):
        text = await transcribe_audio(file_path)
    else:
        with open(file_path, encoding='utf-8', errors='ignore') as f:
            text = f.read()

    if not text or not text.strip():
        raise ValueError(
            f"No text could be extracted from {filename or file_path}. "
            f"The file may be empty, corrupted, or in an unsupported format."
        )

    content_hash = calculate_content_hash(text)

    update_data = {
        "content_text": text,
        "content_hash": content_hash,
        "status": "processing",
        "extracted_text_length": len(text)
    }

    if filename:
        supabase.table("sources").update(update_data).eq("id", source_id).execute()
    else:
        supabase.table("sources").upsert({
            "id": source_id,
            "twin_id": twin_id,
            **update_data
        }).execute()

    log_ingestion_event(source_id, twin_id, "info", f"Text extracted: {len(text)} characters")

    tenant_id = _resolve_tenant_id(twin_id, source_id=source_id)

    AuditLogger.log(
        tenant_id=tenant_id,
        twin_id=twin_id,
        event_type="KNOWLEDGE_UPDATE",
        action="SOURCE_EXTRACTED",
        metadata={"source_id": source_id, "filename": filename or "unknown", "type": "file_upload"}
    )

    health_result = run_all_health_checks(
        source_id,
        twin_id,
        text,
        source_data={
            "filename": filename or "unknown",
            "twin_id": twin_id
        }
    )

    supabase.table("sources").update({
        "health_status": health_result["overall_status"]
    }).eq("id", source_id).execute()

    log_ingestion_event(source_id, twin_id, "info", f"Health checks completed: {health_result['overall_status']}")

    log_ingestion_event(source_id, twin_id, "info", "Auto-indexing enabled")
    num_chunks = await process_and_index_text(source_id, twin_id, text, metadata_override={
        "filename": filename or "unknown",
        "type": "file"
    }, chunk_entries_override=pdf_chunk_entries)

    supabase.table("sources").update({
        "status": "live",
        "chunk_count": num_chunks
    }).eq("id", source_id).execute()

    log_ingestion_event(source_id, twin_id, "info", f"Auto-indexed: {num_chunks} chunks, status=live")

    # Enqueue async content extraction to build graph nodes/edges
    try:
        from modules._core.scribe_engine import enqueue_content_extraction_job
        max_chunks = int(os.getenv("CONTENT_EXTRACT_MAX_CHUNKS", "6"))
        source_type = _infer_source_type(filename or "")
        enqueue_content_extraction_job(
            twin_id=twin_id,
            source_id=source_id,
            tenant_id=tenant_id,
            source_type=source_type,
            max_chunks=max_chunks
        )
        log_ingestion_event(source_id, twin_id, "info", f"Graph extraction queued (max_chunks={max_chunks})")
    except Exception as e:
        log_ingestion_event(source_id, twin_id, "warning", f"Graph extraction enqueue failed: {e}")
        logger.warning("[Ingestion] Warning: Failed to enqueue graph extraction for source %s: %s", source_id, e)

    AuditLogger.log(
        tenant_id=tenant_id,
        twin_id=twin_id,
        event_type="KNOWLEDGE_UPDATE",
        action="SOURCE_INDEXED",
        metadata={
            "source_id": source_id,
            "filename": filename or "unknown",
            "type": "file",
            "chunks": num_chunks
        }
    )

    return num_chunks


async def delete_source(source_id: str, twin_id: str):
    """
    Deletes a source fully: pgvector chunks + Supabase source row.
    """
    filename = "unknown"
    try:
        source_resp = (
            supabase.table("sources")
            .select("filename")
            .eq("id", source_id)
            .eq("twin_id", twin_id)
            .limit(1)
            .execute()
        )
        rows = source_resp.data or []
        if rows:
            filename = str(rows[0].get("filename") or "unknown")
    except Exception as e:
        logger.warning("[DeleteSource] source metadata lookup: %s", e)

    try:
        supabase.table("chunks").delete().eq("source_id", source_id).execute()
    except Exception as e:
        logger.warning("[DeleteSource] chunks delete: %s", e)

    supabase.table("sources").delete().eq("id", source_id).eq("twin_id", twin_id).execute()

    tenant_id = _resolve_tenant_id(twin_id, source_id=source_id)
    AuditLogger.log(
        tenant_id=tenant_id,
        twin_id=twin_id,
        event_type="KNOWLEDGE_UPDATE",
        action="SOURCE_DELETED",
        metadata={"source_id": source_id, "filename": filename},
    )

    return True


async def bulk_update_source_metadata(source_ids: list[str], metadata_updates: dict[str, Any]):
    """
    Bulk update metadata for sources.

    Args:
        source_ids: List of source UUIDs
        metadata_updates: Dict with fields to update (access_group, publish_date, author, citation_url, visibility)
    """
    allowed_fields = ["publish_date", "author", "citation_url"]
    update_data = {k: v for k, v in metadata_updates.items() if k in allowed_fields}

    if not update_data:
        return

    for source_id in source_ids:
        try:
            supabase.table("sources").update(update_data).eq("id", source_id).execute()
        except Exception as e:
            logger.warning("Error updating source %s: %s", source_id, e)


# ============================================================================
# Wrapper functions for router endpoints
# ============================================================================

async def ingest_youtube_transcript_wrapper(twin_id: str, url: str) -> str:
    """Wrapper that creates source_id and calls ingest_youtube_transcript"""
    source_id = str(uuid.uuid4())
    await ingest_youtube_transcript(source_id, twin_id, url)
    return source_id


async def ingest_podcast_transcript(twin_id: str, url: str) -> str:
    """Wrapper that creates source_id and calls ingest_podcast_rss"""
    source_id = str(uuid.uuid4())
    await ingest_podcast_rss(source_id, twin_id, url)
    return source_id


async def ingest_x_thread_wrapper(twin_id: str, url: str) -> str:
    """Wrapper that creates source_id and calls ingest_x_thread"""
    source_id = str(uuid.uuid4())
    await ingest_x_thread(source_id, twin_id, url)
    return source_id


async def ingest_file(twin_id: str, file) -> str:
    """Wrapper that saves uploaded file and calls ingest_source.

    Args:
        twin_id: Owner twin ID
        file: Uploaded file object
    """
    source_id = str(uuid.uuid4())
    temp_dir = "temp_uploads"
    os.makedirs(temp_dir, exist_ok=True)

    file_extension = os.path.splitext(file.filename)[1] if file.filename else ""
    temp_filename = f"{source_id}{file_extension}"
    file_path = os.path.join(temp_dir, temp_filename)

    try:
        with open(file_path, "wb") as f:
            content = await file.read()
            f.write(content)

        await ingest_source(source_id, twin_id, file_path, file.filename)

        if os.path.exists(file_path):
            os.remove(file_path)

        return source_id
    except Exception as e:
        if os.path.exists(file_path):
            os.remove(file_path)
        raise e


async def ingest_url(twin_id: str, url: str) -> str:
    """Wrapper that creates a new source_id and ingests a URL."""
    source_id = str(uuid.uuid4())
    await ingest_url_to_source(source_id=source_id, twin_id=twin_id, url=url)
    return source_id
