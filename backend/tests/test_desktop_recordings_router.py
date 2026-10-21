from __future__ import annotations

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from modules.auth_guard import verify_owner
from routers import desktop_recordings
from tests._supabase_mock import fluent


def _client(user: dict | None = None) -> TestClient:
    app = FastAPI()
    app.include_router(desktop_recordings.router)

    if user is not None:
        app.dependency_overrides[verify_owner] = lambda: user
    else:
        app.dependency_overrides[verify_owner] = lambda: (_ for _ in ()).throw(
            HTTPException(status_code=401, detail="Authentication required")
        )

    return TestClient(app, raise_server_exceptions=False)


def _request_body() -> dict:
    return {
        "source": "electron",
        "window": {
            "id": "window-1",
            "title": "Weekly Sync",
            "url": "https://meet.google.com/abc-defg-hij",
            "platform": "google-meet",
        },
    }


def test_sdk_upload_requires_authenticated_owner():
    response = _client().post("/v2/desktop-recordings/sdk-upload", json=_request_body())

    assert response.status_code == 401


def test_sdk_upload_returns_envelope_and_sends_recording_config(monkeypatch):
    captured: dict = {}

    async def fake_create_desktop_sdk_upload(**kwargs):
        captured.update(kwargs)
        return {
            "id": "upload-1",
            "upload_token": "token-1",
            "recording_id": "recording-1",
            "status": "pending",
        }

    mock_sb = fluent([{"id": "meeting-1"}])
    monkeypatch.setenv("RECALL_TRANSCRIPT_PROVIDER", "deepgram")
    monkeypatch.setattr(desktop_recordings, "create_desktop_sdk_upload", fake_create_desktop_sdk_upload)
    monkeypatch.setattr(desktop_recordings, "supabase", mock_sb)

    response = _client({"user_id": "user-1", "tenant_id": "tenant-1"}).post(
        "/v2/desktop-recordings/sdk-upload",
        json=_request_body(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "data": {
            "id": "upload-1",
            "upload_token": "token-1",
            "recording_id": "recording-1",
            "meeting_id": "meeting-1",
        },
    }
    inserted = mock_sb.insert.call_args.args[0]
    assert inserted["recall_sdk_upload_id"] == "upload-1"
    assert inserted["tenant_id"] == "tenant-1"
    assert inserted["source"] == "desktop_sdk"
    assert captured["metadata"]["user_id"] == "user-1"
    assert captured["metadata"]["tenant_id"] == "tenant-1"
    # Provider is chosen via env; per-provider settings live in the Recall dashboard.
    assert captured["recording_config"]["transcript"] == {"provider": {"deepgram": {}}}


def test_sdk_upload_sanitizes_recall_http_errors(monkeypatch):
    async def fake_create_desktop_sdk_upload(**_kwargs):
        request = httpx.Request("POST", "https://us-east-1.recall.ai/api/v1/sdk_upload/")
        response = httpx.Response(403, request=request, text="account_id=acct_secret hint=private")
        raise httpx.HTTPStatusError("forbidden", request=request, response=response)

    monkeypatch.setattr(desktop_recordings, "create_desktop_sdk_upload", fake_create_desktop_sdk_upload)

    response = _client({"user_id": "user-1", "tenant_id": "tenant-1"}).post(
        "/v2/desktop-recordings/sdk-upload",
        json=_request_body(),
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Failed to create Recall upload"}
    assert "acct_secret" not in response.text
