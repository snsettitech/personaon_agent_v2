"""VAL-01: Recall gate test for Phase 22 cutover (Pinecone -> pgvector).

This integration test validates that Gemini 768d embeddings + pgvector HNSW
search produce accurate retrieval for known query-chunk pairs.  It acts as a
hard blocker: Phase 22 cutover CANNOT proceed unless >= 4/5 curated pairs
return the expected chunk as the top result.

Requires:
    PGVECTOR_DATABASE_URL  -- direct Supabase connection (port 5432)
    GOOGLE_API_KEY         -- for Gemini embedding generation
    EMBEDDING_TARGET_DIMENSION=768

Usage:
    cd backend && pytest tests/test_vector_recall.py -x -v --tb=short
"""

import os
import logging

import pytest
import pytest_asyncio

from adk_core.services.vector_store import search

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TWIN_ID = "11219c13-1fff-4237-86ab-af0333658938"  # Sainath Setti

RECALL_PAIRS: list[dict[str, str]] = [
    {
        "query": "What did Sainath do at Microsoft?",
        "expected_substring": "six years at",
    },
    {
        "query": "What is PersonaOn AI?",
        "expected_substring": "PersonaOn AI",
    },
    {
        "query": "Who is PersonaOn built for?",
        "expected_substring": "professionals whose expertise",
    },
    {
        "query": "What problem does PersonaOn solve?",
        "expected_substring": "fielding the same questions",
    },
    {
        "query": "What is Sainath's entrepreneurial journey?",
        "expected_substring": "co-founded a",
    },
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _pgvector_available() -> bool:
    """Return True if PGVECTOR_DATABASE_URL is configured."""
    return bool(os.getenv("PGVECTOR_DATABASE_URL"))


@pytest_asyncio.fixture(autouse=True)
async def _check_backfill_done():
    """Skip the entire module if backfill has not been run yet."""
    if not _pgvector_available():
        pytest.skip(
            "PGVECTOR_DATABASE_URL not set -- cannot run recall test"
        )

    from modules.clients import get_pgvector_pool

    pool = await get_pgvector_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM chunks "
            "WHERE embedding IS NOT NULL AND twin_id = $1::uuid",
            TWIN_ID,
        )

    if count == 0:
        pytest.skip(
            "Backfill not yet run -- no embedded chunks found for "
            f"twin_id={TWIN_ID}"
        )

    logger.info(
        "[RecallTest] Found %d embedded chunks for twin_id=%s", count, TWIN_ID
    )


# ---------------------------------------------------------------------------
# Recall validation test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.integration
async def test_vector_recall():
    """Verify >= 4/5 curated query-chunk pairs return expected content.

    Each pair fires a top-1 search against live pgvector.  A "hit" means the
    top result's text contains the expected substring (case-insensitive).
    """
    hits = 0
    details: list[str] = []

    for i, pair in enumerate(RECALL_PAIRS, start=1):
        query = pair["query"]
        expected = pair["expected_substring"].lower()

        results = await search(query, TWIN_ID, top_k=1)

        if results and expected in results[0]["text"].lower():
            hits += 1
            details.append(
                f"  [{i}] HIT  | q={query!r} | "
                f"score={results[0].get('score', '?')}"
            )
        else:
            top_text = (
                results[0]["text"][:120] if results else "<no results>"
            )
            details.append(
                f"  [{i}] MISS | q={query!r} | "
                f"top_text={top_text!r}"
            )

    detail_str = "\n".join(details)
    logger.info(
        "[RecallTest] Result: %d/%d hits\n%s", hits, len(RECALL_PAIRS),
        detail_str,
    )

    assert hits >= 4, (
        f"Recall gate FAILED: {hits}/{len(RECALL_PAIRS)} hits (need >= 4).\n"
        f"Details:\n{detail_str}"
    )
