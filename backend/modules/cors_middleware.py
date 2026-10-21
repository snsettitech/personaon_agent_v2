"""CORS middleware configuration for PersonaOn API."""

from __future__ import annotations

import logging
import os

from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)


def get_allowed_origins() -> list[str]:
    """Parse ALLOWED_ORIGINS or fall back to known production origins."""
    origins_raw = os.getenv("ALLOWED_ORIGINS")

    if origins_raw:
        origins = [o.strip() for o in origins_raw.split(",") if o.strip()]
    else:
        origins = [
            "https://personaon-web-czlsihxvra-uc.a.run.app",
            "https://personaon-web-837700257032.us-central1.run.app",
            "https://personaon-api-czlsihxvra-uc.a.run.app",
            "https://personaon-api-837700257032.us-central1.run.app",
            "https://personaon.com",
            "https://www.personaon.com",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]

    frontend_url = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
    if frontend_url and frontend_url not in origins:
        origins.append(frontend_url)

    return origins


def _get_origin_regex() -> str:
    """Build regex matching Cloud Run and Vercel preview deployment origins."""
    patterns = [
        r"https://personaon-(web|api|worker)-[a-z0-9-]+-[a-z0-9]+\.(a\.run\.app|us-central1\.run\.app)",
        r"https://personaon[a-z0-9-]*\.vercel\.app",
    ]
    return "|".join(f"({p})" for p in patterns)


def create_cors_middleware(app: ASGIApp) -> CORSMiddleware:
    """Wrap the entire ASGI app so CORS headers are present on unhandled 500s."""
    origins = get_allowed_origins()
    origin_regex = _get_origin_regex()

    logger.info("CORS allowed origins: %s", origins)

    return CORSMiddleware(
        app=app,
        allow_origins=origins,
        allow_origin_regex=origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-correlation-id"],
    )
