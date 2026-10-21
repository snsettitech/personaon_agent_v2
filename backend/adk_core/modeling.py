"""Model resolution helpers for the ADK runtime."""

from __future__ import annotations

import os
from typing import Any

from google.adk.models.lite_llm import LiteLlm

from adk_core.model_names import DEFAULT_GEMINI_MODEL

__all__ = ["DEFAULT_GEMINI_MODEL", "resolve_default_model", "resolve_model_for_env"]

DEFAULT_GEMINI_SYNTHESIS_MODEL = "gemini-3.5-flash"
DEFAULT_OPENAI_MODEL = "openai/gpt-4.1-mini"
DEFAULT_CEREBRAS_MODEL = "cerebras/qwen-3-235b-a22b-instruct-2507"
DEFAULT_CEREBRAS_RESEARCH_MODEL = "cerebras/llama3.1-8b"
DEFAULT_PROVIDER_PRIORITY = ("gemini", "cerebras", "openai")
LITELLM_PREFIXES = (
    "anthropic/",
    "azure/",
    "bedrock/",
    "cerebras/",
    "cohere/",
    "deepseek/",
    "fireworks_ai/",
    "groq/",
    "mistral/",
    "ollama/",
    "ollama_chat/",
    "openai/",
    "openrouter/",
    "vertex_ai/",
    "xai/",
)


def _normalize_priority(raw_priority: str) -> list[str]:
    items = [item.strip().lower() for item in raw_priority.split(",") if item.strip()]
    return items or list(DEFAULT_PROVIDER_PRIORITY)


def _provider_model(provider: str) -> str:
    if provider == "cerebras":
        model = os.getenv("CEREBRAS_MODEL", "").strip() or DEFAULT_CEREBRAS_MODEL
        return model if "/" in model else f"cerebras/{model}"
    if provider == "openai":
        model = os.getenv("OPENAI_MODEL", "").strip() or DEFAULT_OPENAI_MODEL
        return model if "/" in model else f"openai/{model}"
    return os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_GEMINI_MODEL


def _has_credentials(provider: str) -> bool:
    if provider == "cerebras":
        return bool(os.getenv("CEREBRAS_API_KEY"))
    if provider == "openai":
        return bool(os.getenv("OPENAI_API_KEY"))
    if provider == "gemini":
        return bool(os.getenv("GOOGLE_API_KEY"))
    return False


def _coerce_model(model_name: str, provider_hint: str | None = None) -> Any:
    normalized = model_name.strip()
    if not normalized:
        raise ValueError("ADK model name cannot be blank.")
    if provider_hint and "/" not in normalized and provider_hint in {"openai", "cerebras"}:
        normalized = f"{provider_hint}/{normalized}"
    if normalized.startswith(LITELLM_PREFIXES):
        return LiteLlm(model=normalized)
    return normalized


def resolve_default_model() -> Any:
    """
    Resolve the live ADK model configuration.

    Precedence:
    1. `ADK_DEFAULT_MODEL`
    2. First provider with credentials in `ADK_PROVIDER_PRIORITY`
    3. Gemini string fallback
    """
    explicit_model = os.getenv("ADK_DEFAULT_MODEL", "").strip()
    explicit_provider = os.getenv("ADK_DEFAULT_PROVIDER", "").strip().lower() or None
    if explicit_model:
        return _coerce_model(explicit_model, explicit_provider)

    priority = _normalize_priority(
        os.getenv("ADK_PROVIDER_PRIORITY", ",".join(DEFAULT_PROVIDER_PRIORITY))
    )
    for provider in priority:
        if _has_credentials(provider):
            return _coerce_model(_provider_model(provider), provider)
    return DEFAULT_GEMINI_MODEL


def resolve_model_for_env(
    env_key: str,
    *,
    fallback_model: str | None = None,
    fallback_provider: str | None = None,
) -> Any:
    explicit_model = os.getenv(env_key, "").strip()
    if explicit_model:
        return _coerce_model(explicit_model)
    if fallback_model:
        return _coerce_model(fallback_model, fallback_provider)
    return resolve_default_model()
