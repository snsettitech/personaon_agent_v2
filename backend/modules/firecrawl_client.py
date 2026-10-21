"""
Firecrawl Client Module (Phase 3.0)

Production Firecrawl API wrapper with:
- Retry with exponential backoff
- Circuit breaker pattern
- Concurrency limiting
- Firecrawl error mapping to existing failure taxonomy
- Result quality/status model for honest content reporting

Usage:
    client = get_firecrawl_client()
    result = await client.scrape_with_retry(url)
    if result.quality == ContentQuality.FULL:
        # Process full content
    elif result.quality == ContentQuality.PARTIAL:
        # Handle partial extraction (e.g., YouTube description only)
"""

import os
import asyncio
import logging
import time
from typing import Any
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum

# Firecrawl imports
try:
    from firecrawl import FirecrawlApp
    FIRECRAWL_AVAILABLE = True
except ImportError:
    FIRECRAWL_AVAILABLE = False

# Import existing failure taxonomy for error mapping
from modules.crawl_failure_taxonomy import (
    FailureType,
    is_retryable,
    get_failure_category,
)

logger = logging.getLogger(__name__)


class ContentQuality(str, Enum):
    """
    Honest content quality assessment for crawled sources.

    - FULL: Complete content extraction (article body, full page)
    - PARTIAL: Incomplete extraction (metadata only, description without transcript)
    - BLOCKED: Access blocked by robots, gating, or policy
    - MANUAL_NEEDED: Content requires manual upload (video transcript, gated content)
    """
    FULL = "full"
    PARTIAL = "partial"
    BLOCKED = "blocked"
    MANUAL_NEEDED = "manual_needed"


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass
class FirecrawlResult:
    """
    Standardized Firecrawl result with quality assessment.

    Attributes:
        success: Whether the operation succeeded
        url: The URL that was crawled/scraped
        content: Extracted content (markdown/html)
        metadata: Page metadata (title, description, etc.)
        quality: Content quality assessment
        quality_reason: Explanation for quality rating
        http_status: HTTP status code if available
        firecrawl_status: Raw Firecrawl status
        links: Discovered links (for crawl operations)
        error: Error information if failed
        attempts: Number of retry attempts made
        duration_ms: Operation duration in milliseconds
    """
    success: bool
    url: str
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    quality: ContentQuality = ContentQuality.FULL
    quality_reason: str = ""
    http_status: int | None = None
    firecrawl_status: str | None = None
    links: list[str] = field(default_factory=list)
    error: dict[str, Any] | None = None
    attempts: int = 0
    duration_ms: int = 0

    def to_failure_artifact(self, crawl_id: str, page_id: str | None = None) -> dict[str, Any] | None:
        """Convert failed result to failure artifact for taxonomy."""
        if self.success:
            return None
        from modules.crawl_failure_taxonomy import create_failure_artifact, FailureStage

        # Get stage from error, default to FETCH
        stage = self.error.get("stage", FailureStage.FETCH)
        if isinstance(stage, str):
            # Convert string to enum if needed
            stage = FailureStage(stage)

        return create_failure_artifact(
            url=self.url,
            canonical_url=self.url,
            crawl_id=crawl_id,
            crawl_page_id=page_id,
            failure_type=self.error.get("failure_type", FailureType.NETWORK),
            error_detail=self.error.get("detail", "Unknown error"),
            stage=stage,
            metadata={
                "http_status": self.http_status,
                "firecrawl_status": self.firecrawl_status,
                "quality": self.quality.value,
                "attempts": self.attempts,
            }
        )


@dataclass
class FirecrawlConfig:
    """Configuration for Firecrawl client."""
    api_key: str
    base_url: str = "https://api.firecrawl.dev"
    timeout_seconds: int = 60
    max_retries: int = 3
    retry_backoff_base: float = 2.0
    max_concurrent: int = 5

    # Circuit breaker settings
    circuit_failure_threshold: int = 5
    circuit_recovery_timeout: int = 30

    # Source-type defaults
    website_crawl_limit: int = 50
    website_max_depth: int = 3
    scrape_formats: list[str] = field(default_factory=lambda: ["markdown"])
    max_content_chars: int = 500000
    max_metadata_chars: int = 8000

    @classmethod
    def from_env(cls) -> "FirecrawlConfig":
        """Load configuration from environment variables."""
        return cls(
            api_key=os.getenv("FIRECRAWL_API_KEY", ""),
            base_url=os.getenv("FIRECRAWL_BASE_URL", "https://api.firecrawl.dev"),
            timeout_seconds=int(os.getenv("FIRECRAWL_TIMEOUT_SECONDS", "60")),
            max_retries=int(os.getenv("FIRECRAWL_MAX_RETRIES", "3")),
            retry_backoff_base=float(os.getenv("FIRECRAWL_RETRY_BACKOFF_BASE", "2.0")),
            max_concurrent=int(os.getenv("FIRECRAWL_MAX_CONCURRENT", "5")),
            circuit_failure_threshold=int(os.getenv("FIRECRAWL_CIRCUIT_FAILURE_THRESHOLD", "5")),
            circuit_recovery_timeout=int(os.getenv("FIRECRAWL_CIRCUIT_RECOVERY_TIMEOUT", "30")),
            website_crawl_limit=int(os.getenv("FIRECRAWL_WEBSITE_CRAWL_LIMIT", "50")),
            website_max_depth=int(os.getenv("FIRECRAWL_WEBSITE_MAX_DEPTH", "3")),
            max_content_chars=max(0, int(os.getenv("FIRECRAWL_MAX_CONTENT_CHARS", "500000"))),
            max_metadata_chars=max(0, int(os.getenv("FIRECRAWL_MAX_METADATA_CHARS", "8000"))),
        )

    def is_configured(self) -> bool:
        """Check if Firecrawl is properly configured."""
        return bool(self.api_key) and FIRECRAWL_AVAILABLE


class CircuitBreaker:
    """
    Simple circuit breaker for Firecrawl API calls.

    - CLOSED: Normal operation, requests pass through
    - OPEN: Too many failures, requests rejected immediately
    - HALF_OPEN: Testing if service recovered
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 30):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: float | None = None
        self._lock = asyncio.Lock()

    async def call(self, func, *args, **kwargs):
        """Execute function with circuit breaker protection."""
        async with self._lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    logger.info("Circuit breaker entering HALF_OPEN state")
                else:
                    raise CircuitBreakerOpen("Circuit breaker is OPEN")

        try:
            result = await func(*args, **kwargs)
            async with self._lock:
                self._on_success()
            return result
        except Exception:
            async with self._lock:
                self._on_failure()
            raise

    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to try recovery."""
        if self.last_failure_time is None:
            return True
        return (time.time() - self.last_failure_time) >= self.recovery_timeout

    def _on_success(self):
        """Handle successful call."""
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            self.failure_count = 0
            logger.info("Circuit breaker CLOSED (recovered)")

    def _on_failure(self):
        """Handle failed call."""
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            logger.warning("Circuit breaker OPEN (still failing)")
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(f"Circuit breaker OPEN after {self.failure_count} failures")


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is open."""
    pass


class FirecrawlClient:
    """
    Production Firecrawl client wrapper.

    Features:
    - Retry with exponential backoff
    - Circuit breaker for cascading failure protection
    - Concurrency limiting via semaphore
    - Error mapping to existing failure taxonomy
    - Result quality assessment
    """

    def __init__(self, config: FirecrawlConfig):
        self.config = config
        self._apps: list[FirecrawlApp] = []
        self._app_index: int = 0
        self._circuit = CircuitBreaker(
            failure_threshold=config.circuit_failure_threshold,
            recovery_timeout=config.circuit_recovery_timeout
        )
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._initialized = False

    @property
    def app(self) -> FirecrawlApp:
        """Get next FirecrawlApp, round-robining across all configured API keys."""
        if not self._apps:
            if not FIRECRAWL_AVAILABLE:
                raise ImportError("firecrawl-py not installed. Run: pip install firecrawl-py")
            if not self.config.api_key:
                raise ValueError("FIRECRAWL_API_KEY not configured")
            keys: list[str] = [self.config.api_key]
            for i in range(2, 12):
                k = os.getenv(f"FIRECRAWL_API_KEY_{i}", "")
                if k:
                    keys.append(k)
            self._apps = [FirecrawlApp(api_key=k) for k in keys]
            self._initialized = True
            logger.info("FirecrawlClient initialized with %d API key(s)", len(self._apps))
        app = self._apps[self._app_index % len(self._apps)]
        self._app_index = (self._app_index + 1) % len(self._apps)
        return app

    def _map_exception_to_failure_type(self, error: Exception) -> FailureType:
        """
        Map Firecrawl/Python exceptions to existing failure taxonomy.

        Mapping:
        - 429 Too Many Requests -> RATE_LIMIT (retryable)
        - 403 Forbidden -> AUTH or GATING (non-retryable)
        - 5xx errors -> UNAVAILABLE (retryable)
        - Timeout -> TIMEOUT (retryable)
        - Network/DNS/SSL -> NETWORK (retryable)
        - Size exceeded -> SIZE_EXCEEDED (non-retryable)
        - Parser errors -> PARSER_FAIL (non-retryable)
        - Robots blocked -> GATING (non-retryable)
        """
        error_str = str(error).lower()
        _ = type(error).__name__

        # Check for HTTP status codes in error message
        if "429" in error_str or "too many requests" in error_str:
            return FailureType.RATE_LIMIT

        if "403" in error_str or "forbidden" in error_str:
            # Distinguish auth vs gating
            if any(x in error_str for x in ["bot", "captcha", "cloudflare", "blocked"]):
                return FailureType.GATING
            return FailureType.AUTH

        if "401" in error_str or "unauthorized" in error_str:
            return FailureType.AUTH

        # Permanent platform/domain limitations - don't burn retries.
        if any(
            token in error_str
            for token in (
                "website not supported",
                "we do not support this site",
                "domain not supported",
            )
        ):
            return FailureType.GATING

        if "5" in error_str[:3] or "server error" in error_str:
            return FailureType.UNAVAILABLE

        if "timeout" in error_str or "timed out" in error_str:
            return FailureType.TIMEOUT

        # DNS resolution failures for missing/invalid hostnames are typically permanent.
        if any(
            x in error_str
            for x in [
                "dns resolution failed for hostname",
                "name or service not known",
                "nodename nor servname provided",
                "no such host",
                "domain does not exist",
            ]
        ):
            return FailureType.INVALID_HOSTNAME

        if any(x in error_str for x in ["dns", "connection", "network", "ssl", "certificate", "tls"]):
            return FailureType.NETWORK

        if any(x in error_str for x in ["size", "too large", "exceed"]):
            return FailureType.SIZE_EXCEEDED

        if any(x in error_str for x in ["parse", "decode", "json", "xml", "encoding"]):
            return FailureType.PARSER_FAIL

        if any(x in error_str for x in ["robots", "disallowed", "policy"]):
            return FailureType.GATING

        # Circuit breaker open is a special case
        if isinstance(error, CircuitBreakerOpen):
            return FailureType.UNAVAILABLE

        # Default to network for unknown errors
        return FailureType.NETWORK

    def _assess_content_quality(
        self,
        content: str,
        metadata: dict[str, Any],
        error: Exception | None
    ) -> tuple[ContentQuality, str]:
        """
        Assess content quality for honest reporting.

        Returns:
            Tuple of (quality, reason)
        """
        if error:
            error_str = str(error).lower()

            # Check for gating/blocks
            if any(x in error_str for x in ["robots", "blocked", "forbidden", "captcha", "gating"]):
                return ContentQuality.BLOCKED, f"Access blocked: {error}"

            # Check for content type issues that might need manual handling
            if any(x in error_str for x in ["video", "youtube", "transcript unavailable"]):
                return ContentQuality.MANUAL_NEEDED, "Video content requires manual transcript upload"

            # General failure
            return ContentQuality.BLOCKED, f"Extraction failed: {error}"

        # No error - assess content completeness
        content_length = len(content.strip())

        # Empty or very short content
        if content_length < 100:
            # Check if we have metadata at least
            if metadata.get("title") or metadata.get("description"):
                return ContentQuality.PARTIAL, "Minimal content extracted, metadata only"
            return ContentQuality.BLOCKED, "No meaningful content extracted"

        # Short content might be partial
        if content_length < 500:
            # Check for indicators of partial extraction
            if metadata.get("sourceURL") and "youtube" in metadata.get("sourceURL", "").lower():
                return ContentQuality.PARTIAL, "YouTube description only (video content not extracted)"
            if "linkedin" in metadata.get("sourceURL", "").lower():
                return ContentQuality.PARTIAL, "LinkedIn partial extraction (gating likely)"

        # Full content
        return ContentQuality.FULL, f"Full content extracted ({content_length} chars)"

    def _truncate_content_if_needed(self, content: str, url: str) -> tuple[str, bool]:
        """
        Truncate very large page bodies to avoid memory pressure on small instances.

        Returns:
            (content, was_truncated)
        """
        max_chars = self.config.max_content_chars
        if max_chars > 0 and len(content) > max_chars:
            logger.warning(
                "Truncating content for %s from %d to %d chars",
                url,
                len(content),
                max_chars,
            )
            return content[:max_chars], True
        return content, False

    def _compact_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """
        Keep metadata payload bounded to avoid retaining unexpectedly large blobs.
        """
        if not isinstance(metadata, dict):
            return {}

        max_chars = self.config.max_metadata_chars
        compact: dict[str, Any] = {}
        for key, value in metadata.items():
            if isinstance(value, str):
                compact[key] = value[:max_chars] if max_chars > 0 else value
            elif isinstance(value, (int, float, bool)) or value is None:
                compact[key] = value
            elif isinstance(value, list):
                trimmed = value[:25]
                if max_chars > 0:
                    compact[key] = [
                        item[:max_chars] if isinstance(item, str) else item
                        for item in trimmed
                    ]
                else:
                    compact[key] = trimmed
            elif isinstance(value, dict):
                # Keep nested object shallow and bounded.
                nested: dict[str, Any] = {}
                for idx, (nested_key, nested_value) in enumerate(value.items()):
                    if idx >= 25:
                        break
                    if isinstance(nested_value, str) and max_chars > 0:
                        nested[nested_key] = nested_value[:max_chars]
                    elif isinstance(nested_value, (int, float, bool)) or nested_value is None:
                        nested[nested_key] = nested_value
                    else:
                        nested[nested_key] = str(nested_value)[:max_chars] if max_chars > 0 else str(nested_value)
                compact[key] = nested
            else:
                compact[key] = str(value)[:max_chars] if max_chars > 0 else str(value)
        return compact

    async def scrape_with_retry(
        self,
        url: str,
        formats: list[str] | None = None,
        max_retries: int | None = None
    ) -> FirecrawlResult:
        """
        Scrape a single URL with retry logic.

        Args:
            url: URL to scrape
            formats: Output formats (default: ["markdown"])
            max_retries: Override default max retries

        Returns:
            FirecrawlResult with quality assessment
        """
        formats = formats or self.config.scrape_formats
        max_retries = max_retries or self.config.max_retries

        start_time = time.time()
        last_error = None
        attempts = 0

        async with self._semaphore:
            for attempt in range(max_retries + 1):
                attempts = attempt + 1
                try:
                    # Use circuit breaker
                    result = await self._circuit.call(
                        self._do_scrape, url, formats
                    )

                    duration_ms = int((time.time() - start_time) * 1000)
                    result.attempts = attempts
                    result.duration_ms = duration_ms

                    logger.info(f"Successfully scraped {url} in {duration_ms}ms (attempt {attempts})")
                    return result

                except Exception as e:
                    last_error = e
                    failure_type = self._map_exception_to_failure_type(e)

                    if not is_retryable(failure_type) or attempt >= max_retries:
                        break

                    # Calculate backoff
                    backoff = self.config.retry_backoff_base ** attempt
                    logger.warning(f"Scrape attempt {attempts} failed for {url}: {e}. Retrying in {backoff}s...")
                    await asyncio.sleep(backoff)

        # All retries exhausted
        duration_ms = int((time.time() - start_time) * 1000)
        failure_type = self._map_exception_to_failure_type(last_error)

        logger.error(f"Failed to scrape {url} after {attempts} attempts: {last_error}")

        return FirecrawlResult(
            success=False,
            url=url,
            error={
                "failure_type": failure_type,
                "category": get_failure_category(failure_type).value,
                "detail": str(last_error),
                "retryable": is_retryable(failure_type),
            },
            quality=ContentQuality.BLOCKED,
            quality_reason=f"Failed after {attempts} attempts: {last_error}",
            attempts=attempts,
            duration_ms=duration_ms,
        )

    async def _do_scrape(self, url: str, formats: list[str]) -> FirecrawlResult:
        """Execute actual scrape (called within circuit breaker)."""
        loop = asyncio.get_event_loop()

        # Run synchronous Firecrawl call in thread pool
        def _scrape():
            # firecrawl-py v2 uses app.scrape(...); keep backward compatibility.
            if hasattr(self.app, "scrape"):
                return self.app.scrape(url, formats=formats)
            return self.app.scrape_url(url, params={"formats": formats})

        result = await asyncio.wait_for(
            loop.run_in_executor(None, _scrape),
            timeout=self.config.timeout_seconds
        )

        # Normalize object/dict responses.
        if hasattr(result, "model_dump"):
            result = result.model_dump()
        elif not isinstance(result, dict):
            result = {
                "markdown": getattr(result, "markdown", ""),
                "html": getattr(result, "html", ""),
                "metadata": getattr(result, "metadata", {}) or {},
                "links": getattr(result, "links", []) or [],
            }

        # Extract content
        content = ""
        if "markdown" in result:
            content = result["markdown"]
        elif "html" in result:
            content = result["html"]

        metadata = self._compact_metadata(result.get("metadata", {}))
        content, was_truncated = self._truncate_content_if_needed(content, url)

        # Assess quality
        quality, quality_reason = self._assess_content_quality(content, metadata, None)
        if was_truncated:
            quality = ContentQuality.PARTIAL
            quality_reason = f"{quality_reason} (truncated to {self.config.max_content_chars} chars)"

        return FirecrawlResult(
            success=True,
            url=url,
            content=content,
            metadata=metadata,
            quality=quality,
            quality_reason=quality_reason,
            http_status=metadata.get("statusCode"),
            firecrawl_status="success",
        )

    async def crawl_with_polling_iter(
        self,
        url: str,
        limit: int | None = None,
        max_depth: int | None = None,
        poll_interval: int = 5
    ) -> AsyncIterator[FirecrawlResult]:
        """
        Start a crawl job and stream page results.

        Args:
            url: Starting URL
            limit: Max pages to crawl
            max_depth: Max crawl depth
            poll_interval: Seconds between status checks

        Yields:
            FirecrawlResult for each crawled page
        """
        limit = limit or self.config.website_crawl_limit
        max_depth = max_depth or self.config.website_max_depth

        async with self._semaphore:
            try:
                # Start crawl
                loop = asyncio.get_event_loop()

                def _start_crawl():
                    # firecrawl-py v2 uses app.crawl(...); keep fallback for old clients.
                    if hasattr(self.app, "crawl"):
                        return self.app.crawl(
                            url,
                            limit=limit,
                            max_discovery_depth=max_depth,
                            scrape_options={"formats": ["markdown"]},
                        )
                    params = {
                        "limit": limit,
                        "maxDepth": max_depth,
                        "scrapeOptions": {"formats": ["markdown"]},
                    }
                    return self.app.crawl_url(url, params=params)

                crawl_result = await asyncio.wait_for(
                    loop.run_in_executor(None, _start_crawl),
                    timeout=self.config.timeout_seconds
                )

                if hasattr(crawl_result, "model_dump"):
                    crawl_result = crawl_result.model_dump()

                # Process results without building a second in-memory list.
                page_count = 0
                data_pages: list[dict[str, Any]] = []
                if isinstance(crawl_result, dict) and isinstance(crawl_result.get("data"), list):
                    data_pages = crawl_result["data"]

                while data_pages:
                    page = data_pages.pop()
                    page_content = page.get("markdown", "")
                    page_metadata = self._compact_metadata(page.get("metadata", {}))
                    page_url = page_metadata.get("sourceURL", url)
                    page_content, was_truncated = self._truncate_content_if_needed(page_content, page_url)

                    quality, quality_reason = self._assess_content_quality(
                        page_content, page_metadata, None
                    )
                    if was_truncated:
                        quality = ContentQuality.PARTIAL
                        quality_reason = (
                            f"{quality_reason} (truncated to {self.config.max_content_chars} chars)"
                        )

                    page_count += 1
                    yield FirecrawlResult(
                        success=True,
                        url=page_url,
                        content=page_content,
                        metadata=page_metadata,
                        quality=quality,
                        quality_reason=quality_reason,
                        http_status=page_metadata.get("statusCode"),
                    )

                if isinstance(crawl_result, dict):
                    crawl_result.clear()

                logger.info(f"Crawl of {url} completed: {page_count} pages")

            except Exception as e:
                logger.error(f"Crawl failed for {url}: {e}")
                failure_type = self._map_exception_to_failure_type(e)
                yield FirecrawlResult(
                    success=False,
                    url=url,
                    error={
                        "failure_type": failure_type,
                        "detail": str(e),
                    },
                    quality=ContentQuality.BLOCKED,
                    quality_reason=f"Crawl failed: {e}",
                )

    async def crawl_with_polling(
        self,
        url: str,
        limit: int | None = None,
        max_depth: int | None = None,
        poll_interval: int = 5
    ) -> list[FirecrawlResult]:
        """
        Backward-compatible crawl API that collects streamed page results.
        """
        results: list[FirecrawlResult] = []
        async for result in self.crawl_with_polling_iter(
            url=url,
            limit=limit,
            max_depth=max_depth,
            poll_interval=poll_interval,
        ):
            results.append(result)
        return results

    async def search(
        self,
        query: str,
        limit: int = 10,
    ) -> list[str]:
        """
        Search the web via Firecrawl /search API.
        Returns list of URLs from search results (no scrape).

        Args:
            query: Search query (e.g. full name, "John Smith")
            limit: Max results (default 10, max 100)

        Returns:
            List of URLs from search results
        """
        if not query or not str(query).strip():
            return []
        limit = min(max(1, limit), 100)
        async with self._semaphore:
            try:
                loop = asyncio.get_event_loop()

                def _search():
                    return self.app.search(str(query).strip(), limit=limit)

                result = await asyncio.wait_for(
                    loop.run_in_executor(None, _search),
                    timeout=self.config.timeout_seconds,
                )
                urls: list[str] = []

                # Normalize object/dict responses across Firecrawl SDK versions.
                if hasattr(result, "model_dump"):
                    result = result.model_dump()

                items: list[Any] = []
                if result and isinstance(result, dict):
                    # Legacy shape: {"data": [...]}
                    if isinstance(result.get("data"), list):
                        items.extend(result["data"])
                    # v2 shape: {"web": [...], "news": [...], "images": ...}
                    if isinstance(result.get("web"), list):
                        items.extend(result["web"])
                    if isinstance(result.get("news"), list):
                        items.extend(result["news"])
                elif result and hasattr(result, "data") and isinstance(result.data, list):
                    items.extend(result.data)

                for item in items:
                    url = item.get("url") if isinstance(item, dict) else getattr(item, "url", None)
                    if url and str(url).startswith(("http://", "https://")):
                        urls.append(str(url))

                # Deduplicate while preserving order.
                deduped_urls: list[str] = []
                seen: set[str] = set()
                for url in urls:
                    if url not in seen:
                        seen.add(url)
                        deduped_urls.append(url)

                logger.info(f"Firecrawl search '{query[:50]}...' returned {len(deduped_urls)} URLs")
                return deduped_urls
            except Exception as e:
                logger.warning(f"Firecrawl search failed for '{query[:50]}': {e}")
                return []


# Global client instance (lazy-loaded)
_firecrawl_client: FirecrawlClient | None = None


def get_firecrawl_client() -> FirecrawlClient | None:
    """
    Get the global Firecrawl client instance.

    Returns:
        FirecrawlClient if configured, None otherwise
    """
    global _firecrawl_client
    if _firecrawl_client is None:
        config = FirecrawlConfig.from_env()
        if config.is_configured():
            _firecrawl_client = FirecrawlClient(config)
            logger.info("Firecrawl client initialized")
        else:
            logger.warning("Firecrawl not configured (FIRECRAWL_API_KEY missing)")
    return _firecrawl_client


def reset_firecrawl_client():
    """Reset the global client (useful for testing)."""
    global _firecrawl_client
    _firecrawl_client = None
