"""ADK FunctionTool factory for owner-driven persona profile edits (Home v1).

The chief-of-staff can edit the owner's PUBLIC persona page from chat. It writes
plain-text fields into settings.public_profile — the exact keys
normalize_public_profile() reads FIRST for /p/{handle} — so an edit renders
immediately. Everything structural (status, handle, theme, sections, lifecycle,
cited research) is OFF LIMITS and not writable here.

The write goes through the `update_persona_field` Postgres function (jsonb_set)
on the SERVICE-key client: it merges a single field atomically — no read-modify-
write race, no full-settings-blob round-trip, and it bypasses RLS so it succeeds
where the broken Publish-tab UI (#230) cannot. Owner-scoped: twin_id is closure-
bound and the assistant endpoint verifies ownership before the agent runs.
"""

import logging
import re

from google.adk.tools import FunctionTool

from modules.observability import get_supabase_client
from modules.runtime_kill_switches import agent_edits_enabled
from modules.text_quality import validate_headline_text, validate_meaningful_text

logger = logging.getLogger(__name__)

# field -> max length. ONLY these public-profile text fields are chat-editable.
_EDITABLE_FIELDS: dict[str, int] = {
    "headline": 240,
    "role": 160,
    "organization": 160,
    "occupation": 160,
    "bio": 2000,
    "short_description": 400,
}

_HTML_TAG_RE = re.compile(r"<[^>]*>")


def _editable_fields_label() -> str:
    return ", ".join(_EDITABLE_FIELDS.keys())


def _make_update_persona_tool(twin_id: str) -> FunctionTool:
    """Return a FunctionTool that edits one public-profile text field for twin_id."""

    async def update_persona(field: str, value: str) -> dict:
        """Edit ONE text field on the owner's public persona page.

        Call this ONLY after the owner has explicitly confirmed the exact new
        text — it updates their LIVE public page immediately. Editable fields:
        headline, role, organization, occupation, bio, short_description.

        Args:
            field: Which field to set (must be one of the editable fields).
            value: The new text for that field.
        """
        # Runtime kill-switch (execution-board 0.10 / PRD NFR-3): checked here,
        # INSIDE the tool call, not in _make_update_persona_tool — the factory
        # runs once per cached runner, so checking there would freeze the flag's
        # value for that runner's lifetime. Reading it per-call means flipping
        # AGENT_EDITS_ENABLED in Cloud Run takes effect on the very next turn,
        # no rebuild/redeploy of the image required — see
        # runtime_kill_switches.py for the Cloud Run traffic-pinning
        # precondition this depends on. The agent declines in-character rather
        # than the write silently failing or raising.
        if not agent_edits_enabled():
            logger.info("[TOOL] update_persona declined — AGENT_EDITS_ENABLED=false twin=%s", twin_id)
            return {
                "status": "rejected",
                "message": "Editing is temporarily paused right now — I can't update the page at the moment. Please try again later.",
            }

        key = (field or "").strip().lower()
        max_len = _EDITABLE_FIELDS.get(key)
        if max_len is None:
            return {
                "status": "rejected",
                "message": f"'{field}' isn't editable. You can edit: {_editable_fields_label()}.",
            }

        # Strip HTML tags (defense-in-depth against stored XSS on the public page),
        # then re-trim — this text is rendered to visitors.
        clean = _HTML_TAG_RE.sub("", (value or "").strip()).strip()
        if not clean:
            return {"status": "rejected", "message": f"The new {key} can't be empty."}
        if len(clean) > max_len:
            return {
                "status": "rejected",
                "message": f"That {key} is too long ({len(clean)}/{max_len} characters).",
            }

        # Same meaningfulness bar as the rest of the publish-gate write paths
        # (modules.text_quality — see its docstring) applies to bio/headline
        # here too, so a chat-driven edit can't quietly reintroduce the
        # "nill"-style thin content the gate exists to block on every other
        # write path.
        try:
            if key == "bio":
                clean = validate_meaningful_text(clean)
            elif key == "headline":
                clean = validate_headline_text(clean)
        except ValueError as exc:
            return {"status": "rejected", "message": str(exc)}

        sb = get_supabase_client()
        try:
            # Atomic single-field merge in Postgres (no read-modify-write race).
            sb.rpc(
                "update_persona_field",
                {"p_twin_id": twin_id, "p_field": key, "p_value": clean},
            ).execute()
        except Exception:
            logger.exception("[TOOL] update_persona write failed twin=%s field=%s", twin_id, key)
            return {"status": "error", "message": "Couldn't save the change — please try again."}

        logger.info("[TOOL] update_persona twin=%s field=%s len=%d", twin_id, key, len(clean))
        return {
            "status": "updated",
            "field": key,
            "message": f"Your {key} is updated and live on your page.",
        }

    return FunctionTool(func=update_persona)
