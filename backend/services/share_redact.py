"""Public share-recap redaction.

Strips sensitive fields from a meeting row before returning to the anonymous
public share route GET /m/{share_token}.

Privacy rules (per W5 plan):
- my_positions, style_sample, twin_responses, analytics, recall_bot_id,
  meet_link, recall_billable_seconds, model_*_tokens, estimated_cost_cents,
  brief_json — always hidden.
- attendees_json — emails collapsed to display names only.
- attendees_json organizer email — hidden.
"""

from __future__ import annotations

from typing import Any

# Belt-and-braces denylist: even though the backend GET /m/{token} now uses
# an explicit column allowlist, we still strip any of these if they somehow
# arrive in the row (e.g., from a future refactor that drops back to
# `select("*")`). Treat this as defense-in-depth, not the primary control.
_ALWAYS_HIDE = {
    "my_positions",
    "style_sample",
    "twin_responses",
    "analytics",
    "recall_bot_id",
    "recall_billable_seconds",
    "recall_recording_id",
    "meet_link",
    "estimated_cost_cents",
    "brief_json",
    "credentials_encrypted",
    # Share-state internals — public reader should never see these.
    "share_token",
    "share_view_count",
    "share_last_viewed_at",
    "share_created_at",
    "share_expires_at",
    "share_revoked_at",
    "share_enabled",
    # Tenant + provider tagging
    "tenant_id",
    "twin_id",
    "organizer_email",
    "calendar_connector_id",
    "provider_event_id",
    "provider_calendar_id",
    "provider_event_instance_id",
    # Live recording state
    "live_transcript",
    "transcript_text",
    "transcript_raw",
    "raw_recall_payload",
    # User-private prep
    "user_goal",
    "user_context",
    "context_prep",
    "internal_notes",
}


def _redact_attendees(attendees: list[Any] | None) -> list[dict[str, str]]:
    """Collapse attendee list to display names only.

    Privacy choice: if an attendee has only an email (no displayName) we
    surface a positional placeholder ("Attendee 2") instead of leaking the
    email-localpart, which can still identify an internal team member by
    handle (e.g., 'sai' → Sai Setti at PersonaOn).
    """
    if not attendees or not isinstance(attendees, list):
        return []
    out: list[dict[str, str]] = []
    next_anon_idx = 1
    for a in attendees:
        name: str = ""
        if isinstance(a, dict):
            name = (a.get("displayName") or a.get("name") or "").strip()
        elif isinstance(a, str):
            name = a.strip()
        if not name:
            name = f"Attendee {next_anon_idx}"
            next_anon_idx += 1
        out.append({"name": name})
    return out


def redact_for_public_share(meeting_row: dict[str, Any]) -> dict[str, Any]:
    """Project a meetings row into the public-readable shape.

    Drops sensitive columns, collapses attendees, hides any column whose
    name matches model_*_tokens prefix.
    """
    result: dict[str, Any] = {}
    for key, value in meeting_row.items():
        if key in _ALWAYS_HIDE:
            continue
        if key.startswith("model_") and key.endswith("_tokens"):
            continue
        if key == "attendees_json":
            result["attendees"] = _redact_attendees(value)
            continue
        result[key] = value
    return result


def public_owner_display(owner_row: dict[str, Any] | None) -> dict[str, str]:
    """Project a twin owner row to safe public fields (name only)."""
    if not owner_row:
        return {"name": "PersonaOn user"}
    name = (owner_row.get("name") or "PersonaOn user").strip()
    return {"name": name}
