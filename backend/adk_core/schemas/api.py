"""API contracts for the ADK v2 routes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator
from modules.profile_utils import normalize_external_url


class ChatTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation_id: Optional[str] = None
    lead_id: Optional[str] = None  # public-page conversational capture: echoed across turns
    message: str = Field(..., min_length=1, max_length=4096)
    client_context: Optional[Dict[str, Any]] = None
    mode_override: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Prompt override text from mode_switch action",
    )

    @field_validator("message")
    @classmethod
    def clean_message(cls, value: str) -> str:
        cleaned = " ".join((value or "").split())
        if not cleaned:
            raise ValueError("message is required")
        return cleaned


class ChatTurnResponse(BaseModel):
    conversation_id: str
    message: str
    citations: List[str] = Field(default_factory=list)
    persona_version: str
    surface: str
    lead_id: Optional[str] = None  # set when public-page lead capture is active


class ResearchRunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    subject_name: str = Field(..., min_length=1, max_length=200)
    twin_id: Optional[str] = None
    hints: Dict[str, Any] = Field(default_factory=dict)
    seed_urls: List[str] = Field(default_factory=list, max_length=5)
    idempotency_key: Optional[str] = Field(default=None, max_length=128)

    @field_validator("subject_name")
    @classmethod
    def clean_subject_name(cls, value: str) -> str:
        cleaned = " ".join((value or "").split())
        if not cleaned:
            raise ValueError("subject_name is required")
        return cleaned

    @field_validator("seed_urls", mode="before")
    @classmethod
    def clean_seed_urls(cls, value: Any) -> List[str]:
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise ValueError("seed_urls must be a list")

        normalized: List[str] = []
        seen = set()
        for raw in value:
            url = normalize_external_url(raw)
            if not url:
                continue
            if url in seen:
                continue
            seen.add(url)
            normalized.append(url)
        return normalized


class ResearchRunRecord(BaseModel):
    run_id: str
    twin_id: Optional[str] = None
    subject_name: str
    status: str
    created_at: str
    updated_at: str
    error_message: Optional[str] = None


class CompilePersonaRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    twin_id: str = Field(..., min_length=1)
    publish: bool = True


class ConversationRecord(BaseModel):
    id: str
    twin_id: str
    surface: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MessageRecord(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    citations: List[str] = Field(default_factory=list)
    created_at: Optional[str] = None
