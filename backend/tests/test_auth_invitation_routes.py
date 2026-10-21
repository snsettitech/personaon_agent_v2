import os
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient

# Add backend to path
sys.path.insert(0, os.path.join(os.getcwd(), "backend"))

from main import app
from routers import auth as auth_router

client = TestClient(app)


def test_validate_invitation_endpoint_returns_pending_metadata(monkeypatch):
    monkeypatch.setattr(
        auth_router,
        "_require_pending_invitation_or_raise",
        lambda token: {
            "id": "inv-1",
            "tenant_id": "tenant-1",
            "email": "invitee@example.com",
            "role": "viewer",
            "invited_by": "owner-1",
            "status": "pending",
            "expires_at": "2099-01-01T00:00:00Z",
        },
    )

    response = client.get("/auth/invitation/test-token")
    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "invitee@example.com"
    assert payload["role"] == "viewer"
    assert payload["status"] == "pending"


def test_accept_invitation_endpoint_returns_real_session_payload(monkeypatch):
    monkeypatch.setattr(
        auth_router,
        "_require_pending_invitation_or_raise",
        lambda token: {
            "id": "inv-1",
            "tenant_id": "tenant-1",
            "email": "invitee@example.com",
            "role": "viewer",
            "status": "pending",
        },
    )

    mock_admin = SimpleNamespace(
        create_user=lambda attrs: SimpleNamespace(
            user=SimpleNamespace(id="auth-user-123", email=attrs["email"])
        )
    )
    monkeypatch.setattr(auth_router, "supabase", SimpleNamespace(auth=SimpleNamespace(admin=mock_admin)))

    mock_sign_in_response = SimpleNamespace(
        session=SimpleNamespace(
            access_token="access-token-123",
            refresh_token="refresh-token-123",
            expires_in=3600,
            expires_at=9999999999,
            token_type="bearer",
        ),
        user=SimpleNamespace(id="auth-user-123", email="invitee@example.com"),
    )
    monkeypatch.setattr(
        auth_router,
        "_get_anon_supabase_client",
        lambda: SimpleNamespace(
            auth=SimpleNamespace(sign_in_with_password=lambda credentials: mock_sign_in_response)
        ),
    )

    monkeypatch.setattr(
        auth_router,
        "accept_invitation",
        lambda token, user_data, auth_user_id=None: {
            "id": auth_user_id or "fallback-id",
            "tenant_id": "tenant-1",
            "email": "invitee@example.com",
            "role": "viewer",
            "created_at": "2026-01-01T00:00:00Z",
        },
    )

    response = client.post(
        "/auth/accept-invitation",
        json={"token": "test-token", "password": "password123", "name": "Invitee"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["token"] == "access-token-123"
    assert payload["session"]["access_token"] == "access-token-123"
    assert payload["session"]["refresh_token"] == "refresh-token-123"
    assert payload["user"]["id"] == "auth-user-123"
