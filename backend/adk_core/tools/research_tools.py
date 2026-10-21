"""Research gathering tools for ADK."""

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

from google.adk.tools import ToolContext

from adk_core.tools._common import url_source_id
from modules.firecrawl_client import FirecrawlResult, get_firecrawl_client
from modules.research_claim_web_search import SearchResult, create_search_provider_with_fallback

MAX_RESEARCH_RESULTS = max(2, min(int(os.getenv("ADK_RESEARCH_MAX_RESULTS", "12")), 20))
MAX_RESEARCH_SCRAPES = max(1, min(int(os.getenv("ADK_RESEARCH_MAX_SCRAPES", "10")), 15))
MAX_SOURCE_TEXT_CHARS = max(300, min(int(os.getenv("ADK_RESEARCH_MAX_SOURCE_TEXT_CHARS", "4000")), 8000))
MAX_SNIPPET_CHARS = max(160, min(int(os.getenv("ADK_RESEARCH_MAX_SNIPPET_CHARS", "500")), 1200))
MAX_QUOTE_CANDIDATES = max(3, min(int(os.getenv("ADK_RESEARCH_MAX_QUOTE_CANDIDATES", "12")), 20))


def _quote_candidates(source_id: str, text: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for match in re.findall(r"\"([^\"]{25,280})\"", text or ""):
        quote = re.sub(r"\s+", " ", match).strip()
        if len(quote.split()) < 5:
            continue
        results.append(
            {
                "quote": quote,
                "source_id": source_id,
                "confidence": 0.65,
                "context": quote[:180],
            }
        )
        if len(results) >= 4:
            break
    return results


def _research_queries(
    *,
    subject_name: str,
    location: str = "",
    company: str = "",
    website: str = "",
    anchored_identity: bool = False,
) -> list[str]:
    base: list[str] = []

    if anchored_identity and company:
        # Start from the trusted anchor and expand within that org context.
        base.append(f'"{subject_name}" "{company}"')
        base.append(f"{subject_name} {company}")
        base.append(f"{subject_name} {company} interview OR podcast OR keynote")
        base.append(f"{subject_name} {company} news OR announcement OR press release")
        base.append(f"{subject_name} {company} career OR background OR founder")
        if website:
            domain = website.replace("https://", "").replace("http://", "").strip("/")
            base.append(f"{subject_name} site:{domain}")
        if location:
            base.append(f"{subject_name} {company} {location}")
    else:
        # Fallback when we have weaker org/location hints.
        if company:
            base.append(f"{subject_name} {company}")
        if website:
            domain = website.replace("https://", "").replace("http://", "").strip("/")
            base.append(f"{subject_name} site:{domain}")
        if location:
            base.append(f"{subject_name} {location}")
        base.append(subject_name)
        base.append(f"{subject_name} interview OR profile OR biography")
        if company:
            base.append(f'"{subject_name}" "{company}"')

    deduped: list[str] = []
    seen = set()
    for query in base:
        cleaned = re.sub(r"\s+", " ", query).strip()
        if not cleaned or cleaned.lower() in seen:
            continue
        seen.add(cleaned.lower())
        deduped.append(cleaned)
    return deduped[:10]


async def gather_public_research(
    subject_name: str,
    location: str = "",
    company: str = "",
    website: str = "",
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """
    Gather public-source research material for a subject.

    The tool performs bounded web search, scrapes a small set of sources, and
    stores the normalized payload in session state for downstream ADK agents.
    """
    provider = create_search_provider_with_fallback()
    queries = _research_queries(
        subject_name=subject_name,
        location=location,
        company=company,
        website=website,
        anchored_identity=bool(company),
    )

    search_results: list[SearchResult] = []
    for query in queries:
        results = await provider.search(query, num_results=10)
        search_results.extend(results)

    # Build filter terms from company/location hints
    hint_terms = [
        t.strip().lower()
        for t in (company.split(",") if company else []) + ([location] if location else [])
        if t.strip() and len(t.strip()) > 2
    ]

    def _mentions_org(r: SearchResult) -> bool:
        text = ((r.title or "") + " " + (r.snippet or "")).lower()
        return any(term in text for term in hint_terms)

    # Deduplicate by URL
    unique: list[SearchResult] = []
    seen_urls = set()
    for result in search_results:
        if not result.url or result.url in seen_urls:
            continue
        seen_urls.add(result.url)
        unique.append(result)

    if bool(company) and hint_terms:
        # In anchored mode, prefer results that reinforce the same org context.
        # This is a code-level filter, not an LLM instruction.
        matching = [r for r in unique if _mentions_org(r)]
        # If filtering left too few results, add back top non-matching ones
        if len(matching) < 2:
            non_matching = [r for r in unique if not _mentions_org(r)]
            matching.extend(non_matching[:2])
        deduped = matching[:MAX_RESEARCH_RESULTS]
    else:
        # Rank by hint relevance but keep the broader candidate set.
        def _hint_score(r: SearchResult) -> int:
            text = ((r.title or "") + " " + (r.snippet or "")).lower()
            return sum(1 for term in hint_terms if term in text)
        if hint_terms:
            unique.sort(key=_hint_score, reverse=True)
        deduped = unique[:MAX_RESEARCH_RESULTS]

    firecrawl = get_firecrawl_client()
    crawl_payloads: dict[str, FirecrawlResult] = {}
    if firecrawl and deduped:
        scrape_results = await asyncio.gather(
            *[firecrawl.scrape_with_retry(item.url) for item in deduped[:MAX_RESEARCH_SCRAPES]],
            return_exceptions=True,
        )
        for item, scrape_result in zip(deduped[:MAX_RESEARCH_SCRAPES], scrape_results, strict=False):
            if isinstance(scrape_result, Exception):
                continue
            crawl_payloads[item.url] = scrape_result

    source_registry: list[dict[str, Any]] = []
    quote_candidates: list[dict[str, Any]] = []
    for idx, result in enumerate(deduped, start=1):
        source_id = url_source_id(result.url, idx)
        scrape = crawl_payloads.get(result.url)
        extracted_text = ""
        quality = "search_only"
        if scrape and scrape.success:
            extracted_text = (scrape.content or "")[:MAX_SOURCE_TEXT_CHARS]
            quality = scrape.quality.value
            quote_candidates.extend(_quote_candidates(source_id, extracted_text))
        source_registry.append(
            {
                "source_id": source_id,
                "url": result.url,
                "title": result.title,
                "snippet": (result.snippet or "")[:MAX_SNIPPET_CHARS],
                "extracted_text": extracted_text,
                "provider": result.source or getattr(provider, "name", "unknown"),
                "quality": quality,
                "published_at": result.published_date,
            }
        )

    payload = {
        "subject_name": subject_name,
        "queries": queries,
        "source_registry": source_registry,
        "verified_quote_candidates": quote_candidates[:12],
        "gather_stats": {
            "search_provider": getattr(provider, "name", "unknown"),
            "source_count": len(source_registry),
            "scraped_count": len(crawl_payloads),
            "source_text_chars": MAX_SOURCE_TEXT_CHARS,
        },
    }
    if tool_context:
        tool_context.state["gathered_research_json"] = json.dumps(payload)
    return payload
