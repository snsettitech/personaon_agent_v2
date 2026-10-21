"""
PostHog server-side analytics for PersonaOn API.

Tracks backend events that the frontend can't observe:
- Research pipeline completion/failure
- Ingestion results
- Chat API latency and quality signals
- Twin lifecycle (creation, deletion, status changes)
- Auth sync (new vs returning user)

Usage:
    from modules.posthog_analytics import ph_capture, ph_identify, ph_shutdown

    ph_capture(user_id="abc", event="research_completed", properties={...})
    ph_identify(user_id="abc", properties={"email": "...", "plan": "free"})
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from typing import Any

logger = logging.getLogger(__name__)

_client: Any = None
_client_lock = threading.Lock()
_atexit_registered = False


def _get_client() -> Any:
    """Lazily initialize the PostHog client. Returns None if not configured.

    After ``_shutdown()`` the global is cleared, so the next call builds a
    fresh client instead of queueing onto one whose consumer threads are gone.
    """
    global _client, _atexit_registered
    client = _client
    if client is not None:
        return client

    api_key = os.getenv("POSTHOG_API_KEY")
    if not api_key:
        return None

    with _client_lock:
        if _client is not None:
            return _client
        try:
            from posthog import Posthog

            host = os.getenv("POSTHOG_HOST", "https://us.i.posthog.com")
            _client = Posthog(
                project_api_key=api_key,
                host=host,
                debug=os.getenv("POSTHOG_DEBUG", "").lower() in ("1", "true"),
                on_error=_on_error,
            )
            if not _atexit_registered:
                atexit.register(_shutdown)
                _atexit_registered = True
            return _client
        except Exception as exc:
            logger.error("[PostHog] Failed to initialize: %s", exc)
            return None


def _on_error(error: Exception, items: list[Any]) -> None:
    logger.warning("[PostHog] Flush error: %s (%s items)", error, len(items))


def _shutdown() -> None:
    """Flush pending events and drop the client. Critical for Cloud Run.

    The global is detached *before* flushing, so a second call (e.g. a later
    app lifespan, or atexit after ph_shutdown) is a no-op rather than a
    flush() on a client whose consumer threads already exited, which blocks
    forever in queue.join().
    """
    global _client
    with _client_lock:
        client, _client = _client, None
    if client is None:
        return
    try:
        client.shutdown()
    except Exception as exc:
        logger.warning("[PostHog] shutdown failed (non-fatal): %s", exc)


def ph_capture(
    *,
    user_id: str,
    event: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """Capture a server-side event.

    Analytics is fire-and-forget: a telemetry failure must NEVER propagate to
    the caller. sync_user (and other core flows) call this on the request
    path, so a raised exception here would 500 the endpoint. Swallow + log.
    """
    client = _get_client()
    if client is None:
        return
    try:
        client.capture(
            distinct_id=user_id,
            event=event,
            properties=properties or {},
        )
    except Exception as exc:
        logger.warning("[PostHog] capture failed (non-fatal) event=%s: %s", event, exc)


def ph_identify(
    *,
    user_id: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """Identify or update a user's person properties.

    PostHog Python SDK 6+/7.x removed the top-level ``identify()`` method;
    person properties are now set with ``client.set(distinct_id=,
    properties=)``. Using the old name raised AttributeError, which 500'd
    /auth/sync-user — and since the desktop app calls sync-user before every
    recording, that blocked all recording. Wrapped so analytics can never
    break the caller.
    """
    client = _get_client()
    if client is None:
        return
    try:
        client.set(
            distinct_id=user_id,
            properties=properties or {},
        )
    except Exception as exc:
        logger.warning("[PostHog] set/identify failed (non-fatal) user=%s: %s", user_id, exc)


def ph_group_identify(
    *,
    group_type: str,
    group_key: str,
    properties: dict[str, Any] | None = None,
) -> None:
    """Identify a group (e.g. tenant/organization)."""
    client = _get_client()
    if client is None:
        return
    try:
        client.group_identify(
            group_type=group_type,
            group_key=group_key,
            properties=properties or {},
        )
    except Exception as exc:
        logger.warning("[PostHog] group_identify failed (non-fatal) group=%s/%s: %s", group_type, group_key, exc)


def ph_ai_generation(
    *,
    user_id: str,
    trace_id: str,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    latency_seconds: float,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit a PostHog $ai_generation event for LLM observability.

    PostHog uses this to populate the LLM Analytics dashboard with cost,
    latency, token usage, and error rate breakdowns.
    """
    client = _get_client()
    if client is None:
        return
    properties: dict[str, Any] = {
        "$ai_provider": provider,
        "$ai_model": model,
        "$ai_input_tokens": input_tokens,
        "$ai_output_tokens": output_tokens,
        "$ai_total_tokens": input_tokens + output_tokens,
        "$ai_latency": round(latency_seconds, 3),
        "$ai_trace_id": trace_id,
        **(extra or {}),
    }
    if error is not None:
        properties["$ai_error"] = error
    try:
        client.capture(
            distinct_id=user_id,
            event="$ai_generation",
            properties=properties,
        )
    except Exception as exc:
        logger.warning("[PostHog] $ai_generation capture failed (non-fatal): %s", exc)


def ph_ai_trace(
    *,
    user_id: str,
    trace_id: str,
    input_tokens: int,
    output_tokens: int,
    latency_seconds: float,
    extra: dict[str, Any] | None = None,
) -> None:
    """Emit a PostHog $ai_trace event (one per conversation turn)."""
    client = _get_client()
    if client is None:
        return
    try:
        client.capture(
            distinct_id=user_id,
            event="$ai_trace",
            properties={
                "$ai_trace_id": trace_id,
                "$ai_input_tokens": input_tokens,
                "$ai_output_tokens": output_tokens,
                "$ai_total_tokens": input_tokens + output_tokens,
                "$ai_latency": round(latency_seconds, 3),
                **(extra or {}),
            },
        )
    except Exception as exc:
        logger.warning("[PostHog] $ai_trace capture failed (non-fatal): %s", exc)


def ph_capture_exception(
    exc: BaseException,
    *,
    user_id: str | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    """Capture an unhandled/handled exception to PostHog Error Tracking.

    Uses the native ``client.capture_exception`` API (posthog-python >=3.0,
    confirmed present in the pinned 7.x series — see
    ``backend/requirements.txt``: ``posthog>=3.0.0``). That method builds the
    ``$exception`` event with the frames/stack-trace shape PostHog's Error
    Tracking product expects, so we don't hand-roll the event.

    Fire-and-forget like the rest of this module: a telemetry failure must
    never mask or replace the caller's own error handling. Callers should
    invoke this as a side effect alongside (not instead of) their existing
    logging/response/retry behavior.

    Args:
        exc: The exception instance to capture.
        user_id: Optional distinct_id. Falls back to "anonymous-backend" so
            PostHog always has a distinct_id (required by the SDK); backend
            exceptions frequently occur outside any authenticated request.
        context: Optional extra properties merged onto the event (e.g.
            correlation_id, route, operation, job_id).
    """
    client = _get_client()
    if client is None:
        return
    try:
        client.capture_exception(
            exc,
            distinct_id=user_id or "anonymous-backend",
            properties=context or {},
        )
    except Exception as capture_exc:
        logger.warning(
            "[PostHog] capture_exception failed (non-fatal) exc_type=%s: %s",
            type(exc).__name__,
            capture_exc,
        )


def ph_shutdown() -> None:
    """Explicitly flush and shut down. Call on app shutdown."""
    _shutdown()
