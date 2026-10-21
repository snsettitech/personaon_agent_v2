"""Standardized API error responses for all routers.

Provides a consistent error envelope: {"error": CODE, "message": MSG}.
"""

from __future__ import annotations

from fastapi import HTTPException


def api_error(
    status_code: int,
    code: str,
    message: str,
) -> HTTPException:
    """Create a structured HTTPException with consistent envelope."""
    return HTTPException(
        status_code=status_code,
        detail={"error": code, "message": message},
    )


# Pre-built common errors
def not_found(resource: str = "Resource") -> HTTPException:
    return api_error(404, "NOT_FOUND", f"{resource} not found.")


def twin_not_found() -> HTTPException:
    return api_error(404, "TWIN_NOT_FOUND", "Twin not found or access is disabled.")


def conversation_not_found() -> HTTPException:
    return api_error(404, "CONVERSATION_NOT_FOUND", "Conversation not found.")


def persona_not_ready() -> HTTPException:
    return api_error(
        409,
        "PERSONA_NOT_READY",
        "Twin persona is not ready. Run research and compile first.",
    )


def invalid_twin_state(current: str, allowed: list[str]) -> HTTPException:
    return api_error(
        409,
        "INVALID_LIFECYCLE_STATE",
        f"Twin must be in {' or '.join(allowed)} state. Current: {current}.",
    )


def rate_limited() -> HTTPException:
    return api_error(
        429,
        "RATE_LIMITED",
        "Anonymous rate limit reached. Sign up for unlimited access.",
    )
