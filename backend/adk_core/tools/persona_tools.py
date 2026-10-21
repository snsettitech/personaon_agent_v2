"""Persona-loading tools for ADK chat and compile flows."""

from __future__ import annotations

import json

from google.adk.tools import ToolContext

from adk_core.repositories.persona_repository import PersonaRepository
from adk_core.state_keys import AppKey, SessionKey
from adk_core.tools._common import error_result, require_twin_id


_persona_repository = PersonaRepository()


def load_persona_runtime(tool_context: ToolContext) -> dict[str, object]:
    """
    Load the active persona artifact and its quote pack into session state.
    """
    try:
        twin_id = require_twin_id(tool_context)
    except ValueError as e:
        return error_result(str(e))

    tenant_id = tool_context.state.get(SessionKey.TENANT_ID)

    artifact_row = _persona_repository.get_active_artifact(twin_id=twin_id, tenant_id=tenant_id)
    if not artifact_row:
        return error_result("No active persona artifact available.")

    artifact = artifact_row.get("artifact_json") or {}
    tool_context.state[AppKey.PERSONA_ARTIFACT_JSON] = json.dumps(artifact)
    tool_context.state[AppKey.PERSONA_VERSION] = artifact.get("version", "")
    tool_context.state[AppKey.QUOTE_PACK_JSON] = json.dumps(artifact.get("quote_pack") or [])
    tool_context.state[AppKey.PERSONA_PROMPT_BLOCK] = json.dumps(
        {
            "identity_frame": artifact.get("identity_frame") or {},
            "thinking_style": artifact.get("thinking_style") or {},
            "values_and_decision_heuristics": artifact.get("values_and_decision_heuristics") or [],
            "communication_rules": artifact.get("communication_rules") or [],
            "voice_dna": artifact.get("voice_dna") or {},
        }
    )
    return {
        "status": "success",
        "version": artifact.get("version"),
        "subject_name": artifact.get("subject_name"),
        "quote_count": len(artifact.get("quote_pack") or []),
    }
