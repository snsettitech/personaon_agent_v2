from fastapi import HTTPException

from modules import auth_guard


def test_verify_owner_enriches_tenant_id(monkeypatch):
    monkeypatch.setattr(
        auth_guard,
        "authenticate_request",
        lambda token: {"user_id": "user-1", "email": "u@example.com"},
    )
    monkeypatch.setattr(
        auth_guard,
        "resolve_tenant_id",
        lambda user_id, email, create_if_missing=False: "tenant-1",
    )

    user = auth_guard.verify_owner(authorization="Bearer token-1")
    assert user["user_id"] == "user-1"
    assert user["tenant_id"] == "tenant-1"


def test_verify_owner_raises_403_when_tenant_missing(monkeypatch):
    monkeypatch.setattr(
        auth_guard,
        "authenticate_request",
        lambda token: {"user_id": "user-2", "email": "u2@example.com"},
    )

    def _raise_not_found(user_id, email, create_if_missing=False):
        raise HTTPException(status_code=404, detail="Tenant not found")

    monkeypatch.setattr(auth_guard, "resolve_tenant_id", _raise_not_found)

    try:
        auth_guard.verify_owner(authorization="Bearer token-2")
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 403
        assert "tenant association" in str(exc.detail).lower()


def test_get_current_user_best_effort_tenant_enrichment(monkeypatch):
    monkeypatch.setattr(
        auth_guard,
        "authenticate_request",
        lambda token: {"user_id": "user-3", "email": "u3@example.com"},
    )
    monkeypatch.setattr(
        auth_guard,
        "resolve_tenant_id",
        lambda user_id, email, create_if_missing=False: "tenant-3",
    )

    user = auth_guard.get_current_user(authorization="Bearer token-3")
    assert user["user_id"] == "user-3"
    assert user["tenant_id"] == "tenant-3"

