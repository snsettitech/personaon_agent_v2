"""Gemini model-name defaults shared by API, worker and services.

Deliberately free of ADK/LiteLLM imports so any module can use it cheaply.
Every runtime fallback for a Gemini model name should come from here, so a
retired model (e.g. ``gemini-2.5-flash``, 404 for new API keys since 2026-09)
can't linger as a hardcoded default in one corner of the codebase.
"""

from __future__ import annotations

import os

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash-lite"


def _env(key: str) -> str:
    return os.getenv(key, "").strip()


def chat_model_name() -> str:
    """``ADK_CHAT_MODEL``, else the project Gemini default."""
    return _env("ADK_CHAT_MODEL") or DEFAULT_GEMINI_MODEL


def research_model_name() -> str:
    """``ADK_RESEARCH_MODEL``, else the chat model."""
    return _env("ADK_RESEARCH_MODEL") or chat_model_name()


def default_model_name() -> str:
    """``ADK_DEFAULT_MODEL``, else the chat model."""
    return _env("ADK_DEFAULT_MODEL") or chat_model_name()
