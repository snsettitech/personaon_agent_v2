"""
Share Links Module

Handles generation and validation of public share tokens for twins.
"""
import hmac
import logging
import os
import uuid
from datetime import datetime
from typing import Any
from modules.observability import supabase
from modules.text_quality import HEADLINE_MIN_LENGTH, is_meaningful_text, meaningful_text_error

logger = logging.getLogger(__name__)
from modules.governance import AuditLogger

PUBLIC_TWIN_STATUSES = {"active"}


def _fetch_twin_row(twin_id: str) -> dict[str, Any] | None:
    """Fetch a twin row with the fields needed for public-share decisions."""
    try:
        response = (
            supabase.table("twins")
            .select("id, tenant_id, status, settings")
            .eq("id", twin_id)
            .single()
            .execute()
        )
    except Exception:
        return None
    return response.data or None


def _get_tenant_id(twin_id: str) -> str | None:
    """Helper to resolve tenant_id from twin_id."""
    try:
        row = _fetch_twin_row(twin_id)
        return row.get("tenant_id") if row else None
    except Exception:
        return None


def _get_twin_settings(twin: dict[str, Any] | None) -> dict[str, Any]:
    settings = (twin or {}).get("settings") or {}
    return settings if isinstance(settings, dict) else {}


def has_public_twin_status(twin: dict[str, Any] | None) -> bool:
    if not twin:
        return False
    settings = _get_twin_settings(twin)
    if settings.get("deleted_at"):
        return False
    status_value = str(twin.get("status") or "").lower()
    return status_value in PUBLIC_TWIN_STATUSES


def _entry_has_content(entry: Any, content_keys: tuple[str, ...]) -> bool:
    """True when at least one of `content_keys` on `entry` is a non-blank
    string. Used to distinguish a genuinely descriptive work_experience/
    education row from a name-only decoy row."""
    if not isinstance(entry, dict):
        return False
    return any(str(entry.get(key) or "").strip() for key in content_keys)


def _has_populated_section(profile: dict[str, Any]) -> bool:
    """True when the profile has at least one real, populated work_experience
    or education entry — the sections that actually render on the public
    page (execution-board 0.1, PRD R1).

    `normalize_public_profile` builds both lists through `_dedupe_object_rows`,
    which only requires ANY key field (company/role/description, or
    institution/degree/field) to be non-blank to keep a row — so a row like
    {"company": "Acme", "role": "", "description": ""} survives dedupe with
    nothing beyond a bare name. A non-empty list alone is therefore NOT
    sufficient proof of genuine content: this also requires at least one of
    the fields that actually render as substance on the public page
    (role/description for work_experience, degree/field for education) to be
    non-blank on at least one entry.
    """
    work_experience = profile.get("work_experience")
    education = profile.get("education")

    has_work = isinstance(work_experience, list) and any(
        _entry_has_content(entry, ("role", "description")) for entry in work_experience
    )
    has_education = isinstance(education, list) and any(
        _entry_has_content(entry, ("degree", "field")) for entry in education
    )
    return bool(has_work or has_education)


def is_marketplace_public_twin_record(twin: dict[str, Any] | None) -> bool:
    """Marketplace visibility rule.

    Every live twin (status in PUBLIC_TWIN_STATUSES) with a complete public
    profile is in the marketplace dataset by default. There is no separate
    per-twin opt-in flag — "live" implies "marketplace-eligible." The
    marketplace UI is gated separately at the route level until launch.

    Execution-board 0.1 (PRD R1): the previous version only checked that
    display_name/occupation/short_description were non-empty strings — none
    of which are the fields that actually render as visible public sections.
    A twin with headline "software engineer" and bio "nill" satisfied all
    three (short_description falls back to bio) and went live. Now ALSO
    requires (AND, not OR): the bio passes the shared meaningfulness bar
    (modules.text_quality — the same check used at write time), and the
    profile has at least one real work_experience or education entry.

    occupation and short_description previously only had a truthiness check
    (any non-empty string, e.g. "nill" or "x", cleared the gate). They now
    also go through the shared `is_meaningful_text` check — with the same
    low length/word-count floor used for headline text (real occupations
    and short descriptions are often terse, e.g. "Founder"), so garbage
    values no longer clear the gate on a technicality while legitimate
    short values still pass.
    """
    if not twin:
        return False

    if not has_public_twin_status(twin):
        return False

    try:
        from modules.public_profile_pack import normalize_public_profile

        profile = normalize_public_profile(twin)
    except Exception:
        return False

    display_name = str(profile.get("display_name") or "").strip()
    occupation = str(profile.get("occupation") or profile.get("role") or "").strip()
    short_description = str(profile.get("short_description") or profile.get("bio") or "").strip()
    bio = str(profile.get("bio") or "")

    return bool(
        display_name
        and is_meaningful_text(occupation, min_length=HEADLINE_MIN_LENGTH, min_words=1)
        and is_meaningful_text(short_description, min_length=HEADLINE_MIN_LENGTH, min_words=1)
        and is_meaningful_text(bio)
        and _has_populated_section(profile)
    )


def get_publish_gate_status(twin: dict[str, Any] | None) -> dict[str, Any]:
    """Read-only, specific-reason publish-gate status for the dashboard banner
    (execution-board 0.6).

    This is NOT a second, independent gate check — it re-derives the exact
    same content-quality signals `is_marketplace_public_twin_record` uses
    (`normalize_public_profile`, `is_meaningful_text` /
    `meaningful_text_error`, `_has_populated_section`), so the dashboard can
    never drift out of sync with what actually decides public reachability.

    Deliberately does NOT check `has_public_twin_status` — that's "is this
    twin currently live," a separate concern from "would this profile's
    *content* clear the quality bar if published." The dashboard uses this to
    decide whether the Publish button should be enabled and what to tell the
    owner is missing; `publish_profile` (routers/profile.py) and
    `publish_draft_twin` (routers/twins_lifecycle.py) re-run the full write-
    time gate (including status) before actually flipping a twin live.
    """
    if not twin:
        return {"passed": False, "reasons": ["Profile not found."]}

    try:
        from modules.public_profile_pack import normalize_public_profile

        profile = normalize_public_profile(twin)
    except Exception:
        logger.exception(
            "[PublishGate] normalize_public_profile failed twin=%s",
            (twin or {}).get("id"),
        )
        return {"passed": False, "reasons": ["We couldn't check your profile right now. Try again shortly."]}

    display_name = str(profile.get("display_name") or "").strip()
    occupation = str(profile.get("occupation") or profile.get("role") or "").strip()
    bio = str(profile.get("bio") or "")

    reasons: list[str] = []
    if not display_name or display_name == "Persona":
        reasons.append("Add your name.")
    if not occupation:
        reasons.append("Add your role or occupation.")
    bio_error = meaningful_text_error(bio)
    if bio_error:
        reasons.append(bio_error)
    if not _has_populated_section(profile):
        reasons.append("Add at least one work experience or education entry.")

    return {"passed": len(reasons) == 0, "reasons": reasons}


def is_publicly_accessible_twin_record(twin: dict[str, Any] | None) -> bool:
    """A twin is publicly accessible only once it is active AND passes the
    marketplace-quality gate.

    Execution-board 0.1 (PRD R1): this used to OR a `widget_settings.
    public_share_enabled` toggle against the marketplace-quality check, so
    flipping that one flag (as `publish_draft_twin` did, unconditionally)
    made an incomplete/garbage profile publicly reachable with zero content
    validation — a straight bypass of the quality gate. There is no longer
    a quality-free path to public reachability: both the active-status check
    and the marketplace-quality gate must pass.
    """
    if not twin:
        return False

    if not has_public_twin_status(twin):
        return False

    return is_marketplace_public_twin_record(twin)


def ensure_share_token(
    twin_id: str,
    *,
    enable_public_share: bool = False,
    twin_row: dict[str, Any] | None = None,
    tenant_id: str = "",
) -> str:
    """
    Ensure a twin has a share token.

    For marketplace access we can mint a token without flipping the legacy
    public-share toggle. Legacy direct-share flows can still opt into toggling.
    """
    row = twin_row or _fetch_twin_row(twin_id)
    if not row:
        raise ValueError(f"Twin {twin_id} not found")

    settings = dict(row.get("settings") or {})
    widget_settings = dict(settings.get("widget_settings") or {})
    existing_token = widget_settings.get("share_token")

    if existing_token and not enable_public_share:
        return existing_token

    if existing_token and enable_public_share and widget_settings.get("public_share_enabled", False):
        return existing_token

    share_token = existing_token or str(uuid.uuid4())
    widget_settings["share_token"] = share_token
    if enable_public_share:
        widget_settings["public_share_enabled"] = True

    settings["widget_settings"] = widget_settings
    q = supabase.table("twins").update({"settings": settings}).eq("id", twin_id)
    if tenant_id:
        q = q.eq("tenant_id", tenant_id)
    q.execute()
    return share_token


def build_public_share_path(
    twin_id: str,
    settings: dict[str, Any] | None,
    *,
    ensure_token_if_missing: bool = False,
    enable_public_share: bool = False,
) -> str | None:
    """Build the relative public URL for a twin using handle-first resolution."""
    settings = settings if isinstance(settings, dict) else {}

    handle = str(settings.get("handle") or "").strip()
    if handle:
        return f"/p/{handle}"

    widget_settings = settings.get("widget_settings") or {}
    share_token = widget_settings.get("share_token")
    if not share_token and ensure_token_if_missing:
        share_token = ensure_share_token(
            twin_id,
            enable_public_share=enable_public_share,
            twin_row={"id": twin_id, "settings": settings},
        )

    if not share_token:
        return None

    return f"/share/{twin_id}/{share_token}"



def generate_share_token(twin_id: str) -> str:
    """
    Generate or retrieve existing share token for a twin.
    Returns the share token UUID.
    """
    return ensure_share_token(twin_id, enable_public_share=True)


def regenerate_share_token(twin_id: str, *, tenant_id: str = "") -> str:
    """
    Generate a new share token (regenerates even if one exists).
    Returns the new share token UUID.
    """
    share_token = str(uuid.uuid4())

    twin_response = supabase.table("twins").select("settings").eq("id", twin_id).single().execute()

    if not twin_response.data:
        raise ValueError(f"Twin {twin_id} not found")

    settings = twin_response.data.get("settings", {})

    if "widget_settings" not in settings:
        settings["widget_settings"] = {}

    settings["widget_settings"]["share_token"] = share_token

    q = supabase.table("twins").update({"settings": settings}).eq("id", twin_id)
    if tenant_id:
        q = q.eq("tenant_id", tenant_id)
    q.execute()

    return share_token


def validate_share_token(token: str, twin_id: str) -> bool:
    """
    Validate that a share token matches the twin and sharing is enabled.
    Includes expiry check and audit logging.
    """
    try:
        twin = _fetch_twin_row(twin_id)

        if not twin:
            AuditLogger.log(
                tenant_id=_get_tenant_id(twin_id),
                twin_id=twin_id,
                event_type="SECURITY",
                action="SHARE_TOKEN_INVALID",
                metadata={"reason": "twin_not_found", "token_prefix": token[:8] if token else "none"}
            )
            return False

        settings = twin.get("settings") or {}
        widget_settings = settings.get("widget_settings", {})

        # Block archived/deleted twins
        if settings.get("deleted_at"):
            AuditLogger.log(
                tenant_id=_get_tenant_id(twin_id),
                twin_id=twin_id,
                event_type="SECURITY",
                action="SHARE_TOKEN_INVALID",
                metadata={"reason": "twin_deleted"}
            )
            return False

        # V1 public marketplace: allow twins that are marketplace-public even if
        # the legacy direct-share toggle is off.
        if not is_publicly_accessible_twin_record(twin):
            AuditLogger.log(
                tenant_id=_get_tenant_id(twin_id),
                twin_id=twin_id,
                event_type="SECURITY",
                action="SHARE_TOKEN_INVALID",
                metadata={"reason": "sharing_disabled"}
            )
            return False


        # Check if token matches using constant-time comparison. Plain `!=`
        # on Python strings short-circuits on the first mismatched character,
        # leaking timing info that an attacker on a low-latency network can
        # use to recover the token character-by-character. Audit 2026-05-31
        # second pass.
        stored_token = widget_settings.get("share_token")
        # `hmac.compare_digest` requires both inputs to be the same type.
        # Normalize to str so a None / non-string stored value doesn't crash.
        if not stored_token or not token or not hmac.compare_digest(str(stored_token), str(token)):
            AuditLogger.log(
                tenant_id=_get_tenant_id(twin_id),
                twin_id=twin_id,
                event_type="SECURITY",
                action="SHARE_TOKEN_INVALID",
                metadata={"reason": "token_mismatch", "token_prefix": token[:8] if token else "none"}
            )
            return False


        # Check expiry if set
        expires_at_str = widget_settings.get("share_token_expires_at")
        if expires_at_str:
            try:
                expires_at = datetime.fromisoformat(expires_at_str.replace('Z', '+00:00'))
            except Exception as parse_err:
                logger.warning("Error parsing share token expiry: %s", parse_err)
            else:
                if datetime.now(expires_at.tzinfo) > expires_at:
                    try:
                        AuditLogger.log(
                            tenant_id=_get_tenant_id(twin_id),
                            twin_id=twin_id,
                            event_type="SECURITY",
                            action="SHARE_TOKEN_EXPIRED",
                            metadata={"expired_at": expires_at_str}
                        )
                    except Exception as log_err:
                        logger.warning("Error logging share token expiry: %s", log_err)
                    return False

        # Log successful access (at reduced frequency to avoid log spam)
        # AuditLogger.log(twin_id, "ACCESS", "SHARE_LINK_ACCESSED", metadata={})

        return True
    except Exception as e:
        logger.warning("Error validating share token: %s", e)
        return False


def get_public_group_for_twin(twin_id: str) -> dict[str, Any] | None:
    """
    Get the public access group for a twin.
    Returns None if no public group exists.
    """
    try:
        response = (
            supabase.table("access_groups")
            .select("*")
            .eq("twin_id", twin_id)
            .eq("is_public", True)
            .limit(1)
            .execute()
        )
        rows = response.data or []
        return rows[0] if rows else None
    except Exception as e:
        logger.warning("Error getting public group for twin: %s", e)
        return None


def get_share_link_info(twin_id: str) -> dict[str, Any]:
    """
    Get share link information for a twin.
    Returns dict with share_token, share_url, and public_share_enabled.
    """
    try:
        twin = _fetch_twin_row(twin_id)

        if not twin:
            raise ValueError(f"Twin {twin_id} not found")

        settings = twin.get("settings", {})
        if settings.get("deleted_at"):
            raise ValueError("Twin is archived or deleted")
        widget_settings = settings.get("widget_settings", {})

        share_token = widget_settings.get("share_token")
        public_share_enabled = widget_settings.get("public_share_enabled", False)

        if not share_token and is_publicly_accessible_twin_record(twin):
            share_token = ensure_share_token(
                twin_id,
                enable_public_share=bool(public_share_enabled),
                twin_row=twin,
            )
            widget_settings["share_token"] = share_token

        share_path = build_public_share_path(
            twin_id,
            settings,
            ensure_token_if_missing=is_publicly_accessible_twin_record(twin),
            enable_public_share=bool(public_share_enabled),
        )
        share_url = None
        if share_path:
            frontend_url = os.getenv("FRONTEND_URL", "https://personaon.com").rstrip("/")
            share_url = f"{frontend_url}{share_path}"

        return {
            "twin_id": twin_id,
            "share_token": share_token,
            "share_url": share_url,
            "public_share_enabled": public_share_enabled
        }
    except Exception as e:
        logger.warning("Error getting share link info: %s", e)
        raise


def toggle_public_sharing(twin_id: str, enabled: bool, *, tenant_id: str = "") -> bool:
    """
    Enable or disable public sharing for a twin.
    """
    try:
        twin_response = supabase.table("twins").select("settings").eq("id", twin_id).single().execute()

        if not twin_response.data:
            raise ValueError(f"Twin {twin_id} not found")

        settings = twin_response.data.get("settings", {})

        if "widget_settings" not in settings:
            settings["widget_settings"] = {}

        settings["widget_settings"]["public_share_enabled"] = enabled

        q = supabase.table("twins").update({"settings": settings}).eq("id", twin_id)
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        q.execute()

        # Phase 9: Log the action
        AuditLogger.log(
            tenant_id=_get_tenant_id(twin_id),
            twin_id=twin_id,
            event_type="CONFIGURATION_CHANGE",
            action="SHARING_TOGGLED",
            metadata={"enabled": enabled}
        )


        return True
    except Exception as e:
        logger.warning("Error toggling public sharing: %s", e)
        return False
