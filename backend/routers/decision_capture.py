"""Owner-training decision capture endpoints."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from modules.auth_guard import ensure_twin_active, get_current_user, verify_twin_ownership
from modules.interaction_context import InteractionContext, ResolvedInteractionContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/twins/{twin_id}/decision-capture", tags=["decision-capture"])


class SjtCaptureRequest(BaseModel):
    training_session_id: str
    prompt: str
    options: list[dict[str, Any]]
    selected_option: str
    intent_label: str | None = None
    rationale: str | None = None
    thresholds: dict[str, Any] = Field(default_factory=dict)


class PairwiseCaptureRequest(BaseModel):
    training_session_id: str
    prompt: str
    candidate_a: dict[str, Any]
    candidate_b: dict[str, Any]
    preferred: Literal["a", "b"]


class IntrospectionCaptureRequest(BaseModel):
    training_session_id: str
    question: str
    answer: str
    thresholds: dict[str, Any] = Field(default_factory=dict)


def require_owner_training_context(training_session_id: str) -> ResolvedInteractionContext:
    if not training_session_id:
        raise HTTPException(status_code=403, detail="owner_training context required")
    return ResolvedInteractionContext(
        context=InteractionContext.OWNER_TRAINING,
        origin_endpoint="decision_capture",
        training_session_id=training_session_id,
    )


def record_sjt_capture(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise HTTPException(status_code=501, detail="SJT decision capture persistence is not configured")


def record_pairwise_capture(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise HTTPException(status_code=501, detail="Pairwise decision capture persistence is not configured")


def record_introspection_capture(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    raise HTTPException(status_code=501, detail="Introspection decision capture persistence is not configured")


def _response(capture_type: str, context: ResolvedInteractionContext, result: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "recorded",
        "capture_type": capture_type,
        "interaction_context": context.context.value,
        "training_session_id": context.training_session_id,
        "event": result.get("event"),
        "module": result.get("module"),
        "clause_ids": result.get("clause_ids") or [],
    }


@router.post("/sjt")
async def capture_sjt_decision(
    twin_id: str,
    body: SjtCaptureRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    verify_twin_ownership(twin_id, user)
    ensure_twin_active(twin_id)
    context = require_owner_training_context(body.training_session_id)
    result = record_sjt_capture(twin_id=twin_id, user=user, body=body, context=context)
    return _response("sjt", context, result)


@router.post("/pairwise")
async def capture_pairwise_decision(
    twin_id: str,
    body: PairwiseCaptureRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    verify_twin_ownership(twin_id, user)
    ensure_twin_active(twin_id)
    context = require_owner_training_context(body.training_session_id)
    result = record_pairwise_capture(twin_id=twin_id, user=user, body=body, context=context)
    return _response("pairwise", context, result)


@router.post("/introspection")
async def capture_introspection_decision(
    twin_id: str,
    body: IntrospectionCaptureRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    verify_twin_ownership(twin_id, user)
    ensure_twin_active(twin_id)
    context = require_owner_training_context(body.training_session_id)
    result = record_introspection_capture(twin_id=twin_id, user=user, body=body, context=context)
    return _response("introspection", context, result)
