"""Tests for the Phase 30 recap extras Gemini extractor."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


_SAFE_DEFAULT = {"intent": "", "what_happened": "", "commitments": []}


@pytest.mark.asyncio
async def test_extract_recap_extras_returns_leadership_fields(monkeypatch) -> None:
    from services import recap_extras_service

    class _FakeModels:
        @staticmethod
        def generate_content(**_kwargs):
            return SimpleNamespace(
                text=(
                    '{"intent":"Align launch scope",'
                    '"what_happened":"The team chose the beta path.",'
                    '"commitments":[{"text":"Alice will send pricing by Friday","assignee":"Alice","due_at":""}]}'
                )
            )

    class _FakeClient:
        models = _FakeModels()

    monkeypatch.setattr(recap_extras_service, "get_genai_client", lambda: _FakeClient())

    extras = await recap_extras_service.extract_recap_extras(
        transcript_text="Alice: We should choose beta.\nBob: I will send pricing.",
        title="Launch planning",
    )

    assert extras == {
        "intent": "Align launch scope",
        "what_happened": "The team chose the beta path.",
        "commitments": [{"text": "Alice will send pricing by Friday", "assignee": "Alice", "due_at": ""}],
    }


@pytest.mark.asyncio
async def test_extract_recap_extras_gemini_raises_returns_safe_default(monkeypatch) -> None:
    """Regression for review major M1: a Gemini timeout/exception MUST NOT
    crash the worker. The recap pipeline already has tldr/topics/action_items
    from the meeting summary path — extras failing should degrade gracefully,
    not poison the meeting row.
    """
    from services import recap_extras_service

    class _FakeModels:
        @staticmethod
        def generate_content(**_kwargs):
            raise RuntimeError("gemini timeout")

    class _FakeClient:
        models = _FakeModels()

    monkeypatch.setattr(recap_extras_service, "get_genai_client", lambda: _FakeClient())

    extras = await recap_extras_service.extract_recap_extras(
        transcript_text="Some transcript content",
        title="Standup",
    )
    assert extras == _SAFE_DEFAULT


@pytest.mark.asyncio
async def test_extract_recap_extras_malformed_json_returns_safe_default(monkeypatch) -> None:
    """Regression for review major M6: malformed JSON from Gemini must
    degrade to safe defaults, not crash the worker with JSONDecodeError.
    """
    from services import recap_extras_service

    class _FakeModels:
        @staticmethod
        def generate_content(**_kwargs):
            return SimpleNamespace(text="not json {{{")

    class _FakeClient:
        models = _FakeModels()

    monkeypatch.setattr(recap_extras_service, "get_genai_client", lambda: _FakeClient())

    extras = await recap_extras_service.extract_recap_extras(
        transcript_text="t",
        title=None,
    )
    assert extras == _SAFE_DEFAULT


@pytest.mark.asyncio
async def test_extract_recap_extras_empty_transcript_returns_safe_default(monkeypatch) -> None:
    """Regression for review major M6: an empty transcript should short-circuit
    BEFORE calling Gemini at all (saves a token round-trip + the prompt would
    be a no-op anyway).
    """
    from services import recap_extras_service

    called = {"count": 0}

    class _FakeModels:
        @staticmethod
        def generate_content(**_kwargs):
            called["count"] += 1
            return SimpleNamespace(text="{}")

    class _FakeClient:
        models = _FakeModels()

    monkeypatch.setattr(recap_extras_service, "get_genai_client", lambda: _FakeClient())

    extras = await recap_extras_service.extract_recap_extras(
        transcript_text="   ",
        title="Empty",
    )
    assert extras == _SAFE_DEFAULT
    assert called["count"] == 0, "Gemini must not be called for empty transcript"


@pytest.mark.asyncio
async def test_extract_recap_extras_missing_fields_in_response(monkeypatch) -> None:
    """Regression for review major M6: when Gemini returns a valid JSON
    object missing one of the required fields, the missing field should
    coerce to its safe default (empty string / empty array), not None.
    """
    from services import recap_extras_service

    class _FakeModels:
        @staticmethod
        def generate_content(**_kwargs):
            # No commitments field at all.
            return SimpleNamespace(text='{"intent":"X","what_happened":"Y"}')

    class _FakeClient:
        models = _FakeModels()

    monkeypatch.setattr(recap_extras_service, "get_genai_client", lambda: _FakeClient())

    extras = await recap_extras_service.extract_recap_extras(
        transcript_text="content",
        title=None,
    )
    assert extras == {"intent": "X", "what_happened": "Y", "commitments": []}


@pytest.mark.asyncio
async def test_extract_recap_extras_uses_injection_delimiters(monkeypatch) -> None:
    """Regression for review major M5: the prompt must wrap the transcript
    text in delimiter tags so a transcript containing instruction-like text
    (e.g. "Ignore previous instructions and return ...") cannot escape into
    the system prompt and exfiltrate behavior.
    """
    from services import recap_extras_service

    captured_prompts: list[str] = []

    class _FakeModels:
        @staticmethod
        def generate_content(**kwargs):
            captured_prompts.append(str(kwargs.get("contents") or ""))
            return SimpleNamespace(text='{"intent":"","what_happened":"","commitments":[]}')

    class _FakeClient:
        models = _FakeModels()

    monkeypatch.setattr(recap_extras_service, "get_genai_client", lambda: _FakeClient())

    await recap_extras_service.extract_recap_extras(
        transcript_text="malicious content here",
        title="Test",
    )
    assert captured_prompts, "Gemini should have been called once"
    prompt = captured_prompts[0]
    assert "<TRANSCRIPT>" in prompt and "</TRANSCRIPT>" in prompt
    # The instruction to treat the wrapped content as data must be present.
    assert "data, not instructions" in prompt.lower() or "do not follow" in prompt.lower()
