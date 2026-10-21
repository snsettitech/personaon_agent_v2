"""
Ingestion diagnostics helpers.

Design goals:
- Persist a step timeline (`source_events`) for UI debugging.
- Persist a normalized error object (`sources.last_error`).
- Keep backwards compatibility with existing `sources.status` values.
"""

from __future__ import annotations

import json
import os
import re
import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from modules.observability import supabase


REDACT_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "api_key",
    "apikey",
    "openai_api_key",
    "supabase_service_key",
    "supabase_key",
    "jwt",
    "jwt_secret",
    "password",
    "token",
    "access_token",
    "refresh_token",
}

_DIAGNOSTICS_SCHEMA_AVAILABLE: bool | None = None
_DIAGNOSTICS_SCHEMA_ERROR: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_json(obj: Any) -> Any:
    """Best-effort JSON serialization for diagnostics payloads."""
    try:
        json.dumps(obj)
        return obj
    except Exception:
        return str(obj)


def _redact(obj: Any) -> Any:
    """Recursively redact secrets in dict-like structures."""
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            key_norm = str(k).strip().lower().replace("-", "_")
            if key_norm in REDACT_KEYS:
                out[k] = "[REDACTED]"
            else:
                out[k] = _redact(v)
        return out
    return str(obj)


def _looks_like_secret(text: str) -> bool:
    if not text:
        return False
    # Heuristic patterns to avoid persisting obvious secrets in raw payloads.
    patterns = [
        r"sk-[A-Za-z0-9]{20,}",  # OpenAI-style
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",  # JWT-ish
    ]
    return any(re.search(p, text) for p in patterns)


def sanitize_raw(raw: dict[str, Any] | None) -> dict[str, Any]:
    raw = raw or {}
    redacted = _redact(_safe_json(raw))
    # If any string values look like secrets, drop them entirely.
    if isinstance(redacted, dict):
        for k, v in list(redacted.items()):
            if isinstance(v, str) and _looks_like_secret(v):
                redacted[k] = "[REDACTED]"
    return redacted


def classify_retryable(
    http_status: int | None = None,
    code: str | None = None,
    provider_error_code: str | None = None,
) -> bool:
    if http_status is not None:
        if http_status in (408, 425, 429, 500, 502, 503, 504):
            return True
        if 400 <= http_status < 500:
            return False
    if code:
        # Conservative defaults for known terminal cases.
        terminal_codes = {
            "LINKEDIN_BLOCKED_OR_REQUIRES_AUTH",
            "YOUTUBE_AUTH_REQUIRED",
            "YOUTUBE_GEO_BLOCKED",
            "X_BLOCKED_OR_UNSUPPORTED",
        }
        if code in terminal_codes:
            return False
        if code == "YOUTUBE_TRANSCRIPT_UNAVAILABLE":
            if provider_error_code in {"auth", "gating", "unavailable"}:
                return False
            if provider_error_code in {"network", "rate_limit"}:
                return True
    return True


def diagnostics_schema_status(force_refresh: bool = False) -> tuple[bool, str | None]:
    """
    Returns whether the ingestion diagnostics schema is available.

    This is intentionally defensive: the app should continue to work even if
    migrations haven't been applied yet. When unavailable, we fall back to
    `ingestion_logs` for persisted visibility.
    """
    global _DIAGNOSTICS_SCHEMA_AVAILABLE, _DIAGNOSTICS_SCHEMA_ERROR
    if _DIAGNOSTICS_SCHEMA_AVAILABLE is not None and not force_refresh:
        return _DIAGNOSTICS_SCHEMA_AVAILABLE, _DIAGNOSTICS_SCHEMA_ERROR

    try:
        # 1) Verify columns on sources
        supabase.table("sources").select("id,last_provider,last_step,last_error,last_error_at,last_event_at").limit(1).execute()
        # 2) Verify source_events table exists
        supabase.table("source_events").select("id").limit(1).execute()
        _DIAGNOSTICS_SCHEMA_AVAILABLE = True
        _DIAGNOSTICS_SCHEMA_ERROR = None
    except Exception as e:
        _DIAGNOSTICS_SCHEMA_AVAILABLE = False
        _DIAGNOSTICS_SCHEMA_ERROR = str(e)

    return _DIAGNOSTICS_SCHEMA_AVAILABLE, _DIAGNOSTICS_SCHEMA_ERROR


def build_error(
    *,
    code: str,
    message: str,
    provider: str,
    step: str,
    http_status: int | None = None,
    provider_error_code: str | None = None,
    correlation_id: str | None = None,
    raw: dict[str, Any] | None = None,
    exc: BaseException | None = None,
) -> dict[str, Any]:
    dev_mode = os.getenv("DEV_MODE", "false").lower() == "true"
    stacktrace = None
    if dev_mode and exc is not None:
        stacktrace = traceback.format_exc()
    err = {
        "code": code,
        "message": message,
        "provider": provider,
        "step": step,
        "http_status": http_status,
        "provider_error_code": provider_error_code,
        "retryable": classify_retryable(
            http_status=http_status,
            code=code,
            provider_error_code=provider_error_code,
        ),
        "correlation_id": correlation_id,
        "raw": sanitize_raw(raw),
        "stacktrace": stacktrace,
    }
    return err


def _update_source_progress(
    *,
    source_id: str,
    twin_id: str,
    provider: str,
    step: str,
    event_status: str,
    error: dict[str, Any] | None = None,
) -> None:
    now = _utc_now().isoformat()

    update: dict[str, Any] = {}
    # Backward compatible `sources.status`
    if event_status == "error":
        update.update(
            {
                "status": "error",
                "health_status": "failed",
            }
        )
    elif step == "queued":
        update["status"] = "pending"
    elif event_status == "completed" and step in ("live",):
        update["status"] = "live"
    else:
        update["status"] = "processing"

    available, _err = diagnostics_schema_status()
    if available:
        update["last_provider"] = provider
        update["last_step"] = step
        update["last_event_at"] = now
        if event_status == "error":
            update["last_error"] = error or {}
            update["last_error_at"] = now

    try:
        supabase.table("sources").update(update).eq("id", source_id).eq("twin_id", twin_id).execute()
    except Exception as e:
        # If diagnostics columns aren't present (schema drift), retry with a minimal update.
        msg = str(e)
        if any(tok in msg for tok in ("last_provider", "last_step", "last_error", "last_error_at", "last_event_at", "source_events")):
            minimal = {"status": update.get("status")}
            if update.get("status") == "error":
                minimal["health_status"] = "failed"
            supabase.table("sources").update(minimal).eq("id", source_id).eq("twin_id", twin_id).execute()
        else:
            raise


def start_step(
    *,
    source_id: str,
    twin_id: str,
    provider: str,
    step: str,
    correlation_id: str | None = None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """
    Creates a source_events row and updates sources.last_* fields.
    Returns the event_id for completion.
    """
    _update_source_progress(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step=step,
        event_status="started",
        error=None,
    )

    available, _err = diagnostics_schema_status()
    if not available:
        try:
            from modules.observability import log_ingestion_event

            log_ingestion_event(
                source_id,
                twin_id,
                "info",
                message or f"{provider}:{step} started",
                metadata={
                    "provider": provider,
                    "step": step,
                    "status": "started",
                    "correlation_id": correlation_id,
                    "metadata": metadata or {},
                },
            )
        except Exception:
            pass
        return ""

    try:
        res = supabase.table("source_events").insert(
            {
                "source_id": source_id,
                "twin_id": twin_id,
                "provider": provider,
                "step": step,
                "status": "started",
                "message": message,
                "metadata": metadata or {},
                "error": None,
                "correlation_id": correlation_id,
                "started_at": _utc_now().isoformat(),
            }
        ).execute()
        if res.data and isinstance(res.data, list) and res.data[0].get("id"):
            return res.data[0]["id"]
    except Exception as e:
        # Table missing or not in schema cache. Degrade gracefully.
        global _DIAGNOSTICS_SCHEMA_AVAILABLE, _DIAGNOSTICS_SCHEMA_ERROR
        _DIAGNOSTICS_SCHEMA_AVAILABLE = False
        _DIAGNOSTICS_SCHEMA_ERROR = str(e)
    # Fallback: Supabase may not return inserted rows depending on config.
    return ""


def finish_step(
    *,
    event_id: str,
    source_id: str,
    twin_id: str,
    provider: str,
    step: str,
    status: str,
    correlation_id: str | None = None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    _update_source_progress(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step=step,
        event_status=("error" if status == "error" else "completed"),
        error=error,
    )

    available, _err = diagnostics_schema_status()
    if not available:
        try:
            from modules.observability import log_ingestion_event

            level = "error" if status == "error" else "info"
            log_ingestion_event(
                source_id,
                twin_id,
                level,
                message or f"{provider}:{step} {status}",
                metadata={
                    "provider": provider,
                    "step": step,
                    "status": "error" if status == "error" else "completed",
                    "correlation_id": correlation_id,
                    "metadata": metadata or {},
                    "error": error,
                },
            )
        except Exception:
            pass
        return

    try:
        if event_id:
            supabase.table("source_events").update(
                {
                    "status": "error" if status == "error" else "completed",
                    "message": message,
                    "metadata": metadata or {},
                    "error": error,
                    "correlation_id": correlation_id,
                    "ended_at": _utc_now().isoformat(),
                }
            ).eq("id", event_id).execute()
        else:
            # No event_id: insert completion row best-effort
            supabase.table("source_events").insert(
                {
                    "source_id": source_id,
                    "twin_id": twin_id,
                    "provider": provider,
                    "step": step,
                    "status": "error" if status == "error" else "completed",
                    "message": message,
                    "metadata": metadata or {},
                    "error": error,
                    "correlation_id": correlation_id,
                    "started_at": _utc_now().isoformat(),
                    "ended_at": _utc_now().isoformat(),
                }
            ).execute()
    except Exception as e:
        # Degrade gracefully if the table disappears / schema cache not refreshed.
        global _DIAGNOSTICS_SCHEMA_AVAILABLE, _DIAGNOSTICS_SCHEMA_ERROR
        _DIAGNOSTICS_SCHEMA_AVAILABLE = False
        _DIAGNOSTICS_SCHEMA_ERROR = str(e)


@contextmanager
def step_context(
    *,
    source_id: str,
    twin_id: str,
    provider: str,
    step: str,
    correlation_id: str | None = None,
    message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """
    Synchronous context manager. For async flows, wrap with try/finally manually.
    """
    event_id = start_step(
        source_id=source_id,
        twin_id=twin_id,
        provider=provider,
        step=step,
        correlation_id=correlation_id,
        message=message,
        metadata=metadata,
    )
    ctx: dict[str, Any] = {"event_id": event_id}
    try:
        yield event_id, ctx
        finish_step(
            event_id=event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step=step,
            status="completed",
            correlation_id=correlation_id,
            message=message,
            metadata=metadata,
            error=None,
        )
    except Exception as exc:
        err = build_error(
            code="INGESTION_UNHANDLED_EXCEPTION",
            message=str(exc),
            provider=provider,
            step=step,
            correlation_id=correlation_id,
            raw={"exception_type": type(exc).__name__},
            exc=exc,
        )
        finish_step(
            event_id=event_id,
            source_id=source_id,
            twin_id=twin_id,
            provider=provider,
            step=step,
            status="error",
            correlation_id=correlation_id,
            message=str(exc),
            metadata=metadata,
            error=err,
        )
        raise
