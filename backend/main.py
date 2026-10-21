"""
PersonaOn API

Routers:
  - Auth (signup, login, OAuth)
  - Chat (public + owner)
  - Profile (onboarding, publish, persona pages)
  - Handles (claim, check, resolve)
  - Deep Research (runs, compile)
  - Twins (CRUD, lifecycle)
  - Knowledge (ingestion, sources, knowledge base)
  - Import (LinkedIn, resume)
  - YouTube preflight

Deployed on GCP Cloud Run (personaon-api, us-central1).
uv run uvicorn main:asgi_app --reload --port 8006
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

import uuid as _uuid
from pathlib import Path as _Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from adk_core.model_names import chat_model_name, default_model_name, research_model_name
from modules.cors_middleware import create_cors_middleware, get_allowed_origins
from modules.posthog_analytics import ph_capture_exception, ph_shutdown
from modules.rate_limit import rate_limit_middleware
from modules.telemetry import setup_telemetry
from routers import register_routers

_static_dir = _Path(__file__).parent / "static"

load_dotenv(_Path(__file__).parent / ".env", override=False)


# ---------------------------------------------------------------------------
# Fail fast if critical env vars are missing
# ---------------------------------------------------------------------------
_REQUIRED = [
    "SUPABASE_URL",
    "SUPABASE_SERVICE_KEY",
    "GOOGLE_API_KEY",
    "JWT_SECRET",
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
]


def _check_required_env() -> None:
    missing = [k for k in _REQUIRED if not os.getenv(k)]
    if missing:
        logger.critical(
            "[STARTUP] Missing required env vars — refusing to start: %s", missing
        )
        raise SystemExit(1)


_check_required_env()

# ---------------------------------------------------------------------------
# Defaults: ADK uses Gemini, allows Cloud Run env overrides
# ---------------------------------------------------------------------------
# Unset model vars resolve to ADK_CHAT_MODEL (else the project Gemini default)
# so a retired model can't sneak back in as a hardcoded default here.
os.environ.setdefault("ADK_CHAT_MODEL", chat_model_name())
os.environ.setdefault("ADK_DEFAULT_MODEL", default_model_name())
os.environ.setdefault("ADK_RESEARCH_MODEL", research_model_name())
os.environ.setdefault("ADK_COMPILER_MODEL", chat_model_name())
os.environ.setdefault("ADK_PROVIDER_PRIORITY", "gemini,openai")
os.environ.setdefault("INFERENCE_PROVIDER", "gemini")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("[PersonaOn] API starting")
    # Initialize OpenTelemetry tracing here (not at module import) so that
    # test collection / mypy runs don't trigger OTEL setup. No-op unless
    # OTEL_EXPORTER_OTLP_ENDPOINT is set.
    setup_telemetry()
    logger.info("[PersonaOn] ADK_CHAT_MODEL     = %s", os.getenv("ADK_CHAT_MODEL"))
    logger.info("[PersonaOn] ADK_RESEARCH_MODEL = %s", os.getenv("ADK_RESEARCH_MODEL"))
    logger.info("[PersonaOn] ADK_COMPILER_MODEL = %s", os.getenv("ADK_COMPILER_MODEL"))
    logger.info("[PersonaOn] INFERENCE_PROVIDER = %s", os.getenv("INFERENCE_PROVIDER"))

    # Clear namespace cache (prevents stale creator_id resolution)
    try:
        from modules.twin_namespace import clear_creator_namespace_cache

        clear_creator_namespace_cache()
    except Exception:
        pass

    try:
        from modules.observability import get_supabase_client
        from services.notification_seed import seed_transactional_flows

        await seed_transactional_flows(get_supabase_client())
    except Exception:
        logger.exception("[PersonaOn] failed to seed transactional notification flows")

    yield
    logger.info("[PersonaOn] API shutting down")
    ph_shutdown()


app = FastAPI(
    title="PersonaOn API",
    description="PersonaOn AI Persona platform API",
    version="2.0.0",
    lifespan=lifespan,
)

APP_STARTED_AT = time.time()

# CORS — added directly to app so it works with both `main:app` and `main:application`
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["x-correlation-id"],
)


@app.exception_handler(Exception)
async def _global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch unhandled exceptions — log details, return generic message.

    Also reports the exception to PostHog Error Tracking as a side effect
    (see ph_capture_exception). This is additive only: it never changes the
    logged message or the 500 response returned to the client, and a
    PostHog failure can't affect this handler since ph_capture_exception
    swallows its own errors.
    """
    correlation_id = str(_uuid.uuid4())[:8]
    logger.error(
        "[PersonaOn] UNHANDLED %s: %s: %s", correlation_id, type(exc).__name__, exc
    )
    user = getattr(request.state, "user", None)
    user_id = str(user.get("id")) if isinstance(user, dict) and user.get("id") else None
    ph_capture_exception(
        exc,
        user_id=user_id,
        context={
            "correlation_id": correlation_id,
            "path": request.url.path,
            "method": request.method,
        },
    )
    return JSONResponse(
        status_code=500,
        content={"detail": f"Internal server error (ref: {correlation_id})"},
    )


@app.middleware("http")
async def log_requests(request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = time.time() - start
    logger.info(
        "[PersonaOn] %s %s -> %s (%.3fs)",
        request.method,
        request.url.path,
        response.status_code,
        duration,
    )
    return response

app.middleware("http")(rate_limit_middleware)

if _static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")

register_routers(app)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health", tags=["health"])
async def health():
    uptime = int(time.time() - APP_STARTED_AT)
    deps: dict = {}

    try:
        from modules.clients import get_gemini_client, get_openai_client
        from modules.observability import get_supabase_client

        checks = {
            "supabase": lambda: get_supabase_client(),
            "gemini": lambda: (
                get_gemini_client() if os.getenv("GOOGLE_API_KEY") else None
            ),
            "openai": lambda: (
                get_openai_client() if os.getenv("OPENAI_API_KEY") else None
            ),
        }
        for name, fn in checks.items():
            try:
                result = fn()
                deps[name] = "ok" if result is not None else "not_configured"
            except Exception as e:
                deps[name] = f"error: {e}"

        # pgvector check is async — await it separately
        try:
            from adk_core.services.vector_store import validate_index

            result = await validate_index()
            deps["pgvector"] = (
                "ok" if result.get("status") == "ok" else f"error: {result}"
            )
        except Exception as e:
            deps["pgvector"] = f"error: {e}"
    except Exception as e:
        deps["probe"] = f"error: {e}"

    return {
        "status": "healthy",
        "service": "personaon-api",
        "version": "2.0.0",
        "uptime_seconds": uptime,
        "dependencies": deps,
    }


@app.head("/health", tags=["health"])
async def health_head():
    return Response(status_code=200)


@app.get("/startup", tags=["health"])
async def startup_probe():
    return {"status": "starting"}


@app.get("/", tags=["health"])
async def root():
    return await health()


@app.head("/", tags=["health"])
async def root_head():
    return Response(status_code=200)


# Wrap the fully configured FastAPI app so CORS headers are present on 500s too.
asgi_app = create_cors_middleware(app)
application = asgi_app
