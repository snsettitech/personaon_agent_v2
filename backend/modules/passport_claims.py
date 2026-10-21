"""Passport claims repository — ensure profile + insert proposed claim (PON-7).

Provides repository functions used by the passport extraction pipeline:
- ensure_professional_profile: idempotent upsert of the profile row
- insert_proposed_claim:        validated insert of a single proposed claim
- transition_claim_state:       approve or reject a proposed claim
- correct_claim:                supersede an existing claim with a corrected one
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from modules.passport_claim_types import is_allowed_claim_type

logger = logging.getLogger(__name__)

_ALLOWED_CREATED_BY: frozenset[str] = frozenset({"import", "owner", "agent", "system"})


def ensure_professional_profile(
    *,
    tenant_id: str,
    twin_id: str,
    owner_user_id: str,
    client: Any,
) -> str:
    """Idempotent ensure: return existing profile id or insert draft and return it.

    Guards against supabase-py returning ``None`` from ``maybe_single().execute()``
    when zero rows match (first-run path). Concurrent callers use
    ``upsert(..., on_conflict='twin_id', ignore_duplicates=True)`` then select
    the winning row so UNIQUE(twin_id) races do not raise.
    """
    logger.info(
        "[passport_claims] ensure_professional_profile twin_id=%s", twin_id
    )
    resp = (
        client.table("professional_profiles")
        .select("id")
        .eq("twin_id", twin_id)
        .maybe_single()
        .execute()
    )

    # maybe_single can return None (no APIResponse) or APIResponse with data=None
    if resp is not None and getattr(resp, "data", None):
        profile_id: str = resp.data["id"]
        logger.info(
            "[passport_claims] found existing profile profile_id=%s twin_id=%s",
            profile_id,
            twin_id,
        )
        return profile_id

    new_id = str(uuid.uuid4())
    row: dict[str, Any] = {
        "id": new_id,
        "tenant_id": tenant_id,
        "twin_id": twin_id,
        "owner_user_id": owner_user_id,
        "status": "draft",
    }
    (
        client.table("professional_profiles")
        .upsert(row, on_conflict="twin_id", ignore_duplicates=True)
        .execute()
    )

    # Re-select so a concurrent winner's id is returned (not our discarded UUID)
    win = (
        client.table("professional_profiles")
        .select("id")
        .eq("twin_id", twin_id)
        .single()
        .execute()
    )
    if win is None or not getattr(win, "data", None):
        raise RuntimeError(
            f"[passport_claims] profile upsert race unresolved twin_id={twin_id}"
        )
    created_id: str = win.data["id"]
    logger.info(
        "[passport_claims] ensured draft profile profile_id=%s twin_id=%s",
        created_id,
        twin_id,
    )
    return created_id


def insert_proposed_claim(
    *,
    tenant_id: str,
    profile_id: str,
    claim_type: str,
    value_json: dict[str, Any],
    value_text: str,
    client: Any,
    confidence: float | None = None,
    extraction_version: str | None = None,
    fingerprint: str | None = None,
    created_by: str = "system",
) -> str:
    """Validate claim_type via is_allowed_claim_type; insert state=proposed; return claim id.

    Raises:
        ValueError: if claim_type is not in the Sprint-1 allowlist, or if
                    created_by is not one of {"import", "owner", "agent", "system"}.
    """
    if not is_allowed_claim_type(claim_type):
        raise ValueError(
            f"[passport_claims] disallowed claim_type={claim_type!r}; "
            "must be one of the Sprint-1 Passport claim types"
        )
    if created_by not in _ALLOWED_CREATED_BY:
        raise ValueError(
            f"[passport_claims] created_by={created_by!r} not allowed; "
            f"must be one of {sorted(_ALLOWED_CREATED_BY)}"
        )

    row: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "tenant_id": tenant_id,
        "profile_id": profile_id,
        "claim_type": claim_type,
        "value_json": value_json,
        "value_text": value_text,
        "state": "proposed",
        "created_by": created_by,
    }
    if confidence is not None:
        row["confidence"] = confidence
    if extraction_version is not None:
        row["extraction_version"] = extraction_version
    if fingerprint is not None:
        row["fingerprint"] = fingerprint

    logger.info(
        "[passport_claims] inserting proposed claim claim_type=%s profile_id=%s",
        claim_type,
        profile_id,
    )
    resp = client.table("profile_claims").insert(row).execute()
    claim_id: str = resp.data[0]["id"]
    logger.info(
        "[passport_claims] inserted proposed claim claim_id=%s claim_type=%s",
        claim_id,
        claim_type,
    )
    return claim_id


_ALLOWED_NEW_STATES: frozenset[str] = frozenset({"approved", "rejected"})


def transition_claim_state(
    *,
    claim_id: str,
    new_state: str,
    reviewed_by: str,
    client: Any,
) -> None:
    """Transition a claim from proposed → approved | rejected.

    Update is conditional on ``state = 'proposed'`` so concurrent reviewers
    cannot overwrite an already finalized claim. Verifies exactly one row
    changed.

    Args:
        reviewed_by: UUID string of the reviewer — must match a Supabase auth uid.

    Raises:
        ValueError: if new_state is not "approved" or "rejected".
        ValueError: if the claim is missing or not currently proposed.
    """
    if new_state not in _ALLOWED_NEW_STATES:
        raise ValueError(
            f"[passport_claims] new_state={new_state!r} not allowed; "
            "must be 'approved' or 'rejected'"
        )

    now = datetime.now(timezone.utc).isoformat()
    update_resp = (
        client.table("profile_claims")
        .update(
            {
                "state": new_state,
                "reviewed_by": reviewed_by,
                "reviewed_at": now,
                "updated_at": now,
            }
        )
        .eq("id", claim_id)
        .eq("state", "proposed")
        .execute()
    )

    rows = getattr(update_resp, "data", None) if update_resp is not None else None
    if not rows:
        raise ValueError(
            f"[passport_claims] cannot transition claim_id={claim_id}; "
            "missing or not in state 'proposed'"
        )

    logger.info(
        "[passport_claims] transitioned claim claim_id=%s proposed->%s reviewed_by=%s",
        claim_id,
        new_state,
        reviewed_by,
    )


def correct_claim(
    *,
    claim_id: str,
    tenant_id: str,
    profile_id: str,
    claim_type: str,
    value_json: dict[str, Any],
    value_text: str,
    reviewed_by: str,
    client: Any,
    confidence: float | None = None,
    fingerprint: str | None = None,
) -> str:
    """Supersede an existing claim with a corrected proposed claim atomically.

    Calls ``correct_profile_claim`` RPC so supersede + insert share one
    database transaction — a failed insert cannot leave the old claim
    superseded with no replacement.

    Args:
        reviewed_by: UUID string of the reviewer — must match a Supabase auth uid.

    Raises:
        ValueError: if claim_type is not in the Sprint-1 Passport allowlist.
        ValueError: if the RPC reports the claim cannot be corrected.
    """
    if not is_allowed_claim_type(claim_type):
        raise ValueError(
            f"[passport_claims] disallowed claim_type={claim_type!r} in correct_claim; "
            "must be one of the Sprint-1 Passport claim types"
        )

    logger.info(
        "[passport_claims] correct_claim claim_id=%s profile_id=%s via RPC",
        claim_id,
        profile_id,
    )
    try:
        rpc_resp = client.rpc(
            "correct_profile_claim",
            {
                "p_claim_id": claim_id,
                "p_tenant_id": tenant_id,
                "p_profile_id": profile_id,
                "p_claim_type": claim_type,
                "p_value_json": value_json,
                "p_value_text": value_text,
                "p_reviewed_by": reviewed_by,
                "p_confidence": confidence,
                "p_fingerprint": fingerprint,
            },
        ).execute()
    except Exception as exc:
        msg = str(exc)
        if "cannot correct state" in msg or "claim not found" in msg:
            raise ValueError(f"[passport_claims] {msg}") from exc
        raise

    # RPC returns a scalar uuid (or wrapped)
    data = getattr(rpc_resp, "data", None) if rpc_resp is not None else None
    if isinstance(data, list) and data:
        new_claim_id = str(data[0])
    elif isinstance(data, str):
        new_claim_id = data
    elif data is not None:
        new_claim_id = str(data)
    else:
        raise RuntimeError(
            f"[passport_claims] correct_profile_claim returned empty for claim_id={claim_id}"
        )

    logger.info(
        "[passport_claims] inserted corrected claim new_claim_id=%s supersedes=%s reviewed_by=%s",
        new_claim_id,
        claim_id,
        reviewed_by,
    )
    return new_claim_id
