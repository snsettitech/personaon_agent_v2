"""Health check endpoint — validates all dependencies."""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def _get_git_sha() -> str:
    for key in ("GIT_SHA", "COMMIT_SHA", "RENDER_GIT_COMMIT", "VERCEL_GIT_COMMIT_SHA"):
        value = os.getenv(key)
        if value:
            return value

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _get_environment() -> str:
    value = (os.getenv("ENVIRONMENT") or os.getenv("APP_ENV") or os.getenv("NODE_ENV") or "development").lower()
    if value in {"production", "prod"}:
        return "production"
    if value in {"staging", "stage"}:
        return "staging"
    return "development"


def _check_supabase() -> dict[str, Any]:
    try:
        from modules.observability import get_supabase_client
        sb = get_supabase_client()
        sb.table("twins").select("id").limit(1).execute()
        return {"status": "ok"}
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:200]}


async def _check_pgvector() -> dict[str, Any]:
    try:
        from adk_core.services.vector_store import validate_index
        return await validate_index()
    except Exception as exc:
        return {"status": "error", "error": str(exc)[:200]}


def _check_gemini() -> dict[str, Any]:
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        return {"status": "error", "error": "GOOGLE_API_KEY not set"}
    return {"status": "ok"}


def _check_firecrawl() -> dict[str, Any]:
    api_key = os.getenv("FIRECRAWL_API_KEY", "")
    if not api_key:
        return {"status": "error", "error": "FIRECRAWL_API_KEY not set"}
    return {"status": "ok"}


@router.get("/health")
async def health_check():
    """Validate all dependencies and return status."""
    checks = {
        "supabase": _check_supabase(),
        "pgvector": await _check_pgvector(),
        "gemini": _check_gemini(),
        "firecrawl": _check_firecrawl(),
    }

    all_ok = all(c.get("status") == "ok" for c in checks.values())

    return {
        "status": "healthy" if all_ok else "degraded",
        "checks": checks,
    }


@router.get("/version")
async def version_info():
    """Return build metadata for optional debug/admin UI."""
    return {
        "service": "personaon-api",
        "version": "2.0.0",
        "environment": _get_environment(),
        "git_sha": _get_git_sha(),
        "build_time": os.getenv("BUILD_TIME") or os.getenv("BUILD_TIMESTAMP") or datetime.now(timezone.utc).isoformat(),
    }
