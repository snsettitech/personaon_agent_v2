"""Twin lifecycle state machine.

States:
  created           -> Initial state after twin creation
  researching       -> Research pipeline is running
  research_complete -> Research finished, ready for compile
  compiling         -> Compiler pipeline is running
  ready             -> Persona compiled, ready for chat
  active            -> Published and publicly accessible

Transitions:
  created           -> researching       (start research)
  researching       -> research_complete (research finishes)
  researching       -> created           (research fails, can retry)
  research_complete -> compiling         (start compile)
  research_complete -> researching       (re-research with different identity)
  compiling         -> ready             (compile finishes)
  compiling         -> research_complete (compile fails, can retry)
  ready             -> active            (publish)
  ready             -> researching       (re-research)
  active            -> researching       (re-research)
"""

from __future__ import annotations

import logging
from typing import Any

from adk_core.errors import invalid_twin_state

logger = logging.getLogger(__name__)

VALID_STATES = frozenset({
    "created",
    "researching",
    "research_complete",
    "compiling",
    "ready",
    "active",
})

# States from which chat is allowed
CHAT_ALLOWED_STATES = frozenset({"ready", "active"})

# States from which research can be (re)started
RESEARCH_ALLOWED_STATES = frozenset({"created", "ready", "active", "research_complete"})

# States from which compile can be started
COMPILE_ALLOWED_STATES = frozenset({"research_complete"})


def get_twin_state(twin: dict[str, Any]) -> str:
    """Extract lifecycle state from twin row, defaulting to 'created'."""
    settings = twin.get("settings") or {}
    return str(settings.get("lifecycle_state") or twin.get("lifecycle_state") or "created").strip()


def require_twin_state(twin: dict[str, Any], allowed: frozenset[str]) -> None:
    """Raise 409 if twin is not in one of the allowed states."""
    current = get_twin_state(twin)
    if current not in allowed:
        raise invalid_twin_state(current, sorted(allowed))


def update_twin_state(twin_id: str, new_state: str) -> None:
    """Update the twin's lifecycle state in the database."""
    if new_state not in VALID_STATES:
        raise ValueError(f"Invalid lifecycle state: {new_state}")

    from modules.observability import supabase

    # Update lifecycle_state in the settings JSONB column
    try:
        twin_result = supabase.table("twins").select("settings").eq("id", twin_id).maybe_single().execute()
        current_settings = dict((twin_result.data or {}).get("settings") or {}) if twin_result and twin_result.data else {}
    except Exception:
        current_settings = {}

    current_settings["lifecycle_state"] = new_state
    supabase.table("twins").update({"settings": current_settings}).eq("id", twin_id).execute()
    logger.info("Twin %s lifecycle state -> %s", twin_id, new_state)
