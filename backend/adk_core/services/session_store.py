"""Supabase-backed ADK session service."""

from __future__ import annotations

import copy
import logging
import time
import uuid
from typing import Any

from google.adk.events import Event
from google.adk.sessions import BaseSessionService, Session
from google.adk.sessions.base_session_service import GetSessionConfig, ListSessionsResponse

from adk_core.repositories.session_repository import SessionRepository

logger = logging.getLogger(__name__)


# Rolling window caps for session.events. Chat needs a small cap to avoid
# unbounded growth across many turns. Research/compiler are single-turn
# workflows with longer tool chains, so they need a larger buffer.
_DEFAULT_MAX_SESSION_EVENTS = 30
_APP_MAX_SESSION_EVENTS = {
    "adk_research": 120,
    "adk_compiler": 80,
}

_TEMP_PREFIX = "temp:"


# Large temp keys that contain scraped web content — strip before persisting
# to prevent 80KB+ blob growth per session row.
_LARGE_TEMP_KEYS = {
    "temp:scraped_sources_json",
    "temp:search_results_json",
}


def _strip_temp_state(session: Session) -> Session:
    """Strip large temp: keys (scraped content) but keep small ones (citations, briefs).

    Small temp: keys like temp:fact_context_json, temp:coordinator_brief are
    needed by ADK instruction template injection on session reload.
    Large temp: keys contain full scraped web pages and must not be persisted.
    Empty defaults ("[]") are preserved so ADK key templating doesn't throw
    KeyError when downstream agents reference them.
    """
    persistent_state = {}
    for k, v in session.state.items():
        if k in _LARGE_TEMP_KEYS:
            # Keep empty defaults, strip only populated content
            if isinstance(v, str) and v.strip() in ("[]", "{}", ""):
                persistent_state[k] = v
            # else: skip (large content)
        else:
            persistent_state[k] = v
    persisted = copy.copy(session)
    persisted.state = persistent_state
    return persisted


def _event_limit_for_app(app_name: str) -> int:
    """Return the rolling event cap for a given ADK app."""
    return _APP_MAX_SESSION_EVENTS.get(app_name, _DEFAULT_MAX_SESSION_EVENTS)


def _trim_events_preserving_turn_boundaries(events: list[Event], max_events: int) -> list[Event]:
    """Trim old events, but never cut through an active tool turn.

    Gemini tool calling is strict about turn ordering. If a persisted session
    starts mid-turn because we trimmed away the earlier user/function-response
    context, a later replay can fail with INVALID_ARGUMENT. Trim only after a
    completed turn boundary.
    """
    if len(events) <= max_events:
        return events

    for idx, existing_event in enumerate(events):
        if not getattr(existing_event, "turn_complete", False):
            continue
        next_idx = idx + 1
        if next_idx >= len(events):
            break
        if len(events) - next_idx <= max_events:
            return events[next_idx:]

    return events


class AdkDatabaseSessionService(BaseSessionService):
    """Stores ADK Session objects in the authoritative adk_sessions table."""

    def __init__(self, repository: SessionRepository | None = None):
        super().__init__()
        self._repository = repository or SessionRepository()

    def _save(self, session: Session) -> None:
        """Persist session to Supabase, stripping temp: keys."""
        persisted = _strip_temp_state(session)
        self._repository.save(
            session=persisted,
            tenant_id=session.state.get("session:tenant_id"),
            twin_id=session.state.get("session:twin_id"),
        )

    async def create_session(
        self,
        *,
        app_name: str,
        user_id: str,
        state: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> Session:
        session = Session(
            id=session_id or str(uuid.uuid4()),
            app_name=app_name,
            user_id=user_id,
            state=state or {},
            events=[],
            last_update_time=time.time(),
        )
        self._save(session)
        return session

    async def get_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        config: GetSessionConfig | None = None,
    ) -> Session | None:
        del config
        return self._repository.get(app_name=app_name, user_id=user_id, session_id=session_id)

    async def list_sessions(
        self,
        *,
        app_name: str,
        user_id: str | None = None,
    ) -> ListSessionsResponse:
        return ListSessionsResponse(sessions=self._repository.list(app_name=app_name, user_id=user_id))

    async def delete_session(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> None:
        self._repository.delete(app_name=app_name, user_id=user_id, session_id=session_id)

    async def append_event(self, session: Session, event: Event) -> Event:
        event = await super().append_event(session, event)
        # Trim to a rolling window, but preserve full in-flight tool turns.
        # Research/compiler often emit long tool sequences in a single
        # turn, and trimming those mid-turn can break Gemini function-call
        # replay semantics on the next model call.
        max_events = _event_limit_for_app(session.app_name)
        original_len = len(session.events)
        if original_len > max_events:
            trimmed = _trim_events_preserving_turn_boundaries(session.events, max_events)
            if len(trimmed) == original_len and original_len == max_events + 1:
                logger.warning(
                    "session_store: deferring trim for %s session %s because no completed turn boundary exists yet",
                    session.app_name,
                    session.id,
                )
            session.events = trimmed
        session.last_update_time = time.time()
        self._save(session)
        return event

    async def patch_state(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
        patch: dict[str, Any],
    ) -> None:
        """Merge patch into an existing session's state without replacing it."""
        session = await self.get_session(
            app_name=app_name, user_id=user_id, session_id=session_id
        )
        if session:
            session.state.update(patch)
            session.last_update_time = time.time()
            self._save(session)
