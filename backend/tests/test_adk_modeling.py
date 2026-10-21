from google.adk.models.lite_llm import LiteLlm

from adk_core.modeling import (
    DEFAULT_CEREBRAS_MODEL,
    DEFAULT_CEREBRAS_RESEARCH_MODEL,
    DEFAULT_GEMINI_MODEL,
    resolve_default_model,
    resolve_model_for_env,
)


def test_resolve_default_model_prefers_cerebras_when_available(monkeypatch):
    monkeypatch.delenv("ADK_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("ADK_DEFAULT_PROVIDER", raising=False)
    monkeypatch.setenv("ADK_PROVIDER_PRIORITY", "cerebras,gemini,openai")
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-cerebras-key")
    monkeypatch.delenv("CEREBRAS_MODEL", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "invalid-but-present")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")

    model = resolve_default_model()

    assert isinstance(model, LiteLlm)
    assert model.model == DEFAULT_CEREBRAS_MODEL


def test_resolve_default_model_keeps_gemini_strings(monkeypatch):
    monkeypatch.setenv("ADK_DEFAULT_MODEL", DEFAULT_GEMINI_MODEL)
    monkeypatch.delenv("ADK_DEFAULT_PROVIDER", raising=False)

    model = resolve_default_model()

    assert model == DEFAULT_GEMINI_MODEL


def test_resolve_model_for_env_uses_runner_override(monkeypatch):
    monkeypatch.setenv("ADK_RESEARCH_MODEL", DEFAULT_CEREBRAS_RESEARCH_MODEL)

    model = resolve_model_for_env("ADK_RESEARCH_MODEL")

    assert isinstance(model, LiteLlm)
    assert model.model == DEFAULT_CEREBRAS_RESEARCH_MODEL
