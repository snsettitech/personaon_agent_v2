"""
import_routes.py

Endpoints for importing structured data exports (LinkedIn, etc.) into the
twin's profile pack and Pinecone index.

Routes:
    POST /persona/import/linkedin-export   Upload LinkedIn ZIP → profile pack
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File

from modules.auth_guard import get_current_user, verify_twin_ownership
from modules.observability import supabase
from modules.linkedin_export_parser import parse_linkedin_export_zip
from modules.public_profile_pack import merge_profile_fields_partial

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/persona", tags=["import"])

_MAX_ZIP_BYTES = 50 * 1024 * 1024  # 50 MB


@router.post("/{twin_id}/import/linkedin-export")
async def import_linkedin_export(
    twin_id: str,
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    """
    Upload a LinkedIn 'Download My Data' ZIP export and merge the structured
    profile fields (name, headline, work history, education, skills) into the
    twin's public_profile without overwriting any higher-confidence data.

    Marks `public_profile_meta.linkedin_export_imported = true` on success so
    the dashboard nudge card can be suppressed.
    """
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    verify_twin_ownership(twin_id, user)

    # Validate file type
    filename_lower = (file.filename or "").lower()
    if not filename_lower.endswith(".zip"):
        raise HTTPException(
            status_code=400,
            detail="Expected a LinkedIn export ZIP file (.zip)",
        )

    raw_bytes = await file.read()
    if len(raw_bytes) > _MAX_ZIP_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {_MAX_ZIP_BYTES // (1024*1024)} MB",
        )

    # Parse the ZIP
    extracted = parse_linkedin_export_zip(raw_bytes)
    if not extracted:
        raise HTTPException(
            status_code=422,
            detail="Could not extract profile data from the ZIP. "
                   "Make sure this is a LinkedIn 'Download My Data' export.",
        )

    # Fetch current twin settings
    twin_res = (
        supabase.table("twins")
        .select("settings")
        .eq("id", twin_id)
        .single()
        .execute()
    )
    if not twin_res.data:
        raise HTTPException(status_code=404, detail="Twin not found")

    current_settings: dict[str, Any] = dict(twin_res.data.get("settings") or {})
    current_public_profile: dict[str, Any] = dict(
        current_settings.get("public_profile") or {}
    )

    # Merge extracted fields — fills empty fields, never overwrites higher-confidence data
    confidence = extracted.get("confidence", 0.80)
    updated_profile = merge_profile_fields_partial(
        current_public_profile,
        extracted,
        source_confidence=confidence,
    )

    # Mark import done in profile_meta
    profile_meta: dict[str, Any] = dict(
        current_settings.get("public_profile_meta") or {}
    )
    profile_meta["linkedin_export_imported"] = True

    current_settings["public_profile"] = updated_profile
    current_settings["public_profile_meta"] = profile_meta

    supabase.table("twins").update({"settings": current_settings}).eq("id", twin_id).execute()

    logger.info(
        "import_linkedin_export: merged LinkedIn export for twin %s (%d fields)",
        twin_id,
        len([k for k in extracted if k != "confidence"]),
    )

    # Summarise what was imported for the UI
    imported_fields = [k for k in extracted if k not in ("confidence",)]
    return {
        "status": "ok",
        "fields_imported": imported_fields,
        "work_experience_count": len(extracted.get("work_experience") or []),
        "education_count": len(extracted.get("education") or []),
        "skills_count": len(extracted.get("areas_of_expertise") or []),
    }
