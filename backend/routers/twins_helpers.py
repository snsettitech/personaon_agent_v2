"""Shared helper functions and models for twins router modules."""

from typing import Any
from fastapi import HTTPException
from pydantic import BaseModel
from modules.auth_guard import verify_twin_ownership
from modules.observability import supabase
from modules.training_metrics import format_number_compact, get_mind_score_label
from modules.profile_selection import normalize_twin_status_shape as _normalize_twin_status_shape_base


class DeleteTwinResponse(BaseModel):
    """Response for archive/delete twin operations."""
    status: str  # "archived" | "deleted" | "already_archived" | "not_found"
    twin_id: str
    deleted_at: str | None = None
    cleanup_status: str = "done"  # "done" | "pending"
    message: str | None = None


def ensure_twin_owner_or_403(twin_id: str, user: dict) -> dict[str, Any]:
    """
    Strict ownership check:
    - 404 if twin does not exist
    - 403 if twin exists but caller does not own the profile
    Returns the twin record.
    """
    verify_twin_ownership(twin_id, user)
    twin_res = supabase.table("twins").select("*").eq("id", twin_id).single().execute()
    if not twin_res.data:
        raise HTTPException(status_code=404, detail="Twin not found")
    return twin_res.data


def _require_authenticated_user(user: dict[str, Any] | None) -> dict[str, Any]:
    """Ensure private twin endpoints fail closed with 401 when auth is missing/invalid."""
    if not isinstance(user, dict) or not user.get("user_id"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _is_missing_column_error(error: Exception, column_name: str) -> bool:
    """Detect Supabase/PostgREST schema-cache errors for missing columns."""
    message = str(error).lower()
    col = (column_name or "").lower()
    return (
        bool(col)
        and col in message
        and (
            "pgrst204" in message
            or "could not find" in message
            or "column" in message
            or "does not exist" in message
        )
    )


def _normalize_twin_status_shape(twin: dict[str, Any]) -> dict[str, Any]:
    """Delegate to the canonical implementation in profile_selection."""
    return _normalize_twin_status_shape_base(twin)


def _normalize_name_key(value: Any) -> str:
    """Normalize a name-like field for fuzzy equality checks."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return " ".join(text.split())


def _to_non_negative_int(value: Any, default: int = 0) -> int:
    """Best-effort numeric coercion for metrics values."""
    try:
        return max(0, int(float(value)))
    except Exception:
        return default


def _coerce_training_metrics_payload(raw: Any) -> dict[str, Any]:
    """
    Normalize arbitrary training metrics payloads to a UI-safe shape.

    Keeps compatibility with both twin.settings.training_metrics and
    name_deep_research result_json.training_metrics.
    """
    data = raw if isinstance(raw, dict) else {}
    words_processed = _to_non_negative_int(data.get("words_processed"), 0)
    questions_answerable_est = _to_non_negative_int(data.get("questions_answerable_est"), 0)
    mind_score = min(100, _to_non_negative_int(data.get("mind_score"), 0))

    return {
        "words_processed": words_processed,
        "words_processed_display": str(data.get("words_processed_display") or format_number_compact(words_processed)),
        "questions_answerable_est": questions_answerable_est,
        "questions_answerable_display": str(
            data.get("questions_answerable_display") or format_number_compact(questions_answerable_est)
        ),
        "mind_score": mind_score,
        "mind_score_label": str(data.get("mind_score_label") or get_mind_score_label(mind_score)),
        "method_version": str(data.get("method_version") or "v1_heuristic"),
        "notes": str(
            data.get("notes")
            or "Estimated metrics based on ingested content volume, diversity, and extraction quality."
        ),
        "last_computed_at": data.get("last_computed_at"),
    }


def _dedupe_questions(values: list[Any], limit: int = 12) -> list[str]:
    """Deduplicate while preserving order."""
    seen = set()
    out: list[str] = []
    for raw in values:
        question = str(raw or "").strip()
        if not question:
            continue
        key = " ".join(question.lower().split())
        if key in seen:
            continue
        seen.add(key)
        out.append(question)
        if len(out) >= limit:
            break
    return out


def _extract_name_research_questions(result_json: dict[str, Any], combined_questions_estimate: int) -> list[str]:
    """Build chat-ready suggested questions from name deep research artifacts."""
    collected: list[Any] = []

    follow_ups = result_json.get("suggested_followup_questions")
    if isinstance(follow_ups, list):
        collected.extend(follow_ups)

    prepared = result_json.get("prepared_question_answers")
    if isinstance(prepared, list):
        for item in prepared:
            if isinstance(item, dict):
                collected.append(item.get("question"))

    # Generic "capacity exploration" prompts to let users ask broad questions.
    if combined_questions_estimate > 0:
        top_n = min(max(combined_questions_estimate, 5), 20)
        collected.append(f"What are the top {top_n} questions you can answer about me right now?")
    collected.append("Which parts of my profile still need stronger evidence?")
    collected.append("Show me the support and source citations for your next answer.")

    return _dedupe_questions(collected, limit=12)
