import copy

import pytest
from google.adk.events import Event
from google.genai import types

from adk_core.services.session_store import (
    AdkDatabaseSessionService,
    _APP_MAX_SESSION_EVENTS,
    _DEFAULT_MAX_SESSION_EVENTS,
)


class _FakeSessionRepository:
    def __init__(self) -> None:
        self._sessions = {}

    def save(self, *, session, tenant_id=None, twin_id=None):
        self._sessions[(session.app_name, session.user_id, session.id)] = copy.deepcopy(session)
        return {}

    def get(self, *, app_name: str, user_id: str, session_id: str):
        session = self._sessions.get((app_name, user_id, session_id))
        return copy.deepcopy(session) if session is not None else None

    def list(self, *, app_name: str, user_id=None):
        sessions = []
        for (stored_app_name, stored_user_id, _), session in self._sessions.items():
            if stored_app_name != app_name:
                continue
            if user_id is not None and stored_user_id != user_id:
                continue
            sessions.append(copy.deepcopy(session))
        return sessions

    def delete(self, *, app_name: str, user_id: str, session_id: str) -> None:
        self._sessions.pop((app_name, user_id, session_id), None)


def _tool_call_event(index: int, *, turn_complete: bool | None = None) -> Event:
    return Event(
        author="research_searcher",
        turn_complete=turn_complete,
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name="web_search",
                        args={"query": f"query-{index}"},
                    )
                )
            ],
        ),
    )


def _tool_response_event(index: int, *, turn_complete: bool | None = None) -> Event:
    return Event(
        author="research_searcher",
        turn_complete=turn_complete,
        content=types.Content(
            role="user",
            parts=[
                types.Part(
                    function_response=types.FunctionResponse(
                        name="web_search",
                        response={"status": "success", "result_count": 1, "index": index},
                    )
                )
            ],
        ),
    )


def _text_event(index: int, *, turn_complete: bool) -> Event:
    return Event(
        author="assistant",
        turn_complete=turn_complete,
        content=types.Content(
            role="model",
            parts=[types.Part(text=f"message-{index}")],
        ),
    )


@pytest.mark.asyncio
async def test_research_sessions_do_not_trim_mid_tool_turn():
    repo = _FakeSessionRepository()
    service = AdkDatabaseSessionService(repository=repo)
    session = await service.create_session(
        app_name="adk_research",
        user_id="user-1",
        state={"session:tenant_id": "tenant-1"},
        session_id="session-1",
    )

    limit = _APP_MAX_SESSION_EVENTS["adk_research"]
    for index in range(limit + 1):
        event = _tool_call_event(index) if index % 2 == 0 else _tool_response_event(index)
        await service.append_event(session, event)

    saved = repo.get(app_name="adk_research", user_id="user-1", session_id="session-1")
    assert saved is not None
    assert len(saved.events) == limit + 1
    first_part = saved.events[0].content.parts[0]
    assert first_part.function_call.name == "web_search"


@pytest.mark.asyncio
async def test_single_long_research_turn_is_kept_even_when_it_completes():
    repo = _FakeSessionRepository()
    service = AdkDatabaseSessionService(repository=repo)
    session = await service.create_session(
        app_name="adk_research",
        user_id="user-2",
        state={"session:tenant_id": "tenant-2"},
        session_id="session-2",
    )

    limit = _APP_MAX_SESSION_EVENTS["adk_research"]
    for index in range(limit + 1):
        await service.append_event(session, _tool_call_event(index))

    await service.append_event(session, _tool_response_event(limit + 1, turn_complete=True))

    saved = repo.get(app_name="adk_research", user_id="user-2", session_id="session-2")
    assert saved is not None
    assert len(saved.events) == limit + 2
    assert saved.events[-1].turn_complete is True


@pytest.mark.asyncio
async def test_chat_sessions_trim_after_completed_turn_boundaries():
    repo = _FakeSessionRepository()
    service = AdkDatabaseSessionService(repository=repo)
    session = await service.create_session(
        app_name="adk_chat",
        user_id="user-3",
        state={"session:tenant_id": "tenant-3"},
        session_id="session-3",
    )

    for index in range(_DEFAULT_MAX_SESSION_EVENTS + 5):
        await service.append_event(session, _text_event(index, turn_complete=True))

    saved = repo.get(app_name="adk_chat", user_id="user-3", session_id="session-3")
    assert saved is not None
    assert len(saved.events) == _DEFAULT_MAX_SESSION_EVENTS
    assert saved.events[0].content.parts[0].text == "message-5"
