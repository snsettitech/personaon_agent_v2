"""Recap edit endpoints — Wave 7a.

PATCH /v2/meetings/{twin_id}/{meeting_id}/recap     → edit one field
POST  /v2/meetings/{twin_id}/{meeting_id}/recap/nl-edit  → Granola-style NL edit
                                                          (returns preview;
                                                           commits via PATCH)

Concurrency: PATCH honors `If-Match: <recap_version>` header — 409 on mismatch.
Every successful PATCH bumps recap_version + stamps recap_corrected_at and
writes one row to `meeting_recap_edits` (audit table).

`my_positions` edits are accepted here for the field validation, but the
persona-training write-back (graph_claims + Pinecone invalidation) is Wave 7b
and not implemented in this commit. Edits succeed without training.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import defaultdict, deque
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from adk_core.model_names import chat_model_name
from modules.observability import supabase
from routers.meetings import _get_current_user, _require_meeting_intelligence

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meetings-recap-edit"])

# Fields the user is allowed to edit (10 of 11 RecapContract fields;
# twin_id is identity and never edited).
EDITABLE_FIELDS = {
    "recap",
    "intent_vs_outcome",
    "action_items",
    "commitments",
    "decisions",
    "topics",
    "unanswered_questions",
    "people_observed",
    "my_positions",
    "style_sample",
}

# NL-edit rate limit: per-user simple sliding window.
# NOTE: In-memory only — NOT shared across Cloud Run instances. A determined
# user can bypass by hitting different instances. This is best-effort cost
# control for v1, not an abuse-prevention boundary. Replace with a shared
# store (Redis ZSET / Supabase rate-limit RPC) before relying on this limit
# for abuse prevention or billing protection.
_NL_EDIT_WINDOW_SEC = 60
_NL_EDIT_MAX_PER_WINDOW = 5
_nl_edit_calls: dict[str, deque[float]] = defaultdict(deque)


# ─────────────────────────────────────────────────────────────────────────────
# Request schemas
# ─────────────────────────────────────────────────────────────────────────────

EditReason = Literal["correction", "addition", "removal", "nl_prompt"]


class PatchRecapRequest(BaseModel):
    """Body for PATCH /recap. One field at a time — keeps the contract simple
    and means concurrent edits on different fields don't both have to win.
    """
    field: str = Field(..., description="One of EDITABLE_FIELDS")
    value: Any = Field(..., description="Typed payload for that field")
    edit_reason: EditReason | None = None
    nl_prompt: str | None = Field(default=None, max_length=500)


class NLEditRequest(BaseModel):
    """Body for POST /recap/nl-edit. Returns a preview — never commits."""
    field: str = Field(..., description="One of EDITABLE_FIELDS")
    prompt: str = Field(..., min_length=1, max_length=200)


# ─────────────────────────────────────────────────────────────────────────────
# Validation helpers
# ─────────────────────────────────────────────────────────────────────────────

def _validate_field_value(field: str, value: Any) -> Any:
    """Best-effort type validation per field. Returns the normalized value
    or raises HTTPException(422).
    """
    if field == "recap":
        if value is None:
            return None
        if not isinstance(value, str):
            raise HTTPException(422, "recap must be string or null")
        return value.strip()[:5000] or None

    if field == "style_sample":
        if value is None:
            return None
        if not isinstance(value, str):
            raise HTTPException(422, "style_sample must be string or null")
        return value.strip()[:2000] or None

    if field == "intent_vs_outcome":
        if value is None:
            return None
        if not isinstance(value, dict):
            raise HTTPException(422, "intent_vs_outcome must be object {intent, outcome}")
        intent = value.get("intent")
        outcome = value.get("outcome")
        return {
            "intent": (intent.strip()[:1000] if isinstance(intent, str) else None) or None,
            "outcome": (outcome.strip()[:1000] if isinstance(outcome, str) else None) or None,
        }

    if field in {"decisions", "topics", "unanswered_questions"}:
        if not isinstance(value, list):
            raise HTTPException(422, f"{field} must be a list of strings")
        cleaned: list[str] = []
        for item in value[:50]:  # hard cap
            if isinstance(item, str):
                s = item.strip()[:500]
                if s:
                    cleaned.append(s)
        return cleaned

    if field == "action_items":
        if not isinstance(value, list):
            raise HTTPException(422, "action_items must be a list")
        cleaned_ai: list[dict[str, Any]] = []
        for item in value[:50]:
            if not isinstance(item, dict):
                continue
            owner = (item.get("owner") or "").strip()[:120]
            description = (item.get("description") or "").strip()[:500]
            if not description:
                continue
            row = {"owner": owner or "unassigned", "description": description}
            due = item.get("due")
            if isinstance(due, str) and due.strip():
                row["due"] = due.strip()[:120]
            cleaned_ai.append(row)
        return cleaned_ai

    if field == "commitments":
        if not isinstance(value, list):
            raise HTTPException(422, "commitments must be a list")
        cleaned_c: list[dict[str, Any]] = []
        for item in value[:50]:
            if not isinstance(item, dict):
                continue
            by = (item.get("by") or "").strip()[:120]
            what = (item.get("what") or "").strip()[:500]
            if not by or not what:
                continue
            row = {"by": by, "what": what}
            to = item.get("to")
            if isinstance(to, str) and to.strip():
                row["to"] = to.strip()[:120]
            due = item.get("due")
            if isinstance(due, str) and due.strip():
                row["due"] = due.strip()[:120]
            cleaned_c.append(row)
        return cleaned_c

    if field == "people_observed":
        if not isinstance(value, list):
            raise HTTPException(422, "people_observed must be a list")
        cleaned_p: list[dict[str, Any]] = []
        for item in value[:50]:
            if not isinstance(item, dict):
                continue
            name = (item.get("name") or "").strip()[:200]
            if not name:
                continue
            row = {"name": name}
            role_hint = item.get("role_hint")
            if isinstance(role_hint, str) and role_hint.strip():
                row["role_hint"] = role_hint.strip()[:200]
            cleaned_p.append(row)
        return cleaned_p

    if field == "my_positions":
        if not isinstance(value, list):
            raise HTTPException(422, "my_positions must be a list")
        cleaned_pos: list[dict[str, Any]] = []
        for item in value[:50]:
            if not isinstance(item, dict):
                continue
            subject = (item.get("subject") or "").strip()[:500]
            stance = (item.get("stance") or "").strip()[:1500]
            if not subject or not stance:
                continue
            row = {"subject": subject, "stance": stance}
            sup = item.get("supersedes")
            if isinstance(sup, str) and sup.strip():
                row["supersedes"] = sup.strip()[:200]
            cleaned_pos.append(row)
        return cleaned_pos

    raise HTTPException(422, f"Unknown field: {field}")


def _check_nl_rate_limit(user_id: str) -> None:
    """5 NL edits per 60s per user."""
    now = time.monotonic()
    bucket = _nl_edit_calls[user_id]
    while bucket and bucket[0] < now - _NL_EDIT_WINDOW_SEC:
        bucket.popleft()
    if len(bucket) >= _NL_EDIT_MAX_PER_WINDOW:
        raise HTTPException(429, "Too many NL edits — try again in a minute.")
    bucket.append(now)


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /v2/meetings/{twin_id}/{meeting_id}/recap
# ─────────────────────────────────────────────────────────────────────────────

@router.patch(
    "/v2/meetings/{twin_id}/{meeting_id}/recap",
    dependencies=[Depends(_require_meeting_intelligence)],
)
async def patch_recap(
    twin_id: str,
    meeting_id: str,
    body: PatchRecapRequest,
    request: Request,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    """Edit a single recap field with optimistic concurrency."""
    user = _get_current_user(request)
    tenant_id = user.get("tenant_id") or user.get("id")
    user_id = user.get("user_id") or user.get("id")
    if not tenant_id:
        raise HTTPException(401, "Missing tenant context")

    if body.field not in EDITABLE_FIELDS:
        raise HTTPException(422, f"Field '{body.field}' is not editable")

    # Validate + normalize value per field schema
    new_value = _validate_field_value(body.field, body.value)

    # Fetch current row (tenant-scoped) — also captures old value for audit + version check
    existing = (
        supabase.table("meetings")
        .select(f"id, recap_version, {body.field}")
        .eq("id", meeting_id)
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(404, "Meeting not found")
    current_version = int(existing.data.get("recap_version") or 1)
    old_value = existing.data.get(body.field)

    # If-Match concurrency check
    if if_match is not None:
        try:
            client_version = int(if_match.strip())
        except (TypeError, ValueError):
            client_version = -1
        if client_version != current_version:
            return _conflict_response(current_version)

    # Apply update — bump version + stamp corrected_at
    from datetime import datetime, timezone
    now_iso = datetime.now(timezone.utc).isoformat()
    update_payload = {
        body.field: new_value,
        "recap_version": current_version + 1,
        "recap_corrected_at": now_iso,
    }
    upd = (
        supabase.table("meetings")
        .update(update_payload)
        .eq("id", meeting_id)
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .eq("recap_version", current_version)  # double-guard against races
        .execute()
    )
    if not upd.data:
        # Either tenant-scope failed (handled above) or version raced.
        re_check = (
            supabase.table("meetings")
            .select("recap_version")
            .eq("id", meeting_id)
            .eq("twin_id", twin_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )
        if re_check.data:
            return _conflict_response(int(re_check.data.get("recap_version") or 1))
        raise HTTPException(404, "Meeting not found")

    # Audit row — best-effort, never blocks the PATCH success.
    # NOTE: do NOT log `exc` directly here. Supabase exceptions stringify
    # the failed request payload, which includes old_value/new_value —
    # potentially several KB of recap text containing PII. Log only the
    # exception type so Cloud Logging stays PII-free.
    try:
        supabase.table("meeting_recap_edits").insert({
            "meeting_id": meeting_id,
            "tenant_id": tenant_id,
            "field": body.field,
            "old_value": old_value,
            "new_value": new_value,
            "edit_reason": body.edit_reason,
            "nl_prompt": body.nl_prompt,
            "edited_by": user_id,
        }).execute()
    except Exception as exc:
        logger.warning(
            "[RecapEdit] audit insert failed meeting=%s field=%s type=%s",
            meeting_id, body.field, type(exc).__name__,
        )

    # NOTE (W7b): when field == "my_positions", we will also enqueue
    # GraphOperationType.CREATE_CLAIMS + a future INVALIDATE_PERSONA_CACHE op.
    # That's gated behind Phase 4 — not in this commit.

    return {
        "status": "ok",
        "data": {
            "recap_version": current_version + 1,
            "recap_corrected_at": now_iso,
            "field": body.field,
            "value": new_value,
        },
    }


def _conflict_response(current_version: int) -> dict[str, Any]:
    raise HTTPException(
        status_code=409,
        detail={
            "code": "recap_version_mismatch",
            "current_version": current_version,
            "message": "The recap was updated in another tab. Reload and try again.",
        },
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /v2/meetings/{twin_id}/{meeting_id}/recap/nl-edit
# ─────────────────────────────────────────────────────────────────────────────

# Schema hints per editable field for the LLM. The structured fields are
# returned as JSON; string fields are returned as a single string. The
# client previews the diff and calls PATCH to commit.

_FIELD_SCHEMAS: dict[str, str] = {
    "recap": "string (1-3 sentences, max 500 chars)",
    "style_sample": "string (single representative quote, max 1000 chars)",
    "intent_vs_outcome": '{"intent": "string", "outcome": "string"}',
    "decisions": "list[string], max 10 items",
    "topics": "list[string], max 10 items",
    "unanswered_questions": "list[string], max 10 items",
    "action_items": '[{"owner": "string", "description": "string", "due": "optional string"}]',
    "commitments": '[{"by": "string", "what": "string", "to": "optional", "due": "optional"}]',
    "people_observed": '[{"name": "string", "role_hint": "optional string"}]',
    "my_positions": '[{"subject": "string", "stance": "string"}]',
}


@router.post(
    "/v2/meetings/{twin_id}/{meeting_id}/recap/nl-edit",
    dependencies=[Depends(_require_meeting_intelligence)],
)
async def nl_edit_recap(
    twin_id: str,
    meeting_id: str,
    body: NLEditRequest,
    request: Request,
) -> dict[str, Any]:
    """Granola-style: take a natural-language prompt + current field value,
    return a proposed new value. NEVER commits — client previews + commits
    via PATCH /recap.
    """
    user = _get_current_user(request)
    tenant_id = user.get("tenant_id") or user.get("id")
    user_id = str(user.get("user_id") or user.get("id") or "anon")
    if not tenant_id:
        raise HTTPException(401, "Missing tenant context")

    if body.field not in EDITABLE_FIELDS:
        raise HTTPException(422, f"Field '{body.field}' is not editable")

    _check_nl_rate_limit(user_id)

    # Fetch current value + meeting context for grounding
    existing = (
        supabase.table("meetings")
        .select(f"id, title, recap, {body.field}")
        .eq("id", meeting_id)
        .eq("twin_id", twin_id)
        .eq("tenant_id", tenant_id)
        .single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(404, "Meeting not found")

    current_value = existing.data.get(body.field)
    schema_hint = _FIELD_SCHEMAS.get(body.field, "any JSON")

    proposed = await _call_gemini_for_edit(
        meeting_title=existing.data.get("title") or "Untitled meeting",
        meeting_recap=existing.data.get("recap"),
        field=body.field,
        current_value=current_value,
        user_prompt=body.prompt,
        schema_hint=schema_hint,
    )

    # Validate proposed value through the same path PATCH would use.
    try:
        normalized = _validate_field_value(body.field, proposed)
    except HTTPException as ex:
        logger.warning(
            "[NLEdit] proposed value failed validation field=%s err=%s",
            body.field, ex.detail,
        )
        raise HTTPException(
            422,
            "The AI suggestion could not be validated. Try rephrasing your prompt.",
        )

    return {
        "status": "ok",
        "data": {
            "field": body.field,
            "prompt": body.prompt,
            "current_value": current_value,
            "proposed_value": normalized,
        },
    }


async def _call_gemini_for_edit(
    *,
    meeting_title: str,
    meeting_recap: str | None,
    field: str,
    current_value: Any,
    user_prompt: str,
    schema_hint: str,
) -> Any:
    """Call Gemini Flash to apply the user's natural-language edit.

    Returns the proposed new value (string for string fields, dict / list
    for structured fields). Raises HTTPException on LLM failure.
    """
    try:
        # Lazy import — heavy module, only loaded when NL-edit is invoked.
        from google import genai
    except Exception as exc:  # pragma: no cover
        logger.error("[NLEdit] google.genai import failed: %s", exc)
        raise HTTPException(503, "NL-edit is currently unavailable")

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
    if not api_key:
        raise HTTPException(503, "GEMINI_API_KEY not configured")

    # Tight system prompt — guards against prompt injection from `user_prompt`.
    system_prompt = f"""You are editing one field of a meeting recap. Apply the user's
edit instruction to the CURRENT value and return a NEW value in the
expected schema. Do not invent facts; reuse the existing content
where possible. Output JSON only with key "new_value" and nothing else.

FIELD: {field}
SCHEMA: {schema_hint}
"""

    current_json = json.dumps(current_value, ensure_ascii=False, default=str)
    contents = f"""MEETING TITLE: {meeting_title}
MEETING RECAP: {meeting_recap or "(no narrative yet)"}

CURRENT VALUE OF '{field}':
```json
{current_json}
```

USER EDIT INSTRUCTION:
{user_prompt}

Return ONLY a JSON object: {{"new_value": ...}}
"""

    try:
        client = genai.Client(api_key=api_key)
        resp = client.models.generate_content(
            model=chat_model_name(),
            contents=contents,
            config={
                "system_instruction": system_prompt,
                "response_mime_type": "application/json",
                "temperature": 0.2,  # tight; we don't want creativity
                "max_output_tokens": 2048,
            },
        )
        raw = resp.text or "{}"
    except Exception as exc:
        logger.exception("[NLEdit] gemini call failed field=%s: %s", field, exc)
        raise HTTPException(503, "NL edit failed — try again")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("[NLEdit] gemini returned non-JSON field=%s err=%s body=%r", field, exc, raw[:200])
        raise HTTPException(503, "AI suggestion was malformed; try again")

    if "new_value" not in parsed:
        logger.warning("[NLEdit] gemini response missing new_value field=%s body=%r", field, raw[:200])
        raise HTTPException(503, "AI suggestion missing expected field; try again")

    return parsed["new_value"]
