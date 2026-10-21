"""Interaction context contracts for owner-training flows."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class InteractionContext(str, Enum):
    OWNER_TRAINING = "owner_training"
    OWNER_CHAT = "owner_chat"
    PUBLIC_SHARE = "public_share"
    PUBLIC_WIDGET = "public_widget"


class ResolvedInteractionContext(BaseModel):
    context: InteractionContext
    origin_endpoint: str
    training_session_id: str | None = None
