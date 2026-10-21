"""ADK notification agent factory for event-driven notification generation."""

from __future__ import annotations

import logging
from typing import Any

from google.adk.agents import LlmAgent

logger = logging.getLogger(__name__)


def build_notification_agent(*, model: Any) -> LlmAgent:
    """Build the Phase I notification generation agent.

    The worker uses a deterministic fallback when model execution is disabled;
    this factory documents the ADK agent contract for the generated-copy path.
    """
    return LlmAgent(
        name="notification_agent",
        model=model,
        instruction=(
            "You generate concise PersonaOn notification emails from structured events. "
            "Use only the provided event context, recipient context, and memory context. "
            "Return JSON with subject, body, cta_label, and cta_path. Do not invent facts."
        ),
    )
