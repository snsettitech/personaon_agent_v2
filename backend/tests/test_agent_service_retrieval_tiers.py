"""Tests for surface-scoped KB retrieval tiers (PON-11 / ADR-001)."""

from __future__ import annotations

import pytest

from adk_core.services import agent_service


@pytest.mark.parametrize(
    ("surface_class", "expected"),
    [
        ("owner", None),
        ("assistant", None),
        ("visitor", ["public"]),
        ("widget_lead", ["public"]),
        ("public_lead", ["public"]),
        ("interview", ["public"]),
    ],
)
def test_retrieval_tiers_for_surface(surface_class: str, expected: list[str] | None) -> None:
    assert agent_service._retrieval_tiers_for_surface(surface_class) == expected


@pytest.mark.asyncio
async def test_visitor_search_tool_passes_public_tiers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_search(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(agent_service, "vector_search", fake_search)

    tool = agent_service._make_search_tool("twin-1", surface_class="visitor")
    fn = getattr(tool, "func", None) or getattr(tool, "_func", None)
    assert fn is not None
    await fn("what is my salary", top_k=3)

    assert captured["twin_id"] == "twin-1"
    assert captured["allowed_tiers"] == ["public"]
    assert captured["top_k"] == 3


@pytest.mark.asyncio
async def test_owner_search_tool_passes_no_tier_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_search(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return [{"text": "secret", "privacy_level": "private", "score": 0.9}]

    monkeypatch.setattr(agent_service, "vector_search", fake_search)

    tool = agent_service._make_search_tool("twin-1", surface_class="owner")
    fn = getattr(tool, "func", None) or getattr(tool, "_func", None)
    assert fn is not None
    results = await fn("private note", top_k=5)

    assert captured["allowed_tiers"] is None
    assert len(results) == 1


@pytest.mark.asyncio
async def test_chat_stream_pre_retrieval_scopes_visitor(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_search(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(agent_service, "vector_search", fake_search)
    monkeypatch.setattr(
        "modules.twin_namespace.get_twin_owner_id",
        lambda _tid: None,
    )

    def boom(*_a, **_k):  # type: ignore[no-untyped-def]
        raise RuntimeError("stop-after-retrieval")

    monkeypatch.setattr(agent_service, "_build_runner", boom)
    monkeypatch.setattr(agent_service, "_build_request_runner", boom)

    gen = agent_service.chat_stream(
        twin_id="twin-1",
        profile_dict={"name": "Test"},
        user_id="user-1",
        session_id="sess-1",
        message="hello",
        surface="visitor",
    )
    with pytest.raises(RuntimeError, match="stop-after-retrieval"):
        async for _ in gen:
            pass

    assert captured.get("allowed_tiers") == ["public"]
