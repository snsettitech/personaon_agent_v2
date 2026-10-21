"""
Shared profile (single-twin) selection helpers.

These helpers keep canonical twin selection logic consistent across:
- auth router (/auth/my-twins, /auth/me)
- profile router (/profile*)
- name deep-research service
"""

from __future__ import annotations

from typing import Any
from collections.abc import Iterable

from modules.tenant_guard import derive_creator_ids


def _safe_settings(twin: dict[str, Any]) -> dict[str, Any]:
    settings = twin.get("settings")
    return settings if isinstance(settings, dict) else {}


def normalize_twin_status_shape(twin: dict[str, Any]) -> dict[str, Any]:
    """
    Keep status stable when older schemas are missing `twins.status`.
    """
    if not isinstance(twin, dict):
        return twin
    if twin.get("status"):
        return twin

    if twin.get("is_active") is True:
        twin["status"] = "active"
    return twin


def build_creator_candidates(
    *,
    user: dict[str, Any] | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
) -> set[str]:
    candidates: set[str] = set()

    if isinstance(user, dict):
        for creator in derive_creator_ids(user) or []:
            candidates.add(str(creator))
        if not user_id:
            user_id = str(user.get("user_id") or user.get("id") or "").strip() or None
        if not tenant_id:
            tenant_id = str(user.get("tenant_id") or "").strip() or None

    if user_id:
        candidates.add(str(user_id))
    if tenant_id:
        candidates.add(f"tenant_{tenant_id}")

    return candidates


def _score_profile_twin(
    twin: dict[str, Any],
    *,
    user_id: str,
    creator_candidates: set[str],
) -> int:
    score = 0
    creator_id = str(twin.get("creator_id") or "").strip()
    settings = _safe_settings(twin)
    owner_user_id = str(settings.get("owner_user_id") or "").strip()
    status = str(twin.get("status") or "").lower()

    if owner_user_id and user_id and owner_user_id == user_id:
        score += 100
    if creator_id and user_id and creator_id == user_id:
        score += 80
    if creator_id and creator_id in creator_candidates:
        score += 40
    if status == "active":
        score += 20
    if status == "persona_built":
        score += 10
    return score


def select_profile_twin_from_rows(
    *,
    rows: Iterable[dict[str, Any]],
    user_id: str | None,
    creator_candidates: set[str],
    allow_single_legacy_fallback: bool = True,
) -> dict[str, Any] | None:
    """
    Select the canonical profile twin from candidate rows.
    """
    normalized_rows: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        copied = dict(row)
        if _safe_settings(copied).get("deleted_at"):
            continue
        normalized_rows.append(normalize_twin_status_shape(copied))

    if not normalized_rows:
        return None

    user_id = str(user_id or "").strip()

    strong_matches: list[dict[str, Any]] = []
    for twin in normalized_rows:
        settings = _safe_settings(twin)
        owner_user_id = str(settings.get("owner_user_id") or "").strip()
        creator_id = str(twin.get("creator_id") or "").strip()
        if (user_id and owner_user_id == user_id) or (user_id and creator_id == user_id):
            strong_matches.append(twin)

    if strong_matches:
        candidates = strong_matches
    else:
        legacy_matches: list[dict[str, Any]] = []
        for twin in normalized_rows:
            settings = _safe_settings(twin)
            owner_user_id = str(settings.get("owner_user_id") or "").strip()
            creator_id = str(twin.get("creator_id") or "").strip()
            if owner_user_id:
                continue
            if creator_id and creator_id in creator_candidates:
                legacy_matches.append(twin)

        if len(legacy_matches) == 1:
            candidates = legacy_matches
        elif allow_single_legacy_fallback and len(normalized_rows) == 1:
            only = normalized_rows[0]
            settings = _safe_settings(only)
            owner_user_id = str(settings.get("owner_user_id") or "").strip()
            creator_id = str(only.get("creator_id") or "").strip()
            if owner_user_id:
                return None
            if creator_id and creator_id not in creator_candidates and not creator_id.startswith("tenant_"):
                return None
            candidates = [only]
        else:
            return None

    ranked = sorted(
        candidates,
        key=lambda twin: (
            _score_profile_twin(
                twin,
                user_id=user_id,
                creator_candidates=creator_candidates,
            ),
            str(twin.get("created_at") or ""),
        ),
        reverse=True,
    )
    return ranked[0] if ranked else None

