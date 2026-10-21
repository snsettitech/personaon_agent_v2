"""Regression coverage for the lead-capture tool-intact retry path.

Root cause this guards against: when the primary ADK pass for a widget_lead /
public_lead turn yields an empty final-text event (a known Gemini/ADK quirk on
tool-calling turns), chat_stream used to fall straight to _run_tool_free_retry
- a completely tools-stripped agent that fabricates a plausible "thanks for
your email" reply without capture_lead_contact ever running. Confirmed live on
staging: the visitor's email was never persisted to widget_leads despite the
assistant's acknowledgment.

The fix adds _run_lead_tool_retry: one more attempt with the capture tool
still attached, on a fresh session, before falling back to the no-tools path.
These tests verify (1) the tool-intact retry is tried first and its output is
used when it succeeds, and (2) when it also comes up empty, the tool-free
fallback instruction now explicitly forbids claiming any action was captured.
"""
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


def _event(text=None, function_call=None):
    return SimpleNamespace(
        content=SimpleNamespace(
            parts=[SimpleNamespace(text=text, function_call=function_call, function_response=None)]
        )
    )


def _patch_common(monkeypatch, agent_service, session_service, runner_cls):
    monkeypatch.setattr(agent_service, "_session_service", None)
    monkeypatch.setattr(agent_service, "_get_session_service", lambda: session_service)
    monkeypatch.setattr(agent_service, "Agent", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(agent_service, "Runner", runner_cls)
    monkeypatch.setattr(
        agent_service, "sanitize_for_llm", lambda text, strict_mode=False: SimpleNamespace(sanitized_text=text)
    )
    monkeypatch.setattr(
        agent_service,
        "generate_system_prompt",
        lambda profile_dict, actions=None, surface_class="visitor", lead_context=None: "BASE PROMPT",
    )

    async def fake_vector_search(*, query: str, twin_id: str, top_k: int):
        del query, twin_id, top_k
        return []

    monkeypatch.setattr(agent_service, "vector_search", fake_vector_search)


@pytest.mark.asyncio
async def test_lead_tool_retry_used_before_tool_free_fallback(monkeypatch):
    """Primary pass yields no text -> the tool-intact retry succeeds -> its
    chunks are used and the tools-stripped fallback must never run."""
    from adk_core.services import agent_service

    calls: list[str] = []

    class _FakeRunner:
        def __init__(self, *, agent, app_name, session_service):
            del app_name, session_service
            self.agent = agent

        async def run_async(self, *, user_id: str, session_id: str, new_message):
            del user_id, new_message
            calls.append(session_id)
            if session_id.endswith(":retry_tools"):
                yield _event(text="Got it, I've saved your email and will follow up.")
            elif session_id.endswith(":retry"):
                yield _event(text="TOOL-FREE FALLBACK SHOULD NOT BE REACHED")
            else:
                # Primary pass: empty-final-text quirk (function_call only, no text).
                yield _event(function_call=SimpleNamespace(name="capture_lead_contact"))

    session_service = _FakeSessionService()
    _patch_common(monkeypatch, agent_service, session_service, _FakeRunner)

    chunks = [
        chunk
        async for chunk in agent_service.chat_stream(
            twin_id="twin-1",
            profile_dict={"name": "Ada"},
            user_id="public:twin-1:tok",
            session_id="session-1",
            message="my email is visitor@example.com",
            surface="public_lead",
            lead_id="lead-1",
            lead_context={"lead_capture_enabled": True, "offer_state": "already_offered", "turn_count": 3},
        )
    ]

    assert chunks == ["Got it, I've saved your email and will follow up."]
    assert "session-1:retry_tools" in calls
    assert "session-1:retry" not in calls


@pytest.mark.asyncio
async def test_tool_free_fallback_cannot_claim_capture_when_lead_retry_also_empty(monkeypatch):
    """Both the primary pass AND the tool-intact retry yield no text -> falls
    through to the tools-stripped retry, whose instruction must now forbid
    claiming any save/capture happened."""
    from adk_core.services import agent_service

    captured_instructions: list[str] = []

    class _FakeRunner:
        def __init__(self, *, agent, app_name, session_service):
            del app_name, session_service
            self.agent = agent

        async def run_async(self, *, user_id: str, session_id: str, new_message):
            del user_id, new_message
            if session_id.endswith(":retry_tools"):
                yield _event(function_call=SimpleNamespace(name="capture_lead_contact"))
            elif session_id.endswith(":retry"):
                captured_instructions.append(self.agent.instruction)
                yield _event(text="Thanks for your interest!")
            else:
                yield _event(function_call=SimpleNamespace(name="capture_lead_contact"))

    session_service = _FakeSessionService()
    _patch_common(monkeypatch, agent_service, session_service, _FakeRunner)

    chunks = [
        chunk
        async for chunk in agent_service.chat_stream(
            twin_id="twin-1",
            profile_dict={"name": "Ada"},
            user_id="public:twin-1:tok",
            session_id="session-2",
            message="my email is visitor@example.com",
            surface="public_lead",
            lead_id="lead-1",
            lead_context={"lead_capture_enabled": True, "offer_state": "already_offered", "turn_count": 3},
        )
    ]

    assert chunks == ["Thanks for your interest!"]
    assert len(captured_instructions) == 1
    assert "have NOT saved, recorded, or captured" in captured_instructions[0]


@pytest.mark.asyncio
async def test_lead_tool_retry_used_when_primary_run_raises_mid_stream(monkeypatch):
    """Primary pass raises mid-stream (a genuine runner error, not just the
    empty-final-text quirk the other two tests cover) -> the except Exception
    handler's lead-tool-retry branch is exercised -> its chunks are used and
    the tools-stripped fallback must never run."""
    from adk_core.services import agent_service

    calls: list[str] = []

    class _FakeRunner:
        def __init__(self, *, agent, app_name, session_service):
            del app_name, session_service
            self.agent = agent

        async def run_async(self, *, user_id: str, session_id: str, new_message):
            del user_id, new_message
            calls.append(session_id)
            if session_id.endswith(":retry_tools"):
                yield _event(text="Got it, I've saved your email and will follow up.")
            elif session_id.endswith(":retry"):
                yield _event(text="TOOL-FREE FALLBACK SHOULD NOT BE REACHED")
            else:
                # Primary pass: raises mid-stream, distinct from the
                # empty-final-text quirk covered by the other two tests.
                yield _event(function_call=SimpleNamespace(name="capture_lead_contact"))
                raise RuntimeError("simulated primary runner failure")

    session_service = _FakeSessionService()
    _patch_common(monkeypatch, agent_service, session_service, _FakeRunner)

    chunks = [
        chunk
        async for chunk in agent_service.chat_stream(
            twin_id="twin-1",
            profile_dict={"name": "Ada"},
            user_id="public:twin-1:tok",
            session_id="session-3",
            message="my email is visitor@example.com",
            surface="public_lead",
            lead_id="lead-1",
            lead_context={"lead_capture_enabled": True, "offer_state": "already_offered", "turn_count": 3},
        )
    ]

    assert chunks == ["Got it, I've saved your email and will follow up."]
    assert "session-3:retry_tools" in calls
    assert "session-3:retry" not in calls


@pytest.mark.asyncio
async def test_lead_tool_retry_raises_falls_through_to_tool_free_retry(monkeypatch):
    """Primary run raises AND the lead-tool-intact retry's own runner also
    raises -> the except Exception as lead_retry_exc wrapper around the
    _run_lead_tool_retry call must swallow that second failure and fall
    through unconditionally to the tools-stripped retry, whose output is what
    is ultimately yielded."""
    from adk_core.services import agent_service

    calls: list[str] = []

    class _FakeRunner:
        def __init__(self, *, agent, app_name, session_service):
            del app_name, session_service
            self.agent = agent

        async def run_async(self, *, user_id: str, session_id: str, new_message):
            del user_id, new_message
            calls.append(session_id)
            if session_id.endswith(":retry_tools"):
                # The tool-intact retry's own runner also fails.
                raise RuntimeError("simulated lead tool retry failure")
            elif session_id.endswith(":retry"):
                yield _event(text="Thanks for your interest - tool-free fallback succeeded.")
            else:
                # Primary pass raises mid-stream.
                yield _event(function_call=SimpleNamespace(name="capture_lead_contact"))
                raise RuntimeError("simulated primary runner failure")

    session_service = _FakeSessionService()
    _patch_common(monkeypatch, agent_service, session_service, _FakeRunner)

    chunks = [
        chunk
        async for chunk in agent_service.chat_stream(
            twin_id="twin-1",
            profile_dict={"name": "Ada"},
            user_id="public:twin-1:tok",
            session_id="session-4",
            message="my email is visitor@example.com",
            surface="public_lead",
            lead_id="lead-1",
            lead_context={"lead_capture_enabled": True, "offer_state": "already_offered", "turn_count": 3},
        )
    ]

    assert chunks == ["Thanks for your interest - tool-free fallback succeeded."]
    assert "session-4:retry_tools" in calls
    assert "session-4:retry" in calls
