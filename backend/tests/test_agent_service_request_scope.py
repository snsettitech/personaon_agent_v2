from __future__ import annotations

from types import SimpleNamespace

import pytest


class _FakeSessionService:
    def __init__(self):
        self._sessions: set[tuple[str, str, str]] = set()

    async def get_session(self, *, app_name: str, user_id: str, session_id: str):
        key = (app_name, user_id, session_id)
        if key in self._sessions:
            return {"id": session_id}
        return None

    async def create_session(self, *, app_name: str, user_id: str, session_id: str):
        self._sessions.add((app_name, user_id, session_id))
        return {"id": session_id}


class _FakeRunner:
    instructions: list[str] = []

    def __init__(self, *, agent, app_name, session_service):
        del app_name, session_service
        self.agent = agent

    async def run_async(self, *, user_id: str, session_id: str, new_message):
        del user_id, session_id, new_message
        self.instructions.append(self.agent.instruction)
        yield SimpleNamespace(
            content=SimpleNamespace(
                parts=[SimpleNamespace(text="ok", function_call=None, function_response=None)]
            )
        )


@pytest.mark.asyncio
async def test_chat_stream_does_not_leak_instruction_state(monkeypatch):
    from adk_core.services import agent_service

    session_service = _FakeSessionService()
    _FakeRunner.instructions = []

    monkeypatch.setattr(agent_service, "_session_service", None)
    monkeypatch.setattr(agent_service, "_get_session_service", lambda: session_service)
    monkeypatch.setattr(
        agent_service,
        "Agent",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    monkeypatch.setattr(agent_service, "Runner", _FakeRunner)
    monkeypatch.setattr(agent_service, "sanitize_for_llm", lambda text, strict_mode=False: SimpleNamespace(sanitized_text=text))
    monkeypatch.setattr(agent_service, "generate_system_prompt", lambda profile_dict, actions=None, surface_class="visitor", lead_context=None: "BASE PROMPT")

    async def fake_vector_search(*, query: str, twin_id: str, top_k: int, allowed_tiers=None):
        del twin_id, top_k, allowed_tiers
        if query == "first question":
            return [{"text": "retrieved memory"}]
        return []

    monkeypatch.setattr(agent_service, "vector_search", fake_vector_search)

    first_chunks = [
        chunk
        async for chunk in agent_service.chat_stream(
            twin_id="twin-1",
            profile_dict={"name": "Ada"},
            user_id="user-1",
            session_id="session-1",
            message="first question",
            mode_override="be concise",
            actions=[],
        )
    ]
    second_chunks = [
        chunk
        async for chunk in agent_service.chat_stream(
            twin_id="twin-1",
            profile_dict={"name": "Ada"},
            user_id="user-1",
            session_id="session-2",
            message="second question",
            actions=[],
        )
    ]

    assert first_chunks == ["ok"]
    assert second_chunks == ["ok"]
    assert len(_FakeRunner.instructions) == 2

    first_instruction, second_instruction = _FakeRunner.instructions
    assert "RETRIEVED CONTEXT" in first_instruction
    assert "ACTIVE MODE OVERRIDE" in first_instruction
    assert "retrieved memory" in first_instruction

    assert second_instruction == "BASE PROMPT"
    assert "RETRIEVED CONTEXT" not in second_instruction
    assert "ACTIVE MODE OVERRIDE" not in second_instruction
