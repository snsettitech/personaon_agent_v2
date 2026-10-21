"""Contract tests for the vector pipeline.

These tests encode invariants that, if broken, would immediately fail CI —
closing the gap that let Phase 30 ship with a latent 768/3072 dimension
mismatch and a stray `search_chunks` overload.

Every test here exists to block a class of regression that already happened
once in this codebase. Treat as load-bearing; don't weaken the assertions.

Fast by design:
  * No LLM calls (embeddings are resolved via the env-var-driven dimension
    resolver, not generated).
  * No live DB calls (migrations are grep-asserted from disk).
Run via `pytest tests/test_vector_pipeline_contract.py -q`.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Dimension contract — the 232b44e / Apr 12 regression
# ---------------------------------------------------------------------------

EXPECTED_EMBEDDING_DIMENSION = 768
"""pgvector column `chunks.embedding` is declared vector(768).
If this ever changes, update both the migration AND every service's
EMBEDDING_TARGET_DIMENSION env var in the same commit.
"""


def test_resolve_target_dimension_respects_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_resolve_target_dimension()` must return the env value verbatim.

    Regression guard: commit 232b44e removed the Pinecone fallback and made
    this env var the sole source of truth. A worker deploying without it
    silently defaults to 3072-d (Gemini's native size), which then crashes
    at SELECT time against the 768-d column.
    """
    from modules import embeddings

    # Clear the lru_cache so the test re-reads the env var.
    embeddings._resolve_target_dimension.cache_clear()

    monkeypatch.setenv("EMBEDDING_TARGET_DIMENSION", str(EXPECTED_EMBEDDING_DIMENSION))
    assert embeddings._resolve_target_dimension() == EXPECTED_EMBEDDING_DIMENSION


def test_resolve_target_dimension_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the env var is missing, the resolver must return None.

    This is *intentional* — Gemini will default to 3072-d, which is the
    WRONG answer for this codebase. The boot-time env-var check in
    worker.py is what catches this in practice; this test just pins the
    behavior so the fallback can't be silently re-added without a test
    update.
    """
    from modules import embeddings

    embeddings._resolve_target_dimension.cache_clear()
    monkeypatch.delenv("EMBEDDING_TARGET_DIMENSION", raising=False)
    monkeypatch.delenv("PINECONE_INDEX_NAME", raising=False)
    assert embeddings._resolve_target_dimension() is None


# ---------------------------------------------------------------------------
# SQL-call contract — the 4181e75 / search_chunks ambiguity regression
# ---------------------------------------------------------------------------

def test_vector_store_calls_5_arg_search_chunks() -> None:
    """The Python SQL must send 5 args with the explicit text[] cast.

    Regression guard: 20260421_search_chunks_tiers.sql added a new 5-arg
    overload alongside the 3-arg form. If anyone reverts vector_store.search
    to `search_chunks($1, $2, $3)`, Postgres will raise AmbiguousFunctionError
    on every query. Instead of waiting for a live meeting to discover this,
    we just grep the source file.
    """
    vs_source = Path(__file__).resolve().parents[1] / "adk_core" / "services" / "vector_store.py"
    content = vs_source.read_text(encoding="utf-8")

    # The 5-arg form with explicit text[] cast on the last positional param.
    assert "search_chunks($1::vector, $2::uuid, $3, $4, $5::text[])" in content, (
        "vector_store.search() must call the 5-arg search_chunks signature"
    )
    assert "search_chunks_global($1::vector, $2::uuid[], $3, $4, $5::text[])" in content, (
        "vector_store.search_global() must call the 5-arg search_chunks_global signature"
    )


# ---------------------------------------------------------------------------
# Migration-hygiene contract — every new search_chunks CREATE needs a DROP
# ---------------------------------------------------------------------------

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "supabase" / "migrations"


def test_all_search_chunks_overloads_have_matching_drops() -> None:
    """A migration that introduces a new `search_chunks*` signature must
    also be accompanied (in the same file or an earlier file) by a
    `DROP FUNCTION IF EXISTS` for the superseded overload.

    Regression guard: 20260421_search_chunks_tiers.sql shipped a 5-arg
    search_chunks that collided with the pre-existing 3-arg, and a 5-arg
    search_chunks_global that collided with the 4-arg. The collision was
    only caught at runtime on the first live meeting. A separate
    20260422_drop_legacy_search_chunks_overloads.sql now cleans that up;
    this test keeps it that way.
    """
    if not MIGRATIONS_DIR.exists():
        pytest.skip("migrations directory not present in this checkout")

    sql_text = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in sorted(MIGRATIONS_DIR.glob("*.sql"))
    )

    # Both overloads that Phase 30-A added must be dropped somewhere.
    expected_drops = [
        r"DROP FUNCTION IF EXISTS search_chunks\(vector, uuid, integer\)",
        r"DROP FUNCTION IF EXISTS search_chunks_global\(vector, uuid\[\], integer, integer\)",
    ]
    for pattern in expected_drops:
        assert re.search(pattern, sql_text, flags=re.IGNORECASE), (
            f"Missing cleanup migration. Expected SQL matching: {pattern!r}"
        )
