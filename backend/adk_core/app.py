"""Root assembly for ADK runners and repositories."""

from __future__ import annotations

from functools import lru_cache

from adk_core.repositories import ConversationRepository, PersonaRepository, ResearchRepository, SessionRepository
from adk_core.services import AdkDatabaseSessionService


# ── Repository singletons ────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def get_session_repository() -> SessionRepository:
    return SessionRepository()


@lru_cache(maxsize=1)
def get_session_service() -> AdkDatabaseSessionService:
    return AdkDatabaseSessionService(repository=get_session_repository())


@lru_cache(maxsize=1)
def get_research_repository() -> ResearchRepository:
    return ResearchRepository()


@lru_cache(maxsize=1)
def get_persona_repository() -> PersonaRepository:
    return PersonaRepository()


@lru_cache(maxsize=1)
def get_conversation_repository() -> ConversationRepository:
    return ConversationRepository()
