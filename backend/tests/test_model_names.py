"""Gemini model-name resolution: no retired model can come back as a default."""

from __future__ import annotations

import pytest

from adk_core.model_names import (
    DEFAULT_GEMINI_MODEL,
    chat_model_name,
    default_model_name,
    research_model_name,
)

_MODEL_ENV = ("ADK_CHAT_MODEL", "ADK_RESEARCH_MODEL", "ADK_DEFAULT_MODEL")


@pytest.fixture(autouse=True)
def _clear_model_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _MODEL_ENV:
        monkeypatch.delenv(key, raising=False)


def test_default_is_not_retired_model() -> None:
    assert DEFAULT_GEMINI_MODEL == "gemini-3.5-flash-lite"


def test_all_unset_falls_back_to_project_default() -> None:
    assert chat_model_name() == DEFAULT_GEMINI_MODEL
    assert research_model_name() == DEFAULT_GEMINI_MODEL
    assert default_model_name() == DEFAULT_GEMINI_MODEL


def test_research_unset_uses_chat_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADK_CHAT_MODEL", "gemini-chat-x")
    assert research_model_name() == "gemini-chat-x"
    assert default_model_name() == "gemini-chat-x"


def test_research_set_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADK_CHAT_MODEL", "gemini-chat-x")
    monkeypatch.setenv("ADK_RESEARCH_MODEL", "gemini-research-y")
    assert research_model_name() == "gemini-research-y"


def test_blank_values_are_treated_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADK_CHAT_MODEL", "  ")
    monkeypatch.setenv("ADK_RESEARCH_MODEL", "")
    assert research_model_name() == DEFAULT_GEMINI_MODEL


def test_passport_resume_import_uses_research_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resume → claims extraction calls Gemini with the resolved research model."""
    import modules.passport_resume_import as pri

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    monkeypatch.setenv("ADK_CHAT_MODEL", "gemini-chat-x")
    seen: dict[str, str] = {}

    class _Models:
        def generate_content(self, *, model: str, contents: str) -> object:
            seen["model"] = model
            return type("R", (), {"text": "{}"})()

    class _Client:
        def __init__(self, **_kwargs: object) -> None:
            self.models = _Models()

    monkeypatch.setattr("google.genai.Client", _Client)
    pri.extract_resume_fields_with_gemini("Ada Lovelace, programmer")
    assert seen["model"] == "gemini-chat-x"
