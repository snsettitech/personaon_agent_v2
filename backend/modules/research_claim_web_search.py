"""
Research Claim Web Search Module (Phase 9)

Web search provider abstraction for claim verification.
- Provider abstraction (Exa, Brave, Serper)
- Deterministic mocks for testing
- Returns candidate URLs/snippets for claims

Usage:
    provider = ExaSearchProvider(api_key="...")
    results = await provider.search("Python programming language creator", num_results=5)
"""

import os
import logging
from abc import ABC, abstractmethod
from typing import Any
from dataclasses import dataclass
from datetime import datetime
import contextlib

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Single web search result."""
    url: str
    title: str
    snippet: str
    score: float = 0.0
    published_date: str | None = None
    source: str = ""  # Search provider that returned this


class WebSearchProvider(ABC):
    """Abstract base class for web search providers."""

    @abstractmethod
    async def search(
        self,
        query: str,
        num_results: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """
        Search the web for the given query.

        Args:
            query: Search query string
            num_results: Number of results to return
            **kwargs: Provider-specific options

        Returns:
            List of SearchResult objects
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider name for logging/metrics."""
        pass


class ExaSearchProvider(WebSearchProvider):
    """Exa AI search provider."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("EXA_API_KEY", "")
        self._client = None

    @property
    def name(self) -> str:
        return "exa"

    def _get_client(self):
        """Lazy initialization of Exa client."""
        if self._client is None:
            try:
                from exa_py import Exa
                self._client = Exa(self.api_key)
            except ImportError:
                raise ImportError("exa-py not installed. Run: pip install exa-py")
        return self._client

    async def search(
        self,
        query: str,
        num_results: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """Search using Exa API."""
        if not self.api_key:
            logger.warning("Exa API key not configured")
            return []

        try:
            client = self._get_client()

            # Run synchronous call in thread pool
            import asyncio
            loop = asyncio.get_event_loop()

            category = kwargs.get("category")

            def _search():
                search_kwargs = {"num_results": num_results, "type": "auto"}
                if category:
                    search_kwargs["category"] = category
                return client.search(query, **search_kwargs)

            response = await loop.run_in_executor(None, _search)

            results = []
            for result in response.results:
                text = getattr(result, "text", "") or ""
                highlights = getattr(result, "highlights", None) or []
                highlight_text = " ".join(
                    [item for item in highlights if isinstance(item, str)]
                ).strip()
                results.append(SearchResult(
                    url=result.url,
                    title=result.title or "",
                    snippet=text or highlight_text,
                    score=getattr(result, 'score', 0.0),
                    published_date=getattr(result, 'published_date', None),
                    source="exa"
                ))

            logger.info(f"Exa search returned {len(results)} results for query: {query[:50]}...")
            return results

        except Exception as e:
            logger.error(f"Exa search failed: {e}")
            return []


class BraveSearchProvider(WebSearchProvider):
    """Brave Search API provider."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("BRAVE_API_KEY", "")
        self.base_url = "https://api.search.brave.com/res/v1/web/search"

    @property
    def name(self) -> str:
        return "brave"

    async def search(
        self,
        query: str,
        num_results: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """Search using Brave Search API."""
        if not self.api_key:
            logger.warning("Brave API key not configured")
            return []

        try:
            import aiohttp

            headers = {
                "X-Subscription-Token": self.api_key,
                "Accept": "application/json",
            }

            params = {
                "q": query,
                "count": min(num_results, 20),
                "offset": 0,
                "mkt": "en-US",
                "safesearch": "moderate",
                "text_decorations": False,
                "text_format": "Raw",
            }

            async with aiohttp.ClientSession() as session, session.get(
                self.base_url,
                headers=headers,
                params=params,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    logger.error(f"Brave search failed: {response.status}")
                    return []

                data = await response.json()

                results = []
                for item in data.get("web", {}).get("results", []):
                    results.append(SearchResult(
                        url=item.get("url", ""),
                        title=item.get("title", ""),
                        snippet=item.get("description", ""),
                        score=item.get("score", 0.0),
                        published_date=item.get("age"),
                        source="brave"
                    ))

                logger.info(f"Brave search returned {len(results)} results")
                return results

        except Exception as e:
            logger.error(f"Brave search failed: {e}")
            return []


class SerperSearchProvider(WebSearchProvider):
    """Serper.dev (Google Search API) provider."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or os.getenv("SERPER_API_KEY", "")
        self.base_url = "https://google.serper.dev/search"

    @property
    def name(self) -> str:
        return "serper"

    async def search(
        self,
        query: str,
        num_results: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """Search using Serper API."""
        if not self.api_key:
            logger.warning("Serper API key not configured")
            return []

        try:
            import aiohttp

            headers = {
                "X-API-KEY": self.api_key,
                "Content-Type": "application/json",
            }

            payload = {
                "q": query,
                "num": min(num_results, 10),
            }

            async with aiohttp.ClientSession() as session, session.post(
                self.base_url,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    logger.error(f"Serper search failed: {response.status}")
                    return []

                data = await response.json()

                results = []
                for item in data.get("organic", []):
                    results.append(SearchResult(
                        url=item.get("link", ""),
                        title=item.get("title", ""),
                        snippet=item.get("snippet", ""),
                        score=0.0,  # Serper doesn't provide scores
                        published_date=item.get("date"),
                        source="serper"
                    ))

                logger.info(f"Serper search returned {len(results)} results")
                return results

        except Exception as e:
            logger.error(f"Serper search failed: {e}")
            return []


class MockSearchProvider(WebSearchProvider):
    """
    Mock search provider for testing.
    Returns deterministic results based on query.
    """

    def __init__(self, results: list[SearchResult] | None = None):
        self._results = results or []
        self.search_calls: list[dict[str, Any]] = []

    @property
    def name(self) -> str:
        return "mock"

    async def search(
        self,
        query: str,
        num_results: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """Return mock results."""
        self.search_calls.append({
            "query": query,
            "num_results": num_results,
            "kwargs": kwargs,
            "timestamp": datetime.utcnow().isoformat(),
        })

        # Return configured results, limited to num_results
        return self._results[:num_results]

    def set_results(self, results: list[SearchResult]) -> None:
        """Set mock results for subsequent searches."""
        self._results = results

    def clear_calls(self) -> None:
        """Clear recorded search calls."""
        self.search_calls = []


class FallbackSearchProvider(WebSearchProvider):
    """
    Fallback provider that tries multiple providers in order.
    Returns first successful result set.
    """

    def __init__(self, providers: list[WebSearchProvider]):
        self.providers = providers

    @property
    def name(self) -> str:
        return f"fallback({','.join(p.name for p in self.providers)})"

    async def search(
        self,
        query: str,
        num_results: int = 5,
        **kwargs
    ) -> list[SearchResult]:
        """Try providers in order until one succeeds."""
        for provider in self.providers:
            try:
                results = await provider.search(query, num_results, **kwargs)
                if results:
                    logger.info(f"Search succeeded with provider: {provider.name}")
                    return results
            except Exception as e:
                logger.warning(f"Provider {provider.name} failed: {e}")
                continue

        logger.error("All search providers failed")
        return []


# =============================================================================
# Factory Functions
# =============================================================================

def create_search_provider(
    provider_name: str | None = None,
    api_key: str | None = None
) -> WebSearchProvider:
    """
    Create a search provider by name.

    Args:
        provider_name: 'exa', 'brave', 'serper', or None (auto-detect)
        api_key: Optional API key (otherwise from env)

    Returns:
        WebSearchProvider instance
    """
    provider_name = (provider_name or os.getenv("SEARCH_PROVIDER", "exa")).lower()

    if provider_name == "exa":
        return ExaSearchProvider(api_key)
    if provider_name == "brave":
        return BraveSearchProvider(api_key)
    if provider_name == "serper":
        return SerperSearchProvider(api_key)
    raise ValueError(f"Unknown search provider: {provider_name}")


def create_search_provider_with_fallback(
    preferred: str | None = None
) -> WebSearchProvider:
    """
    Create a fallback provider with multiple search providers.

    Args:
        preferred: Preferred provider name

    Returns:
        FallbackSearchProvider
    """
    providers = []

    # Add preferred first
    if preferred:
        with contextlib.suppress(ValueError):
            providers.append(create_search_provider(preferred))

    # Add others as fallback
    for name in ["exa", "brave", "serper"]:
        if name != preferred:
            try:
                provider = create_search_provider(name)
                # Only add if configured (has API key)
                if hasattr(provider, 'api_key') and provider.api_key:
                    providers.append(provider)
            except (ValueError, ImportError):
                continue

    if not providers:
        logger.warning("No search providers configured")
        # Return mock that returns empty results
        return MockSearchProvider()

    return FallbackSearchProvider(providers)


# =============================================================================
# Query Building
# =============================================================================

def build_claim_search_query(
    claim_text: str,
    claim_type: str | None = None,
    include_verification_terms: bool = True
) -> str:
    """
    Build an effective search query from a claim.

    Args:
        claim_text: The claim text
        claim_type: Optional claim type for context
        include_verification_terms: Add verification-focused terms

    Returns:
        Optimized search query
    """
    # Clean up claim text
    query = claim_text.strip()

    # Remove first-person pronouns for better search
    query = query.replace("I ", "").replace("I'm ", "")
    query = query.replace("My ", "").replace("my ", "")

    # Add verification context for certain claim types
    if include_verification_terms and claim_type:
        if claim_type == "experience":
            query = f"{query} background experience"
        elif claim_type == "belief":
            query = f"{query} opinion stance"

    # Limit length
    if len(query) > 200:
        query = query[:200]

    return query


# =============================================================================
# Convenience Functions
# =============================================================================

async def search_for_claim(
    claim_text: str,
    claim_type: str | None = None,
    num_results: int = 5,
    provider: WebSearchProvider | None = None
) -> list[SearchResult]:
    """
    Convenience function to search for evidence about a claim.

    Args:
        claim_text: The claim to search for
        claim_type: Optional claim type
        num_results: Number of results to return
        provider: Optional search provider (auto-created if None)

    Returns:
        List of SearchResult
    """
    if provider is None:
        provider = create_search_provider_with_fallback()

    query = build_claim_search_query(claim_text, claim_type)
    return await provider.search(query, num_results)
