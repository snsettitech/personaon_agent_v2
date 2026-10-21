"""Metrics and profile insights endpoints for twins."""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

logger = logging.getLogger(__name__)
from modules.auth_guard import get_current_user, verify_owner, verify_twin_ownership
from modules.graph_context import get_graph_stats
from modules.observability import supabase
from modules.public_profile_pack import build_public_profile_pack
from modules.training_metrics import (
    get_mind_score_label,
    is_training_metrics_enabled,
)
from routers.twins_helpers import (
    _coerce_training_metrics_payload,
    _dedupe_questions,
    _extract_name_research_questions,
    _normalize_name_key,
    _require_authenticated_user,
    _to_non_negative_int,
    ensure_twin_owner_or_403,
)

router = APIRouter(tags=["twins"])


@router.get("/twins/{twin_id}/metrics/debug")
async def get_twin_metrics_debug(twin_id: str, user=Depends(get_current_user)):
    """
    Get detailed training metrics breakdown for debugging/explainability.

    Returns component scores and internal calculations for the Mind Score.
    This endpoint is for debugging purposes and may expose internal details.

    Args:
        twin_id: Twin ID to get metrics for

    Returns:
        Detailed metrics breakdown including:
        - Component scores (volume, diversity, quality, etc.)
        - Source counts and statistics
        - Calculation metadata
    """
    user = _require_authenticated_user(user)
    verify_twin_ownership(twin_id, user)

    if not is_training_metrics_enabled():
        raise HTTPException(status_code=403, detail="Training metrics feature is disabled")

    try:
        from modules.training_metrics import compute_training_metrics

        metrics = compute_training_metrics(twin_id)

        return {
            "twin_id": twin_id,
            "public_metrics": {
                "words_processed": metrics.words_processed,
                "words_processed_display": metrics.words_processed_display,
                "questions_answerable_est": metrics.questions_answerable_est,
                "questions_answerable_display": metrics.questions_answerable_display,
                "mind_score": metrics.mind_score,
                "mind_score_label": metrics.mind_score_label,
                "method_version": metrics.method_version,
                "last_computed_at": metrics.last_computed_at,
            },
            "debug": {
                "component_scores": metrics.component_scores,
                "source_count": metrics.source_count,
                "failed_source_count": metrics.failed_source_count,
                "source_type_diversity": metrics.source_type_diversity,
                "calculation_notes": metrics.notes,
            },
            "formulas": {
                "mind_score": "0.25*volume + 0.20*diversity + 0.20*quality + 0.10*freshness + 0.15*structure + 0.10*verification",
                "volume_score": "logarithmic tiers (0-100)",
                "diversity_score": "unique_source_types * 20 (max 100)",
                "quality_score": "extraction_success_rate * 100",
                "questions_estimate": "(words/90) * quality * diversity * 0.85",
            }
        }
    except Exception as e:
        logger.error("[TWINS] Error getting debug metrics for twin %s: %s", twin_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to compute metrics: {str(e)}")


@router.post("/twins/{twin_id}/metrics/recompute")
async def recompute_twin_metrics(twin_id: str, user=Depends(verify_owner)):
    """
    Manually trigger metrics recomputation for a twin.

    This is useful for:
    - Debugging metrics issues
    - Forcing refresh after data corrections
    - Admin maintenance

    Args:
        twin_id: Twin ID to recompute metrics for

    Returns:
        Updated training metrics
    """
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    if not is_training_metrics_enabled():
        raise HTTPException(status_code=403, detail="Training metrics feature is disabled")

    try:
        from modules.training_metrics import (
            get_training_metrics_for_api,
            update_twin_training_metrics,
        )

        # Force recompute by updating stored metrics
        success = update_twin_training_metrics(twin_id)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to update metrics")

        # Return fresh metrics
        metrics = get_training_metrics_for_api(twin_id)

        return {
            "status": "success",
            "message": "Metrics recomputed successfully",
            "training_metrics": metrics["training_metrics"]
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[TWINS] Error recomputing metrics for twin %s: %s", twin_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to recompute metrics: {str(e)}")


@router.get("/twins/{twin_id}/profile-insights")
async def get_twin_profile_insights(twin_id: str, user=Depends(get_current_user)):
    """
    Aggregate profile-facing metrics and starter questions for chat.

    Combines:
    - Twin onboarding training metrics (settings.training_metrics)
    - Latest matching name-deep-research metrics (if available)
    - Suggested follow-up chat questions from deep research artifacts
    """
    user = _require_authenticated_user(user)
    verify_twin_ownership(twin_id, user)

    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="User has no tenant association")

    twin_res = supabase.table("twins").select("id,name,settings").eq("id", twin_id).eq("tenant_id", tenant_id).single().execute()
    if not twin_res.data:
        raise HTTPException(status_code=404, detail="Twin not found")

    twin = twin_res.data
    settings = twin.get("settings") or {}
    twin_metrics = _coerce_training_metrics_payload(settings.get("training_metrics"))

    # Owner-only profile-extraction review flags (consumer side of the
    # owner-confirm feature). Read from settings.persona_profile.extraction_review;
    # None when absent. This is internal metadata and is gated behind the
    # owner-ownership check above — it is never exposed on public profiles.
    persona_profile = settings.get("persona_profile") if isinstance(settings.get("persona_profile"), dict) else {}
    extraction_review = persona_profile.get("extraction_review") or None

    # Resolve best identity name from latest twin research run, fallback to twin name.
    identity_name = str(twin.get("name") or "").strip()
    latest_twin_research_run_id = None
    try:
        # Try new ADK table first; fall back to legacy table
        for _table, _name_field, _nested_field in [
            ("adk_research_runs", "subject_name", None),
            ("research_runs", "claimed_identity", "full_name"),
        ]:
            try:
                _cols = f"id,{_name_field},created_at"
                _res = (
                    supabase.table(_table)
                    .select(_cols)
                    .eq("twin_id", twin_id)
                    .order("created_at", desc=True)
                    .limit(1)
                    .execute()
                )
                if _res.data:
                    _latest = _res.data[0]
                    latest_twin_research_run_id = _latest.get("id")
                    if _nested_field is None:
                        _name = str(_latest.get(_name_field) or "").strip()
                        if _name:
                            identity_name = _name
                    else:
                        _identity = _latest.get(_name_field) or {}
                        if isinstance(_identity, dict):
                            _name = str(_identity.get(_nested_field) or "").strip()
                            if _name:
                                identity_name = _name
                    break
            except Exception:
                continue
    except Exception as e:
        logger.warning("[TWINS] Failed to resolve latest research run for %s: %s", twin_id, e)

    normalized_identity_name = _normalize_name_key(identity_name)

    name_research_summary: dict[str, Any] | None = None
    name_research_metrics: dict[str, Any] | None = None
    question_suggestions: list[str] = []

    try:
        # Pull a small candidate window for tenant and match by normalized input name.
        candidate_runs_res = (
            supabase.table("name_deep_research_runs")
            .select("id,status,input_name,input_company,run_completed_at,created_at")
            .eq("tenant_id", tenant_id)
            .order("created_at", desc=True)
            .limit(25)
            .execute()
        )
        candidate_runs = candidate_runs_res.data or []

        matched = [
            row for row in candidate_runs
            if _normalize_name_key(row.get("input_name")) == normalized_identity_name
        ]
        if not matched and candidate_runs:
            # Fallback to most recent tenant run when identity name is unavailable/missing.
            matched = candidate_runs

        selected_run = None
        for row in matched:
            if str(row.get("status") or "").lower() == "completed":
                selected_run = row
                break
        if not selected_run and matched:
            selected_run = matched[0]

        if selected_run:
            run_id = selected_run.get("id")
            name_research_summary = {
                "run_id": run_id,
                "status": selected_run.get("status"),
                "input_name": selected_run.get("input_name"),
                "run_completed_at": selected_run.get("run_completed_at"),
            }

            artifact_res = (
                supabase.table("name_deep_research_artifacts")
                .select("result_json")
                .eq("tenant_id", tenant_id)
                .eq("run_id", run_id)
                .limit(1)
                .execute()
            )
            if artifact_res.data:
                result_json = artifact_res.data[0].get("result_json") or {}
                if isinstance(result_json, dict):
                    if isinstance(result_json.get("training_metrics"), dict):
                        name_research_metrics = _coerce_training_metrics_payload(result_json.get("training_metrics"))
                    else:
                        # Fallback when artifact predates embedded training_metrics.
                        words_extracted = _to_non_negative_int(
                            (result_json.get("crawl_stats") or {}).get("words_extracted"), 0
                        )
                        fallback_questions = _to_non_negative_int(words_extracted / 90, 0)
                        fallback_mind = min(100, _to_non_negative_int(words_extracted / 1000, 0))
                        name_research_metrics = _coerce_training_metrics_payload(
                            {
                                "words_processed": words_extracted,
                                "questions_answerable_est": fallback_questions,
                                "mind_score": fallback_mind,
                                "mind_score_label": get_mind_score_label(fallback_mind),
                                "method_version": "name_research_fallback_v1",
                                "notes": "Estimated from name deep research crawl stats.",
                            }
                        )
                    preview_combined_questions = (
                        _to_non_negative_int(twin_metrics.get("questions_answerable_est"), 0)
                        + _to_non_negative_int((name_research_metrics or {}).get("questions_answerable_est"), 0)
                    )
                    question_suggestions = _extract_name_research_questions(result_json, preview_combined_questions)
    except Exception as e:
        logger.warning("[TWINS] Failed to load name deep research insights for twin %s: %s", twin_id, e)

    twin_words = _to_non_negative_int(twin_metrics.get("words_processed"), 0)
    twin_questions = _to_non_negative_int(twin_metrics.get("questions_answerable_est"), 0)
    twin_mind = _to_non_negative_int(twin_metrics.get("mind_score"), 0)

    name_words = _to_non_negative_int((name_research_metrics or {}).get("words_processed"), 0)
    name_questions = _to_non_negative_int((name_research_metrics or {}).get("questions_answerable_est"), 0)
    name_mind = _to_non_negative_int((name_research_metrics or {}).get("mind_score"), 0)

    combined_words = twin_words + name_words
    combined_questions = twin_questions + name_questions
    combined_mind = min(100, max(twin_mind, name_mind))
    combined_metrics = _coerce_training_metrics_payload(
        {
            "words_processed": combined_words,
            "questions_answerable_est": combined_questions,
            "mind_score": combined_mind,
            "mind_score_label": get_mind_score_label(combined_mind),
            "method_version": "combined_v1",
            "notes": (
                "Combined estimate from twin onboarding training metrics and latest name deep research run. "
                "Counts may overlap across sources."
            ),
        }
    )

    # If name-research suggestions are unavailable, fall back to pinned profile questions.
    if not question_suggestions:
        public_profile = settings.get("public_profile") if isinstance(settings.get("public_profile"), dict) else {}
        pinned = public_profile.get("pinned_questions") if isinstance(public_profile.get("pinned_questions"), list) else []
        question_suggestions = _dedupe_questions(
            [
                *pinned,
                "What are the top questions you can answer about me right now?",
                "What details in my profile should I verify next?",
            ],
            limit=12,
        )

    capacity_prompt = (
        f"What are the top {min(max(combined_questions, 5), 20)} questions you can answer about me right now?"
        if combined_questions > 0
        else "What can you confidently answer about me right now?"
    )

    return {
        "twin_id": twin_id,
        "identity_name": identity_name,
        "latest_twin_research_run_id": latest_twin_research_run_id,
        "profile_pack": build_public_profile_pack(twin),
        "extraction_review": extraction_review,
        "name_deep_research": name_research_summary,
        "metrics": {
            "combined": combined_metrics,
            "twin_onboarding": twin_metrics,
            "name_deep_research": name_research_metrics,
        },
        "question_suggestions": question_suggestions,
        "question_capacity_estimate": combined_questions,
        "question_capacity_prompt": capacity_prompt,
    }


@router.post("/twins/{twin_id}/profile-insights/dismiss-review")
async def dismiss_twin_extraction_review(twin_id: str, user=Depends(get_current_user)):
    """
    Clear the owner-only extraction-review flag for a twin.

    Owner-confirm feature: once the profile owner has reviewed/corrected the
    flagged work-experience claims, this drops
    ``settings.persona_profile.extraction_review`` so the review card no longer
    surfaces. Merge-safe (read current settings -> drop the key -> update);
    no other settings are touched. Owner-only.
    """
    user = _require_authenticated_user(user)
    verify_twin_ownership(twin_id, user)

    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=403, detail="User has no tenant association")

    logger.info("[TWINS] dismissing extraction_review twin_id=%s", twin_id)

    try:
        twin_res = supabase.table("twins").select("id,settings").eq("id", twin_id).eq("tenant_id", tenant_id).single().execute()
        if not twin_res.data:
            raise HTTPException(status_code=404, detail="Twin not found")

        settings = twin_res.data.get("settings") if isinstance(twin_res.data.get("settings"), dict) else {}
        persona_profile = settings.get("persona_profile") if isinstance(settings.get("persona_profile"), dict) else {}

        if "extraction_review" not in persona_profile:
            # Already cleared (or never set) — idempotent no-op, no write needed.
            logger.info("[TWINS] extraction_review already absent twin_id=%s", twin_id)
            return {"status": "ok", "data": {"extraction_review": None}}

        # Merge-safe: build new objects, never mutate the fetched dicts in place.
        new_persona_profile = {k: v for k, v in persona_profile.items() if k != "extraction_review"}
        new_settings = {**settings, "persona_profile": new_persona_profile}

        supabase.table("twins").update({"settings": new_settings}).eq("id", twin_id).eq("tenant_id", tenant_id).execute()

        logger.info("[TWINS] extraction_review cleared twin_id=%s", twin_id)
        return {"status": "ok", "data": {"extraction_review": None}}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[TWINS] failed to dismiss extraction_review twin_id=%s", twin_id)
        raise HTTPException(status_code=500, detail="Failed to dismiss extraction review") from e


@router.get("/twins/{twin_id}/graph-stats")
async def get_twin_graph_stats(twin_id: str, user=Depends(get_current_user)):
    """Get graph statistics for a twin's content."""
    user = _require_authenticated_user(user)
    ensure_twin_owner_or_403(twin_id, user)

    try:
        stats = await get_graph_stats(twin_id)
        return stats
    except Exception as e:
        logger.error("[TWINS] ERROR getting graph stats: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
