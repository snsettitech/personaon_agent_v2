"""Tests for persona score helpers."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_score_knowledge_is_async():
    """_score_knowledge must be async def — asyncio.run() in FastAPI raises RuntimeError."""
    import asyncio
    from routers.persona_score import _score_knowledge

    assert asyncio.iscoroutinefunction(_score_knowledge), (
        "_score_knowledge must be 'async def'"
    )


@pytest.mark.asyncio
async def test_score_knowledge_returns_nonzero_when_vectors_exist():
    """Should score > 0 when vector_count > 0."""
    with patch("adk_core.services.vector_store.namespace_stats", new_callable=AsyncMock) as mock_stats:
        mock_stats.return_value = {"vector_count": 30}
        from routers.persona_score import _score_knowledge
        result = await _score_knowledge("twin-abc")

    assert result["score"] > 0
    assert result["max"] == 35
