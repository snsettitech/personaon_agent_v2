"""Test scaffolding for vector_store.py (Plan 02 TDD RED state).

All tests import from adk_core.services.vector_store which does NOT exist yet.
Every test will fail with ImportError — this is intentional.
Plan 02 will create vector_store.py and make these tests pass (GREEN).

Covers: VSTORE-01..08, INFRA-06
"""

import os
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

# These imports will fail until vector_store.py is created in Plan 02
from adk_core.services.vector_store import (
    count_faqs,
    delete_namespace,
    namespace_stats,
    search,
    search_global,
    upsert_faq,
    upsert_text_chunks,
    validate_index,
    _normalize,
)


# ---------------------------------------------------------------------------
# VSTORE-01: Search result shape
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_search_result_shape(mock_pgvector_pool):
    """Search must return dicts with keys: text, score, source_id, filename, url, type.
    Score must be a float rounded to 4 decimal places.
    """
    pool, conn = mock_pgvector_pool

    # Mock rows returned by the search_chunks RPC
    mock_row = {
        "id": uuid.uuid4(),
        "content": "Some chunk text",
        "source_id": uuid.uuid4(),
        "metadata": {"filename": "profile.txt", "url": "https://example.com", "type": "profile"},
        "similarity": 0.87654321,
        "privacy_level": "public",
    }
    conn.fetch = AsyncMock(return_value=[mock_row])

    with patch("adk_core.services.vector_store.get_pgvector_pool", return_value=pool):
        with patch("adk_core.services.vector_store.get_embedding", return_value=[0.1] * 768):
            results = await search("test query", "twin-123", top_k=5)

    assert len(results) == 1
    result = results[0]
    assert set(result.keys()) == {"text", "score", "source_id", "privacy_level", "filename", "url", "type", "source_type"}
    assert isinstance(result["score"], float)
    # Score rounded to 4 decimal places
    assert result["score"] == round(result["score"], 4)


# ---------------------------------------------------------------------------
# VSTORE-02 / VSTORE-07: Upsert normalizes embeddings + ON CONFLICT
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upsert_normalizes(mock_pgvector_pool):
    """Upsert must L2-normalize embeddings before storing.
    SQL must contain ON CONFLICT for idempotent upserts.
    """
    pool, conn = mock_pgvector_pool
    conn.execute = AsyncMock(return_value="INSERT 0 1")

    # Vector [3.0, 4.0, 0...] has norm=5.0, normalized = [0.6, 0.8, 0...]
    raw_embedding = [3.0, 4.0] + [0.0] * 766

    with patch("adk_core.services.vector_store.get_pgvector_pool", return_value=pool):
        with patch("adk_core.services.vector_store.get_embedding", return_value=raw_embedding):
            count = await upsert_text_chunks("Hello world", "twin-123", source="profile")

    assert count >= 1

    # Inspect the SQL and args passed to conn.execute
    call_args = conn.execute.call_args
    sql = call_args[0][0] if call_args[0] else ""
    assert "ON CONFLICT" in sql, "Upsert SQL must contain ON CONFLICT"

    # The embedding arg should be normalized
    # Find the embedding string in the args
    embedding_arg = str(call_args)
    assert "[0.6," in embedding_arg or "0.6" in embedding_arg, (
        "Embedding should be L2-normalized (3/5=0.6)"
    )


# ---------------------------------------------------------------------------
# VSTORE-03: FAQ deterministic ID
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_faq_deterministic_id(mock_pgvector_pool):
    """upsert_faq must produce the same UUID5 for the same question text (case-insensitive)."""
    pool, conn = mock_pgvector_pool
    conn.execute = AsyncMock(return_value="INSERT 0 1")

    twin_id = "twin-abc"
    question = "What is your expertise?"

    with patch("adk_core.services.vector_store.get_pgvector_pool", return_value=pool):
        with patch("adk_core.services.vector_store.get_embedding", return_value=[0.1] * 768):
            id1 = await upsert_faq(question, "AI and ML", twin_id)
            id2 = await upsert_faq(question.upper(), "AI and ML", twin_id)

    assert id1 == id2, "Same question (different case) must produce same UUID5"

    # Verify the UUID5 formula
    expected = str(uuid.uuid5(
        uuid.NAMESPACE_DNS,
        f"twin_{twin_id}:faq:{question.lower()}"
    ))
    assert id1 == expected


# ---------------------------------------------------------------------------
# VSTORE-04: Delete namespace
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_delete_namespace(mock_pgvector_pool):
    """delete_namespace must execute DELETE FROM chunks WHERE twin_id."""
    pool, conn = mock_pgvector_pool
    conn.execute = AsyncMock(return_value="DELETE 5")

    with patch("adk_core.services.vector_store.get_pgvector_pool", return_value=pool):
        await delete_namespace("twin-xyz")

    conn.execute.assert_called_once()
    sql = conn.execute.call_args[0][0]
    assert "DELETE FROM chunks" in sql
    assert "twin_id" in sql


# ---------------------------------------------------------------------------
# VSTORE-05: Namespace stats
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_namespace_stats(mock_pgvector_pool):
    """namespace_stats must return dict with vector_count key."""
    pool, conn = mock_pgvector_pool
    conn.fetchval = AsyncMock(return_value=42)

    with patch("adk_core.services.vector_store.get_pgvector_pool", return_value=pool):
        result = await namespace_stats("twin-xyz")

    assert "vector_count" in result
    assert result["vector_count"] == 42


# ---------------------------------------------------------------------------
# VSTORE-06: Validate index
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_validate_index(mock_pgvector_pool):
    """validate_index must return status=ok when pgvector extension and table exist."""
    pool, conn = mock_pgvector_pool
    # Mock: extension exists, table has embedding column
    conn.fetchval = AsyncMock(side_effect=[True, True])

    with patch("adk_core.services.vector_store.get_pgvector_pool", return_value=pool):
        result = await validate_index()

    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# VSTORE-07: Normalization function
# ---------------------------------------------------------------------------
def test_normalization():
    """_normalize must L2-normalize vectors. Zero vector returns zero vector."""
    # [3, 4, 0] -> norm=5 -> [0.6, 0.8, 0.0]
    result = _normalize([3.0, 4.0, 0.0])
    assert abs(result[0] - 0.6) < 1e-6
    assert abs(result[1] - 0.8) < 1e-6
    assert abs(result[2] - 0.0) < 1e-6

    # Zero vector stays zero
    zero_result = _normalize([0.0, 0.0, 0.0])
    assert zero_result == [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# VSTORE-08: Zero result warning
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_zero_result_warning(mock_pgvector_pool, caplog):
    """Search returning empty results must log a WARNING with 'zero results'."""
    pool, conn = mock_pgvector_pool
    conn.fetch = AsyncMock(return_value=[])

    import logging
    with caplog.at_level(logging.WARNING):
        with patch("adk_core.services.vector_store.get_pgvector_pool", return_value=pool):
            with patch("adk_core.services.vector_store.get_embedding", return_value=[0.1] * 768):
                results = await search("obscure query", "twin-empty", top_k=5)

    assert results == []
    assert any("zero results" in record.message.lower() for record in caplog.records), (
        "Expected WARNING log containing 'zero results'"
    )


# ---------------------------------------------------------------------------
# REGRESSION: search() must call the 5-arg search_chunks overload.
#
# Why this test exists:
#   Migration 20260421_search_chunks_tiers added a new 5-arg search_chunks
#   alongside the legacy 3-arg form. Production broke when a caller reverted
#   to 3 positional args because Postgres raised AmbiguousFunctionError.
#   A separate migration (20260422_drop_legacy_search_chunks_overloads) drops
#   the old overload, but this test guards the Python contract independently:
#   the SQL we send MUST be the 5-arg signature, and callers must be able to
#   pass allowed_tiers + min_similarity through to SQL.
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_search_sends_5_arg_sql_with_defaults(mock_pgvector_pool):
    """search() with default args must call the 5-arg search_chunks signature.

    Guards against regression to the 3-arg form that caused AmbiguousFunctionError
    in staging when both overloads coexisted.
    """
    pool, conn = mock_pgvector_pool
    conn.fetch = AsyncMock(return_value=[])

    with patch("adk_core.services.vector_store.get_pgvector_pool", return_value=pool):
        with patch("adk_core.services.vector_store.get_embedding", return_value=[0.1] * 768):
            await search("q", "twin-123", top_k=5)

    conn.fetch.assert_awaited_once()
    sql = conn.fetch.call_args[0][0]
    # 5 positional placeholders, including the explicit ::text[] cast on $5
    assert "search_chunks($1::vector, $2::uuid, $3, $4, $5::text[])" in sql, (
        "search() must call the 5-arg search_chunks signature with explicit text[] cast"
    )
    # Default min_similarity=0.0, allowed_tiers=None
    call_args = conn.fetch.call_args[0]
    assert call_args[4] == 0.0, "min_similarity default must be 0.0"
    assert call_args[5] is None, "allowed_tiers default must be None"


@pytest.mark.asyncio
async def test_search_forwards_tier_and_similarity_args(mock_pgvector_pool):
    """Callers passing allowed_tiers + min_similarity must have them reach SQL.

    Covers meeting_context_prep.py using allowed_tiers=['public','team'] to
    keep private chunks out of Gemini Live system instructions.
    """
    pool, conn = mock_pgvector_pool
    conn.fetch = AsyncMock(return_value=[])

    with patch("adk_core.services.vector_store.get_pgvector_pool", return_value=pool):
        with patch("adk_core.services.vector_store.get_embedding", return_value=[0.1] * 768):
            await search(
                "q",
                "twin-123",
                top_k=5,
                allowed_tiers=["public", "team"],
                min_similarity=0.5,
            )

    call_args = conn.fetch.call_args[0]
    assert call_args[4] == 0.5
    assert call_args[5] == ["public", "team"]


@pytest.mark.asyncio
async def test_search_global_sends_5_arg_sql(mock_pgvector_pool):
    """search_global() must call the 5-arg search_chunks_global signature.

    Same ambiguity risk as per-twin search: migration 20260422 drops the
    legacy 4-arg overload; this test guards the Python call-shape contract.
    """
    pool, conn = mock_pgvector_pool
    conn.fetch = AsyncMock(return_value=[])

    with patch("adk_core.services.vector_store.get_pgvector_pool", return_value=pool):
        with patch("adk_core.services.vector_store.get_embedding", return_value=[0.1] * 768):
            await search_global("q", [str(uuid.uuid4())])

    conn.fetch.assert_awaited_once()
    sql = conn.fetch.call_args[0][0]
    assert "search_chunks_global($1::vector, $2::uuid[], $3, $4, $5::text[])" in sql, (
        "search_global() must call the 5-arg search_chunks_global signature"
    )
    # Marketplace global search must default to public-only tiers
    call_args = conn.fetch.call_args[0]
    assert call_args[5] == ["public"], "search_global must default to public-only tiers"


# ---------------------------------------------------------------------------
# INFRA-06: Pool rejects port 6543
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pool_rejects_6543(monkeypatch):
    """get_pgvector_pool must raise ValueError when DSN uses port 6543."""
    monkeypatch.setenv("PGVECTOR_DATABASE_URL", "postgresql://x:x@host:6543/db")

    # Reset the singleton so it re-reads the env var
    import modules.clients as clients_mod
    monkeypatch.setattr(clients_mod, "_pgvector_pool", None)

    from modules.clients import get_pgvector_pool

    with pytest.raises(ValueError, match="6543"):
        await get_pgvector_pool()


# ---------------------------------------------------------------------------
# FAQ origin tag + count_faqs (interview stats, issue #331)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_upsert_faq_tags_origin_only_when_given(mock_pgvector_pool):
    pool, conn = mock_pgvector_pool
    conn.execute = AsyncMock(return_value="INSERT 0 1")

    with patch("adk_core.services.vector_store.get_pgvector_pool", return_value=pool):
        with patch("adk_core.services.vector_store.get_embedding", return_value=[0.1] * 768):
            await upsert_faq("Q1?", "A1", "twin-abc", origin="interview")
            await upsert_faq("Q2?", "A2", "twin-abc")

    tagged = json.loads(conn.execute.await_args_list[0].args[5])
    untagged = json.loads(conn.execute.await_args_list[1].args[5])
    assert tagged["origin"] == "interview"
    assert tagged["source"] == "faq"
    assert "origin" not in untagged


@pytest.mark.asyncio
async def test_count_faqs_filters_by_origin(mock_pgvector_pool):
    pool, conn = mock_pgvector_pool
    conn.fetchval = AsyncMock(return_value=7)

    with patch("adk_core.services.vector_store.get_pgvector_pool", return_value=pool):
        result = await count_faqs("twin-abc", origin="interview")

    assert result == 7
    sql, *params = conn.fetchval.await_args.args
    assert "metadata->>'origin' = $2" in sql
    assert params == ["twin-abc", "interview"]


@pytest.mark.asyncio
async def test_count_faqs_returns_zero_when_none(mock_pgvector_pool):
    pool, conn = mock_pgvector_pool
    conn.fetchval = AsyncMock(return_value=None)

    with patch("adk_core.services.vector_store.get_pgvector_pool", return_value=pool):
        assert await count_faqs("twin-abc") == 0
