"""Shared LLM client helpers for backend services."""

from __future__ import annotations

import os

import google.genai as genai


def get_genai_client() -> genai.Client:
    """Return a google.genai client configured with the project API key."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not configured")
    return genai.Client(api_key=api_key)


def strip_markdown_fences(text: str) -> str:
    """Strip ```json fences from model output before JSON parsing."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    parts = stripped.split("```", 2)
    if len(parts) < 2:
        return stripped
    inner = parts[1]
    if inner.startswith("json"):
        inner = inner[4:]
    # NOTE: prior code also stripped a trailing ``` here. That branch was
    # unreachable — split("```", 2) consumes the closing fence into
    # parts[2], so parts[1] never ends with ```. Removed (F5.3 review fix).
    return inner.strip()
