"""
URL-based ingestion strategies.

Extracted from ingestion.py -- contains HTML metadata helpers, provider detection,
and ingestion functions for LinkedIn, Instagram, and generic web URLs.
"""

import ipaddress as _ipaddress
import logging
import re
import urllib.parse
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

from modules.observability import supabase, log_ingestion_event
from modules.ingestion_diagnostics import start_step, finish_step, build_error
from modules.health_checks import calculate_content_hash

from modules.ingestion_config import (
    _truncate_text,
)


# ---------------------------------------------------------------------------
# SSRF guard — block private IPs, metadata endpoints, non-HTTP schemes
# ---------------------------------------------------------------------------

_BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "169.254.169.254"}


def validate_url_for_ingestion(url: str) -> None:
    """Raise ValueError if *url* targets internal/private resources (SSRF guard)."""
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Blocked scheme: {parsed.scheme}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("Empty hostname")
    if host in _BLOCKED_HOSTS:
        raise ValueError(f"Blocked host: {host}")
    try:
        addr = _ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise ValueError(f"Blocked private/loopback IP: {host}")
    except ValueError as exc:
        if "Blocked" in str(exc):
            raise
        # hostname, not IP — allow


# ---------------------------------------------------------------------------
# HTML metadata helpers
# ---------------------------------------------------------------------------

def _extract_og(soup: BeautifulSoup, prop: str) -> str | None:
    tag = soup.find("meta", attrs={"property": prop})
    if tag and tag.get("content"):
        return str(tag.get("content")).strip()
    return None


def _extract_meta_name(soup: BeautifulSoup, name: str) -> str | None:
    tag = soup.find("meta", attrs={"name": name})
    if tag and tag.get("content"):
        return str(tag.get("content")).strip()
    return None


def _extract_canonical(soup: BeautifulSoup) -> str | None:
    tag = soup.find("link", attrs={"rel": "canonical"})
    if tag and tag.get("href"):
        return str(tag.get("href")).strip()
    return None


def _linkedin_login_wall(html_text: str, final_url: str) -> bool:
    t = (html_text or "").lower()
    u = (final_url or "").lower()
    if "/login" in u or "/checkpoint" in u or "authwall" in u:
        return True
    # Common LinkedIn wall cues
    if "sign in" in t and "linkedin" in t and ("join linkedin" in t or "sign in to see" in t):
        return True
    return bool("linkedin login" in t or "linkedin: log in" in t)


def _provider_display_name(provider: str) -> str:
    normalized = (provider or "web").strip().lower()
    if normalized in {"youtube", "yt"}:
        return "YouTube"
    if normalized in {"linkedin"}:
        return "LinkedIn"
    if normalized in {"x", "twitter"}:
        return "X"
    if normalized in {"podcast"}:
        return "Podcast"
    return "Web"


def detect_url_provider(url: str) -> str:
    u = (url or "").strip().lower()
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "twitter.com" in u or "x.com" in u:
        return "x"
    if "linkedin.com" in u:
        return "linkedin"
    if "instagram.com" in u:
        return "instagram"
    if "facebook.com" in u or "fb.com" in u:
        return "facebook"
    if u.endswith(".rss") or "feed" in u or "podcast" in u or "anchor.fm" in u or "podbean" in u:
        return "podcast"
    if u.startswith("http://") or u.startswith("https://"):
        return "web"
    return "unknown"


# ---------------------------------------------------------------------------
# Source resilience helpers (shared by URL ingestion paths)
# ---------------------------------------------------------------------------

def _source_update_missing_column(exc: Exception, column_name: str) -> bool:
    msg = str(exc).lower()
    col = (column_name or "").lower()
    return (
        bool(col)
        and col in msg
        and (
            "column" in msg
            or "does not exist" in msg
            or "could not find" in msg
            or "pgrst204" in msg
        )
    )


def _upsert_source_resilient(payload: dict[str, Any]) -> None:
    """Upsert source row while tolerating optional-column drift across deployments."""
    data = dict(payload)
    while True:
        try:
            supabase.table("sources").upsert(data).execute()
            return
        except Exception as e:
            removed = None
            for optional_column in ("staging_status", "content_hash", "extracted_text_length"):
                if optional_column in data and _source_update_missing_column(e, optional_column):
                    removed = optional_column
                    break
            if removed:
                data.pop(removed, None)
                continue
            raise


def _update_source_resilient(source_id: str, payload: dict[str, Any], *, twin_id: str | None = None) -> None:
    """Update source row while tolerating optional-column drift across deployments."""
    data = dict(payload)
    while True:
        try:
            query = supabase.table("sources").update(data).eq("id", source_id)
            if twin_id:
                query = query.eq("twin_id", twin_id)
            query.execute()
            return
        except Exception as e:
            removed = None
            for optional_column in ("staging_status", "content_hash", "extracted_text_length", "chunk_count"):
                if optional_column in data and _source_update_missing_column(e, optional_column):
                    removed = optional_column
                    break
            if removed:
                data.pop(removed, None)
                continue
            raise


def _mark_source_live_resilient(source_id: str, chunk_count: int) -> None:
    """Mark source live while tolerating optional-column drift across deployments."""
    update_payload: dict[str, Any] = {
        "status": "live",
        "chunk_count": chunk_count,
    }
    while True:
        try:
            supabase.table("sources").update(update_payload).eq("id", source_id).execute()
            return
        except Exception as e:
            removed = None
            for optional_column in ("staging_status", "chunk_count"):
                if optional_column in update_payload and _source_update_missing_column(e, optional_column):
                    removed = optional_column
                    break
            if removed:
                update_payload.pop(removed, None)
                continue
            raise


# ---------------------------------------------------------------------------
# URL ingestion functions
# ---------------------------------------------------------------------------

async def ingest_url_metadata_fallback(
    source_id: str,
    twin_id: str,
    url: str,
    provider: str = "web",
    correlation_id: str | None = None,
    error_message: str | None = None,
    source_type: str = "url_metadata_fallback",
    preferred_title: str | None = None,
) -> int:
    """
    Last-resort URL ingestion path.
    Builds a metadata-only text document so indexing can proceed even when full content extraction fails.
    """
    from modules.ingestion_chunking import process_and_index_text

    provider_norm = (provider or "web").strip().lower()
    provider_label = _provider_display_name(provider_norm)

    final_url = url
    http_status: int | None = None
    fetch_error: str | None = None
    title = _truncate_text(preferred_title, limit=200) or None
    description: str | None = None
    canonical: str | None = None
    html_text = ""

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.8",
    }

    validate_url_for_ingestion(url)

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as client:
            response = await client.get(url)
            http_status = response.status_code
            final_url = str(response.url)
            html_text = response.text or ""
    except Exception as fetch_exc:
        fetch_error = _truncate_text(str(fetch_exc), limit=500)

    if html_text:
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            if not title:
                og_title = _extract_og(soup, "og:title")
                page_title = soup.title.string.strip() if soup.title and soup.title.string else None
                title = _truncate_text(og_title or page_title, limit=200) or None
            description = _truncate_text(
                _extract_og(soup, "og:description") or _extract_meta_name(soup, "description"),
                limit=1000,
            ) or None
            canonical = _truncate_text(_extract_canonical(soup), limit=300) or None
        except Exception as parse_exc:
            parse_error = _truncate_text(str(parse_exc), limit=400)
            fetch_error = fetch_error or f"metadata_parse_failed: {parse_error}"

    title = title or _truncate_text(final_url or url, limit=200) or "Untitled"
    error_summary = _truncate_text(error_message, limit=700)

    doc_lines = [
        f"{provider_label} Source (metadata fallback)",
        f"Original URL: {url}",
    ]
    if final_url and final_url != url:
        doc_lines.append(f"Final URL: {final_url}")
    if canonical:
        doc_lines.append(f"Canonical URL: {canonical}")
    if http_status is not None:
        doc_lines.append(f"HTTP Status: {http_status}")
    doc_lines.append(f"Title: {title}")
    if description:
        doc_lines.append(f"Description: {description}")
    doc_lines.append(
        "Content note: Full body extraction failed or was inaccessible; this entry stores only discovered metadata."
    )
    if error_summary:
        doc_lines.append(f"Primary ingestion error: {error_summary}")
    if fetch_error and fetch_error != error_summary:
        doc_lines.append(f"Fallback fetch note: {fetch_error}")

    metadata_text = "\n".join(line for line in doc_lines if line).strip()
    if len(metadata_text) < 40:
        metadata_text = (
            f"{provider_label} Source (metadata fallback)\n"
            f"Original URL: {url}\n"
            "Content note: Metadata fallback used."
        )

    filename = f"{provider_label} (metadata): {title}"[:240]
    content_hash = calculate_content_hash(metadata_text)

    source_payload: dict[str, Any] = {
        "id": source_id,
        "twin_id": twin_id,
        "filename": filename,
        "file_size": len(metadata_text),
        "content_text": metadata_text,
        "content_hash": content_hash,
        "status": "processing",
        "extracted_text_length": len(metadata_text),
        "citation_url": url,
    }
    _upsert_source_resilient(source_payload)

    log_ingestion_event(
        source_id,
        twin_id,
        "warning",
        f"Metadata fallback ingestion engaged for {provider_norm or 'web'} URL",
    )

    metadata_override: dict[str, Any] = {
        "filename": filename,
        "type": source_type,
        "url": url,
        "provider": provider_norm,
        "is_metadata_fallback": True,
    }
    if final_url:
        metadata_override["final_url"] = final_url
    if canonical:
        metadata_override["canonical_url"] = canonical
    if http_status is not None:
        metadata_override["http_status"] = http_status

    num_chunks = await process_and_index_text(
        source_id=source_id,
        twin_id=twin_id,
        text=metadata_text,
        metadata_override=metadata_override,
        provider=f"{provider_norm}_fallback" if provider_norm else "web_fallback",
        correlation_id=correlation_id,
    )

    _mark_source_live_resilient(source_id, num_chunks)
    return num_chunks


async def ingest_linkedin_open_graph(source_id: str, twin_id: str, url: str, correlation_id: str | None = None) -> int:
    """
    LinkedIn ingestion with Dumpling AI as primary strategy:
    - Tries Dumpling AI first for reliable extraction
    - Falls back to OpenGraph metadata if Dumpling fails
    - If blocked/login wall, creates metadata fallback
    """
    from modules.ingestion_chunking import process_and_index_text

    provider = "linkedin"

    # Ensure source row exists
    try:
        supabase.table("sources").upsert({
            "id": source_id,
            "twin_id": twin_id,
            "filename": "LinkedIn: queued",
            "file_size": 0,
            "content_text": "",
            "status": "processing",
            "citation_url": url,
        }).execute()
    except Exception as e:
        logger.warning("[LinkedIn] Warning: Failed to upsert source record: %s", e)

    fetch_event_id = start_step(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step="fetching",
        correlation_id=correlation_id,
        message="Fetching LinkedIn profile",
        metadata={"url": url},
    )

    http_status: int | None = None
    final_url: str = url
    og_title = None
    og_desc = None
    og_image = None
    canonical = None
    page_title = None
    html_text = ""
    # -------------------------------------------------------------
    # Strategy 0: Direct HTTP fetch with OpenGraph
    # -------------------------------------------------------------
    # Note: LinkedIn aggressively blocks scrapers with HTTP 999.
    # Primary LinkedIn ingestion now goes through deep research (OIDC flow).
    # This path creates a reference source the user can manually update.
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.8",
        }
        async with httpx.AsyncClient(timeout=20, headers=headers, follow_redirects=True) as client:
            resp = await client.get(url)
            http_status = resp.status_code
            final_url = str(resp.url)
            html_text = resp.text or ""

        # If blocked, create a reference source that user can manually fill
        if http_status in (401, 403, 429, 999) or _linkedin_login_wall(html_text, final_url):
            logger.info("[LinkedIn] HTTP %s - creating reference source for manual content", http_status)

            # Extract profile name from URL
            profile_name = url.split("/in/")[-1].rstrip("/").replace("-", " ").title() if "/in/" in url else "LinkedIn Profile"

            doc = f"""# LinkedIn Profile: {profile_name}
URL: {url}

## Note
This LinkedIn profile could not be automatically extracted due to LinkedIn's bot protection (HTTP {http_status}).
To add this profile's content:
1. Visit your LinkedIn profile while logged in
2. Copy the About section, Experience, and other relevant information
3. Paste it as a text source or edit this source

## Placeholder
[Content pending manual addition]
"""

            supabase.table("sources").update({
                "filename": f"LinkedIn: {profile_name} (manual upload needed)"[:240],
                "file_size": len(doc),
                "content_text": doc,
                "status": "live",  # Mark as live so user can see it
                "extracted_text_length": len(doc),
                "citation_url": url,
            }).eq("id", source_id).eq("twin_id", twin_id).execute()

            finish_step(
                event_id=fetch_event_id,
                source_id=source_id,
                twin_id=twin_id,
                provider=provider,
                step="fetching",
                status="completed",
                correlation_id=correlation_id,
                metadata={"http_status": http_status, "manual_upload_needed": True},
            )

            # Index the reference document
            num_chunks = await process_and_index_text(
                source_id,
                twin_id,
                doc,
                metadata_override={
                    "filename": f"LinkedIn: {profile_name}"[:240],
                    "type": "linkedin_profile",
                    "url": url,
                    "profile_name": profile_name,
                    "manual_upload_needed": True,
                },
                provider=provider,
                correlation_id=correlation_id,
            )

            supabase.table("sources").update({
                "chunk_count": num_chunks,
            }).eq("id", source_id).execute()

            return num_chunks

        # If we got here, we have actual HTML content to parse
        soup = BeautifulSoup(html_text, "html.parser")
        og_title = _extract_og(soup, "og:title")
        og_desc = _extract_og(soup, "og:description")
        og_image = _extract_og(soup, "og:image")
        canonical = _extract_canonical(soup) or _extract_og(soup, "og:url")
        page_title = (soup.title.string.strip() if soup.title and soup.title.string else None)

        # Fallback: standard meta tags
        if not og_desc:
            og_desc = _extract_meta_name(soup, "description")

        # Block heuristics: LinkedIn login pages often expose generic titles
        if (og_title and "linkedin login" in og_title.lower()) or (page_title and "linkedin login" in page_title.lower()):
            raise ValueError("LinkedIn returned a login wall page.")

        if not og_title and not og_desc:
            raise ValueError("No public OpenGraph metadata available.")

        finish_step(
            event_id=fetch_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="fetching",
            status="completed",
            correlation_id=correlation_id,
            metadata={"http_status": http_status, "has_og_title": bool(og_title), "has_og_desc": bool(og_desc)},
        )
    except Exception as e:
        # Log error and create reference source as fallback
        logger.warning("[LinkedIn] OpenGraph fetch failed: %s", e)
        err = build_error(
            code="LINKEDIN_BLOCKED_OR_REQUIRES_AUTH",
            message="LinkedIn profile content could not be fetched publicly.",
            provider=provider,
            step="fetching",
            correlation_id=correlation_id,
            raw={"url": url, "error": str(e)},
            exc=e,
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

    parsed_event_id = start_step(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step="parsed",
        correlation_id=correlation_id,
        message="Building minimal profile document from OG fields",
    )
    try:
        title = og_title or page_title or "LinkedIn Profile"
        desc = og_desc or ""
        canon = canonical or final_url or url

        doc = "\n".join([
            "LinkedIn Profile (public metadata)",
            f"Title: {title}",
            f"Description: {desc}",
            f"URL: {canon}",
            f"Image: {og_image or ''}",
        ]).strip()

        content_hash = calculate_content_hash(doc)

        supabase.table("sources").update({
            "filename": f"LinkedIn: {title}"[:240],
            "file_size": len(doc),
            "content_text": doc,
            "content_hash": content_hash,
            "status": "processing",
            "extracted_text_length": len(doc),
            "citation_url": url,
        }).eq("id", source_id).eq("twin_id", twin_id).execute()

        finish_step(
            event_id=parsed_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="parsed",
            status="completed",
            correlation_id=correlation_id,
            metadata={"text_len": len(doc), "canonical": canon},
        )
    except Exception as e:
        err = build_error(
            code="LINKEDIN_PARSE_FAILED",
            message=f"Failed to build LinkedIn metadata document: {str(e)}",
            provider=provider,
            step="parsed",
            correlation_id=correlation_id,
            raw={"url": url},
            exc=e,
        )
        finish_step(
            event_id=parsed_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="parsed",
            status="error",
            correlation_id=correlation_id,
            error=err,
        )
        raise

    num_chunks = await process_and_index_text(
        source_id,
        twin_id,
        doc,
        metadata_override={
            "filename": f"LinkedIn: {title}"[:240],
            "type": "linkedin_profile_og",
            "url": url,
            "canonical_url": canonical or final_url,
        },
        provider=provider,
        correlation_id=correlation_id,
    )

    supabase.table("sources").update({
        "status": "live",
        "chunk_count": num_chunks,
    }).eq("id", source_id).execute()

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

    return num_chunks


async def ingest_web_url(source_id: str, twin_id: str, url: str, correlation_id: str | None = None) -> int:
    """Ingest a generic web URL by fetching HTML, extracting text, and indexing."""
    from modules.ingestion_chunking import process_and_index_text

    provider = "web"

    try:
        _upsert_source_resilient({
            "id": source_id,
            "twin_id": twin_id,
            "filename": f"Web: {url}"[:240],
            "file_size": 0,
            "content_text": "",
            "status": "processing",
            "citation_url": url,
        })
    except Exception as e:
        logger.warning("[Web] Warning: Failed to upsert source record: %s", e)

    fetch_event_id = start_step(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step="fetching",
        correlation_id=correlation_id,
        message="Fetching web page",
        metadata={"url": url},
    )

    # -------------------------------------------------------------
    # Strategy 0: Firecrawl (Primary - JS-rendered web scraping)
    # -------------------------------------------------------------
    html_text = ""
    extracted_text = ""
    http_status = None
    scraper_success = False

    try:
        from modules.firecrawl_client import get_firecrawl_client
        firecrawl = get_firecrawl_client()
        if firecrawl:
            logger.info("[Web] Trying Firecrawl scraping for %s", url)
            log_ingestion_event(source_id, twin_id, "info", "Attempting Firecrawl web scraping")

            fc_result = await firecrawl.scrape_with_retry(url)

            if fc_result.success and fc_result.content and len(fc_result.content) > 50:
                extracted_text = fc_result.content
                fc_title = fc_result.metadata.get("title") or fc_result.metadata.get("ogTitle") or ""
                scraper_success = True
                http_status = fc_result.http_status or 200
                html_text = extracted_text
                logger.info("[Web] Firecrawl scraping succeeded: %s characters", len(extracted_text))
                log_ingestion_event(source_id, twin_id, "info", f"Firecrawl scraping successful ({len(extracted_text)} chars)")

                if fc_title and fc_title != url:
                    try:
                        _update_source_resilient(source_id, {
                            "filename": f"Web: {fc_title}"[:240],
                        }, twin_id=twin_id)
                    except Exception as title_e:
                        logger.warning("[Web] Warning: Could not update title: %s", title_e)
            else:
                logger.warning("[Web] Firecrawl returned insufficient content: %s chars, quality=%s", len(fc_result.content), fc_result.quality)
        else:
            logger.info("[Web] Firecrawl not configured, falling back to direct HTTP")
    except Exception as firecrawl_error:
        logger.warning("[Web] Firecrawl scraping failed: %s", firecrawl_error)
        log_ingestion_event(source_id, twin_id, "warning", f"Firecrawl scraping failed: {firecrawl_error}")

    # -------------------------------------------------------------
    # Strategy 1: Direct HTTP fetch (Fallback)
    # -------------------------------------------------------------
    if not scraper_success:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(url)
                http_status = resp.status_code
                resp.raise_for_status()
                html_text = resp.text or ""

            finish_step(
                event_id=fetch_event_id,
                source_id=source_id,
                twin_id=twin_id,
                provider=provider,
                step="fetching",
                status="completed",
                correlation_id=correlation_id,
                metadata={"http_status": http_status, "bytes": len(html_text)},
            )
        except Exception as e:
            err = build_error(
                code="WEB_FETCH_FAILED",
                message=f"Failed to fetch URL: {str(e)}",
                provider=provider,
                step="fetching",
                http_status=http_status,
                correlation_id=correlation_id,
                raw={"url": url},
                exc=e,
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
            # FALLBACK: Use metadata-only ingestion when fetch fails
            logger.warning("[Web] Fetch failed for %s, falling back to metadata-only ingestion", url)
            return await ingest_url_metadata_fallback(
                source_id=source_id,
                twin_id=twin_id,
                url=url,
                provider=provider,
                correlation_id=correlation_id,
                error_message=str(e),
                source_type="web_fetch_failed",
            )

    parsed_event_id = start_step(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step="parsed",
        correlation_id=correlation_id,
        message="Extracting text from content",
    )

    title = url  # Default title
    try:
        # If Firecrawl succeeded, we already have clean markdown text
        if scraper_success and extracted_text:
            text = extracted_text
            # Try to extract title from first markdown heading if available
            lines = text.split('\n')
            for line in lines[:10]:  # Check first 10 lines
                if line.startswith('# '):
                    title = line.replace('# ', '').strip()
                    break
        else:
            # Strategy 1.5: Gemini extraction from raw HTML (better than BeautifulSoup)
            soup = BeautifulSoup(html_text, "html.parser")
            title = soup.title.string.strip() if soup.title and soup.title.string else url
            text = ""
            try:
                from modules.gemini_extraction import gemini_extract_web_content
                gemini_text = await gemini_extract_web_content(url, html_text)
                if gemini_text:
                    text = gemini_text
                    logger.info("[Web] Gemini extraction succeeded: %d chars", len(text))
                    # Extract title from Gemini output heading if present
                    for line in text.split('\n')[:10]:
                        if line.startswith('# '):
                            title = line.replace('# ', '').strip()
                            break
            except Exception as gemini_err:
                logger.warning("[Web] Gemini extraction failed, falling back to BeautifulSoup: %s", gemini_err)

            # Fallback: BeautifulSoup plain text
            if not text:
                text = soup.get_text(separator="\n", strip=True)
                text = re.sub(r"\n{3,}", "\n\n", text).strip()

        if not text or len(text) < 50:
            raise ValueError(f"Insufficient text extracted from page: {len(text)} chars")

        content_hash = calculate_content_hash(text)
        _update_source_resilient(source_id, {
            "filename": f"Web: {title}"[:240],
            "file_size": len(text),
            "content_text": text,
            "content_hash": content_hash,
            "status": "processing",
            "extracted_text_length": len(text),
            "citation_url": url,
        }, twin_id=twin_id)

        finish_step(
            event_id=parsed_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="parsed",
            status="completed",
            correlation_id=correlation_id,
            metadata={"text_len": len(text), "title": title},
        )
    except Exception as e:
        err = build_error(
            code="WEB_PARSE_FAILED",
            message=f"Failed to parse page: {str(e)}",
            provider=provider,
            step="parsed",
            correlation_id=correlation_id,
            raw={"url": url},
            exc=e,
        )
        finish_step(
            event_id=parsed_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="parsed",
            status="error",
            correlation_id=correlation_id,
            error=err,
        )
        # FALLBACK: Use metadata-only ingestion when full content extraction fails
        logger.warning("[Web] Content extraction failed for %s, falling back to metadata-only ingestion", url)
        return await ingest_url_metadata_fallback(
            source_id=source_id,
            twin_id=twin_id,
            url=url,
            provider=provider,
            correlation_id=correlation_id,
            error_message=str(e),
            source_type="web_fallback",
            preferred_title=title if 'title' in locals() else None,
        )

    num_chunks = await process_and_index_text(
        source_id,
        twin_id,
        text,
        metadata_override={"filename": f"Web: {title}"[:240], "type": "web", "url": url},
        provider=provider,
        correlation_id=correlation_id,
    )

    _mark_source_live_resilient(source_id, num_chunks)

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

    return num_chunks


async def ingest_instagram_profile(
    source_id: str,
    twin_id: str,
    url: str,
    correlation_id: str | None = None
) -> int:
    """
    Ingest Instagram profile or post using Dumpling AI.
    Instagram is heavily JavaScript-based and blocks traditional scraping.
    """
    from modules.ingestion_chunking import process_and_index_text

    provider = "instagram"

    # Ensure source row exists
    try:
        supabase.table("sources").upsert({
            "id": source_id,
            "twin_id": twin_id,
            "filename": "Instagram: processing",
            "file_size": 0,
            "content_text": "",
            "status": "processing",
            "citation_url": url,
        }).execute()
    except Exception as e:
        logger.warning("[Instagram] Warning: Failed to upsert source record: %s", e)

    fetch_event_id = start_step(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step="fetching",
        correlation_id=correlation_id,
        message="Fetching Instagram content",
        metadata={"url": url},
    )

    try:
        # Use Firecrawl for Instagram (best-effort -- Instagram often blocks scrapers)
        from modules.firecrawl_client import get_firecrawl_client
        firecrawl = get_firecrawl_client()
        if not firecrawl:
            raise ValueError("Firecrawl not configured")

        logger.info("[Instagram] Using Firecrawl scraping for %s", url)
        log_ingestion_event(source_id, twin_id, "info", "Attempting Firecrawl Instagram scraping")

        fc_result = await firecrawl.scrape_with_retry(url)

        if not fc_result.success or not fc_result.content or len(fc_result.content) < 100:
            raise ValueError(f"Firecrawl returned insufficient Instagram content (quality={fc_result.quality})")

        doc = f"Instagram Profile/Post: {url}\n\n{fc_result.content}"

        logger.info("[Instagram] Extraction successful: %s characters", len(doc))
        log_ingestion_event(source_id, twin_id, "info", f"Instagram extraction successful ({len(doc)} chars)")

        content_hash = calculate_content_hash(doc)

        supabase.table("sources").update({
            "filename": "Instagram: extracted"[:240],
            "file_size": len(doc),
            "content_text": doc,
            "content_hash": content_hash,
            "status": "processing",
            "extracted_text_length": len(doc),
        }).eq("id", source_id).eq("twin_id", twin_id).execute()

        finish_step(
            event_id=fetch_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="fetching",
            status="completed",
            correlation_id=correlation_id,
            metadata={"text_len": len(doc)},
        )

        # Index the content
        num_chunks = await process_and_index_text(
            source_id,
            twin_id,
            doc,
            metadata_override={"filename": "Instagram: extracted", "type": "instagram", "url": url},
            provider=provider,
            correlation_id=correlation_id,
        )

        supabase.table("sources").update({
            "status": "live",
            "chunk_count": num_chunks,
        }).eq("id", source_id).execute()

        return num_chunks

        # If we get here, extraction failed or returned insufficient content
        raise ValueError("Instagram extraction returned insufficient content")

    except Exception as e:
        logger.warning("[Instagram] Extraction failed: %s", e)
        log_ingestion_event(source_id, twin_id, "error", f"Instagram extraction failed: {str(e)[:200]}")

        # Fall back to metadata-only
        finish_step(
            event_id=fetch_event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step="fetching",
            status="error",
            correlation_id=correlation_id,
            error={"message": str(e)},
        )

        return await ingest_url_metadata_fallback(
            source_id=source_id,
            twin_id=twin_id,
            url=url,
            provider=provider,
            correlation_id=correlation_id,
            error_message=str(e),
            source_type="instagram_fallback",
            preferred_title="Instagram Profile",
        )
