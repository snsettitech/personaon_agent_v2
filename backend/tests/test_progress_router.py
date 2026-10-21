"""Minimal router test for GET /v2/twins/{twin_id}/progress."""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from modules.auth_guard import verify_owner
from routers.twins_progress import router


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


PROGRESS_PAYLOAD = {
    "completed": 2,
    "total": 6,
    "checkpoints": {
        "twin_created": True,
        "profile_filled": True,
        "first_meeting": False,
        "first_commitment_closed": False,
        "first_memory_approved": False,
        "public_share_enabled": False,
    },
}

FAKE_USER = {"user_id": "u-1", "tenant_id": "t-1"}


def test_get_progress_returns_payload():
    app = _make_app()
    app.dependency_overrides[verify_owner] = lambda: FAKE_USER

    with (
        patch("routers.twins_progress.verify_twin_ownership", return_value=None),
        patch(
            "routers.twins_progress.compute_progress",
            new=AsyncMock(return_value=PROGRESS_PAYLOAD),
        ),
    ):
        client = TestClient(app)
        resp = client.get("/v2/twins/twin-1/progress")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 6
    assert data["completed"] == 2
    assert data["checkpoints"]["twin_created"] is True
    assert data["checkpoints"]["profile_filled"] is True
    assert data["checkpoints"]["first_meeting"] is False
