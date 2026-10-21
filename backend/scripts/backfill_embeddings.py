"""Backfill twin_id and Gemini 768d embeddings on all existing chunk rows.

One-shot idempotent script for Phase 21 (MIGR-01, MIGR-02, MIGR-04).
Safe to re-run: all UPDATE/SELECT use WHERE ... IS NULL guards.

Usage:
    PGVECTOR_DATABASE_URL=... GOOGLE_API_KEY=... EMBEDDING_TARGET_DIMENSION=768 \
        python scripts/backfill_embeddings.py

Requirements:
    - PGVECTOR_DATABASE_URL (port 5432 direct, NOT 6543 pgbouncer)
    - GOOGLE_API_KEY
    - EMBEDDING_TARGET_DIMENSION=768
"""

import asyncio
import logging
import os
import sys
import time

# Allow imports from backend/ root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from adk_core.services.vector_store import _normalize, _vec_to_str  # noqa: E402
from modules.clients import get_pgvector_pool  # noqa: E402
from modules.embeddings import get_embedding  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def _preflight_checks() -> None:
    """Assert required env vars before touching the database."""
    target_dim = os.getenv("EMBEDDING_TARGET_DIMENSION")
    if target_dim != "768":
        logger.error(
            "[Preflight] EMBEDDING_TARGET_DIMENSION must be '768', got %r. "
            "Set EMBEDDING_TARGET_DIMENSION=768 and re-run.",
            target_dim,
        )
        sys.exit(1)

    if not os.getenv("PGVECTOR_DATABASE_URL"):
        logger.error("[Preflight] PGVECTOR_DATABASE_URL is not set.")
        sys.exit(1)

    if not os.getenv("GOOGLE_API_KEY"):
        logger.error("[Preflight] GOOGLE_API_KEY is not set.")
        sys.exit(1)

    logger.info("[Preflight] All env vars validated (dim=768, DB URL set, API key set)")


async def _detect_orphans(conn) -> int:
    """Log orphaned chunks (no matching source row). Diagnostic only."""
    orphan_count = await conn.fetchval(
        "SELECT COUNT(*) FROM chunks c "
        "LEFT JOIN sources s ON c.source_id = s.id "
        "WHERE s.id IS NULL"
    )
    if orphan_count and orphan_count > 0:
        logger.warning(
            "[Orphans] Found %d chunk(s) with no matching source row. "
            "These will have NULL twin_id after backfill.",
            orphan_count,
        )
    else:
        logger.info("[Orphans] No orphaned chunks detected.")
    return orphan_count or 0


async def _backfill_twin_id(conn) -> str:
    """MIGR-02: Backfill twin_id from sources join."""
    result = await conn.execute(
        "UPDATE chunks SET twin_id = s.twin_id "
        "FROM sources s "
        "WHERE chunks.source_id = s.id AND chunks.twin_id IS NULL"
    )
    logger.info("[MIGR-02] twin_id backfill: %s", result)
    return result


async def _backfill_embeddings(conn) -> tuple[int, int]:
    """MIGR-01: Backfill Gemini 768d embeddings on chunks missing them."""
    rows = await conn.fetch(
        "SELECT id, content FROM chunks WHERE embedding IS NULL"
    )
    total = len(rows)
    logger.info("[MIGR-01] %d chunk(s) need embedding", total)

    success = 0
    failed = 0

    for i, row in enumerate(rows, 1):
        chunk_id = row["id"]
        content = row["content"]
        try:
            raw_vec = get_embedding(content)
            vec = _normalize(raw_vec)
            vec_str = _vec_to_str(vec)
            await conn.execute(
                "UPDATE chunks SET embedding = $1::vector WHERE id = $2",
                vec_str,
                chunk_id,
            )
            success += 1
            logger.info(
                "[MIGR-01] Embedded chunk %d/%d id=%s (len=%d)",
                i, total, chunk_id, len(content),
            )
        except Exception as exc:
            failed += 1
            logger.error(
                "[MIGR-01] Failed chunk %d/%d id=%s: %s",
                i, total, chunk_id, exc,
            )

        # Rate-limit Gemini API calls
        time.sleep(0.3)

    logger.info("[MIGR-01] Complete: %d success, %d failed", success, failed)
    return success, failed


async def _post_backfill_assertions(conn) -> bool:
    """MIGR-04: Assert zero NULLs in embedding and twin_id columns."""
    null_embeddings = await conn.fetchval(
        "SELECT COUNT(*) FROM chunks WHERE embedding IS NULL"
    )
    null_twin_ids = await conn.fetchval(
        "SELECT COUNT(*) FROM chunks WHERE twin_id IS NULL"
    )
    total_with_embedding = await conn.fetchval(
        "SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL"
    )

    logger.info(
        "[MIGR-04] Results: null_embeddings=%d, null_twin_ids=%d, total_with_embedding=%d",
        null_embeddings or 0,
        null_twin_ids or 0,
        total_with_embedding or 0,
    )

    if (null_embeddings or 0) > 0 or (null_twin_ids or 0) > 0:
        logger.error(
            "[MIGR-04] FAILED: %d NULL embedding(s), %d NULL twin_id(s). "
            "Investigate and re-run.",
            null_embeddings or 0,
            null_twin_ids or 0,
        )
        return False

    logger.info(
        "[MIGR-04] PASSED: %d chunks fully backfilled, zero NULLs",
        total_with_embedding or 0,
    )
    return True


async def main() -> None:
    """Run the full backfill pipeline."""
    _preflight_checks()

    pool = await get_pgvector_pool()
    async with pool.acquire() as conn:
        # Diagnostic: orphan detection
        await _detect_orphans(conn)

        # Phase 1: twin_id backfill (MIGR-02)
        await _backfill_twin_id(conn)

        # Phase 2: embedding backfill (MIGR-01)
        _success, _failed = await _backfill_embeddings(conn)

        # Phase 3: post-backfill assertions (MIGR-04)
        passed = await _post_backfill_assertions(conn)

    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
