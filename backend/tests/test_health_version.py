from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.health import router


def test_version_endpoint_returns_debug_metadata(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc123")
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.setenv("BUILD_TIME", "2026-04-26T00:00:00Z")

    app = FastAPI()
    app.include_router(router)
    response = TestClient(app).get("/version")

    assert response.status_code == 200
    assert response.json() == {
        "service": "personaon-api",
        "version": "2.0.0",
        "environment": "staging",
        "git_sha": "abc123",
        "build_time": "2026-04-26T00:00:00Z",
    }
