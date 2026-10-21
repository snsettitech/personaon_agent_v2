"""Agent-callable search and scrape tools for the research pipeline.

These are FunctionTools that the research strategist agent calls directly.
The agent decides WHAT to search and WHICH pages to scrape.
Code handles the API calls and filtering.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from google.adk.tools import ToolContext

from adk_core.state_keys import AppKey, TempKey
from adk_core.tools._common import accumulate_json_list, url_source_id

logger = logging.getLogger(__name__)


async def web_search(
    query: str,
    num_results: int = 8,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """
    Search the web for information about a person.

    Args:
        query: Search query. Include the person's name and organization
               for best results. Example: '"Chris Carder" "Schulich"'
        num_results: How many results to return (3-15).
    """
    from modules.research_claim_web_search import create_search_provider_with_fallback

    provider = create_search_provider_with_fallback()
    num_results = max(3, min(num_results, 15))

    results = await provider.search(query, num_results=num_results)

    formatted = [
        {"index": idx, "url": r.url, "title": r.title or "", "snippet": (r.snippet or "")[:400]}
        for idx, r in enumerate(results, 1)
    ]

    if tool_context:
        accumulate_json_list(tool_context, TempKey.SEARCH_RESULTS_JSON, formatted, dedup_field="url")

    return {"status": "success", "result_count": len(formatted), "results": formatted}


async def news_search(
    query: str,
    num_results: int = 5,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """
    Search for recent news articles, press releases, and media mentions.

    Args:
        query: Person's name with company or topic.
        num_results: How many articles to return (3-10).
    """
    from modules.research_claim_web_search import create_search_provider_with_fallback

    provider = create_search_provider_with_fallback()
    num_results = max(3, min(num_results, 10))

    try:
        results = await provider.search(query, num_results=num_results, category="news")
    except Exception:
        results = await provider.search(f"{query} news OR press release", num_results=num_results)

    formatted = [
        {"index": idx, "url": r.url, "title": r.title or "", "snippet": (r.snippet or "")[:400]}
        for idx, r in enumerate(results, 1)
    ]

    if tool_context:
        accumulate_json_list(tool_context, TempKey.SEARCH_RESULTS_JSON, formatted, dedup_field="url")

    return {"status": "success", "result_count": len(formatted), "results": formatted}


def _validate_scrape_url(url: str) -> None:
    """Block SSRF: reject private IPs, non-HTTP schemes, and internal hosts."""
    import ipaddress as _ipaddress
    import urllib.parse

    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Blocked scheme: {parsed.scheme}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("Empty hostname")

    BLOCKED_HOSTS = {"localhost", "metadata.google.internal", "169.254.169.254"}
    if host in BLOCKED_HOSTS:
        raise ValueError(f"Blocked host: {host}")

    # AUDIT FIX (W9d CRITICAL): the previous try/except swallowed BOTH the
    # ValueError from ip_address() on a hostname (intended: not an IP,
    # allow) AND the explicit ValueError raised when a parsed IP was
    # private (NOT intended: the block was bypassed). A URL like
    # http://10.0.0.1/ would slip through. Now we separate the two
    # cases via try/except/else so the explicit block re-raises.
    try:
        addr = _ipaddress.ip_address(host)
    except ValueError:
        addr = None  # hostname, not an IP literal — allow
    if addr is not None and (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
    ):
        raise ValueError(f"Blocked private/loopback IP: {host}")


async def scrape_page(
    url: str,
    tool_context: ToolContext = None,
) -> dict[str, Any]:
    """
    Scrape a web page and extract its text content.

    Args:
        url: The URL to scrape. Choose URLs that look like interviews,
             profile pages, or detailed articles — not directory listings.
    """
    try:
        _validate_scrape_url(url)
    except ValueError as e:
        return {"status": "blocked", "url": url, "reason": str(e)}

    from modules.firecrawl_client import get_firecrawl_client

    MAX_CHARS = 50000

    firecrawl = get_firecrawl_client()
    if not firecrawl:
        return {"status": "error", "error_message": "Firecrawl not configured"}

    try:
        result = await firecrawl.scrape_with_retry(url)
    except Exception as e:
        return {"status": "error", "error_message": f"Scrape failed: {e}", "url": url}

    if not result or not result.success:
        return {"status": "error", "error_message": "Page could not be scraped", "url": url}

    text = (result.content or "")[:MAX_CHARS]
    text_lower = text.lower()
    source_id = url_source_id(url, 0)

    # Get the subject name we're researching
    subject_name = ""
    confirmed_org = ""
    if tool_context:
        subject_name = str(tool_context.state.get(AppKey.SUBJECT_NAME, "")).strip()
        confirmed_org = str(tool_context.state.get(AppKey.RESEARCH_COMPANY, "")).strip()

    # Name-match check: reject pages about a DIFFERENT person
    name_parts = [p.lower().strip() for p in subject_name.split() if len(p.strip()) > 1]
    subject_mentioned = not name_parts  # if no name, skip check
    if name_parts:
        last_name = name_parts[-1]
        subject_mentioned = last_name in text_lower

    wrong_person = False
    if subject_mentioned and name_parts and len(name_parts) >= 2:
        full_name_lower = subject_name.lower()
        correct_count = text_lower.count(full_name_lower)
        if correct_count == 0:
            subject_mentioned = False
            wrong_person = True

    if wrong_person:
        return {
            "status": "skipped",
            "url": url,
            "reason": f"Page does not mention '{subject_name}' by full name — likely about a different person.",
            "preview": text[:200],
        }

    # Org filter
    org_mentioned = True
    if confirmed_org:
        org_terms = [t.strip().lower() for t in confirmed_org.split(",") if len(t.strip()) > 2]
        org_mentioned = any(term in text_lower for term in org_terms)

    # Accumulate scraped sources in state
    if tool_context:
        raw = tool_context.state.get(TempKey.SCRAPED_SOURCES_JSON, "[]")
        # Seed from preloaded sources (app: key survives session DB reload; temp: does not)
        if not raw or raw.strip() in ("[]", ""):
            from adk_core.state_keys import AppKey as _AppKey
            raw = tool_context.state.get(_AppKey.PRELOADED_SOURCES_JSON, "[]")
            tool_context.state[TempKey.SCRAPED_SOURCES_JSON] = raw
        sources = json.loads(raw)
        source_row = {
            "source_id": source_id,
            "url": url,
            "title": str((getattr(result, "metadata", None) or {}).get("title") or ""),
            "extracted_text": text,
            "quality": result.quality.value if hasattr(result, "quality") else "scraped",
            "org_mentioned": org_mentioned,
            "subject_mentioned": subject_mentioned,
        }
        existing_idx = next((idx for idx, entry in enumerate(sources) if entry.get("url") == url), None)
        if existing_idx is None:
            sources.append(source_row)
        else:
            current = sources[existing_idx]
            current_text = str(current.get("extracted_text") or "")
            if len(text) >= len(current_text):
                sources[existing_idx] = {**current, **source_row}
        tool_context.state[TempKey.SCRAPED_SOURCES_JSON] = json.dumps(sources)

    return {
        "status": "success",
        "url": url,
        "chars": len(text),
        "org_mentioned": org_mentioned,
        "subject_mentioned": subject_mentioned,
        "preview": text[:300],
    }
