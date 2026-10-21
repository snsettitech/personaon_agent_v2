from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_user_has_linkedin_provider_reads_live_auth_metadata():
    from modules.profile_utils import user_has_linkedin_provider

    assert user_has_linkedin_provider({"app_metadata": {"providers": ["email", "linkedin_oidc"]}})
    assert not user_has_linkedin_provider({"app_metadata": {"providers": ["email", "google"]}})


def test_select_best_linkedin_account_prefers_real_url_over_oidc_provider():
    from modules.profile_utils import select_best_linkedin_account

    rows = [
        {
            "provider": "linkedin_oidc",
            "provider_user_id": "opaque-id",
            "profile_snapshot": {
                "display_name": "Ada Lovelace",
                "profile_url": "https://www.linkedin.com/in/opaque-id",
            },
        },
        {
            "provider": "linkedin",
            "provider_user_id": "legacy-id",
            "profile_snapshot": {
                "display_name": "Ada Lovelace",
                "profile_url": "https://www.linkedin.com/in/ada-lovelace",
            },
        },
    ]

    best = select_best_linkedin_account(rows)

    assert best is not None
    assert best["provider"] == "linkedin"
    assert best["profile_snapshot"]["profile_url"] == "https://www.linkedin.com/in/ada-lovelace"


def test_select_best_linkedin_account_uses_provider_as_tiebreaker():
    from modules.profile_utils import select_best_linkedin_account

    rows = [
        {
            "provider": "linkedin",
            "provider_user_id": "legacy-id",
            "profile_snapshot": {
                "display_name": "Ada Lovelace",
                "profile_url": "https://www.linkedin.com/in/ada-lovelace",
            },
        },
        {
            "provider": "linkedin_oidc",
            "provider_user_id": "oidc-id",
            "profile_snapshot": {
                "display_name": "Ada Lovelace",
                "profile_url": "https://www.linkedin.com/in/ada-lovelace",
            },
        },
    ]

    best = select_best_linkedin_account(rows)

    assert best is not None
    assert best["provider"] == "linkedin_oidc"


class _Query:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self._data)


class _FakeSupabase:
    def __init__(self, *, connected_accounts, twins):
        self._connected_accounts = connected_accounts
        self._twins = twins

    def table(self, name):
        if name == "connected_accounts":
            return _Query(self._connected_accounts)
        if name == "twins":
            return _Query(self._twins)
        raise AssertionError(f"Unexpected table {name}")


@pytest.mark.asyncio
async def test_identity_status_ignores_stale_snapshot_without_live_linkedin_provider():
    from routers import auth

    result = await auth.get_identity_status(
        user={
            "user_id": "user-1",
            "email": "sainsetti@gmail.com",
            "app_metadata": {"providers": ["email", "google"]},
            "user_metadata": {"name": "sainath setti"},
        }
    )

    assert result == {"verified": False, "provider": None}


@pytest.mark.asyncio
async def test_prefill_ignores_stale_snapshot_without_live_linkedin_provider(monkeypatch):
    import asyncio
    from routers import auth

    class _NoSupabase:
        def table(self, _name):
            raise AssertionError("connected_accounts should not be queried without a live LinkedIn provider")

    async def _raise_timeout(awaitable, timeout=None):  # pragma: no cover - shape matches asyncio.wait_for
        if hasattr(awaitable, "close"):
            awaitable.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(auth, "supabase", _NoSupabase())
    monkeypatch.setattr(auth, "_prefill_cache", {})
    monkeypatch.setattr(auth, "_check_prefill_rate_limit", lambda _user_id: True)
    monkeypatch.setattr(asyncio, "wait_for", _raise_timeout)

    payload = await auth.prefill_profile_from_linkedin(
        auth.PrefillProfileRequest(linkedin_url="https://www.linkedin.com/in/sainathsetti/"),
        user={
            "user_id": "user-1",
            "email": "sainsetti@gmail.com",
            "app_metadata": {"providers": ["email", "google"]},
            "user_metadata": {"full_name": "sainath setti"},
        },
    )

    assert payload["name"] == "sainath setti"
    assert payload["headline"] == ""
    assert payload["source"] == "oidc_fallback"
    assert payload["matched_profile_url"] == "https://www.linkedin.com/in/sainathsetti"


@pytest.mark.asyncio
async def test_auto_create_ignores_soft_deleted_duplicate(monkeypatch):
    from routers import auto_create

    fake_supabase = _FakeSupabase(
        connected_accounts=[],
        twins=[
            {
                "id": "deleted-twin",
                "status": "draft",
                "name": "Ada Lovelace",
                "settings": {"deleted_at": "2026-03-01T00:00:00Z"},
            },
            {
                "id": "live-twin",
                "status": "active",
                "name": "Ada Lovelace",
                "settings": {},
            },
        ],
    )

    monkeypatch.setattr(auto_create, "get_supabase_client", lambda: fake_supabase)
    monkeypatch.setattr(auto_create, "resolve_tenant_id", lambda user_id, email: "tenant-1")

    response = await auto_create.auto_create_twin(
        auto_create.AutoCreateRequest(name="Ada Lovelace"),
        user={"user_id": "user-1", "email": "ada@example.com"},
    )

    assert response.twin_id == "live-twin"
    assert response.status == "active"


class _VerifyQuery:
    def __init__(self, table: str, fake: "_VerifySupabase"):
        self._table = table
        self._fake = fake
        self._update_payload = None

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def in_(self, *_args, **_kwargs):
        return self

    def single(self):
        return self

    def update(self, payload):
        self._update_payload = payload
        return self

    def execute(self):
        if self._update_payload is not None:
            self._fake.updated_twins.append(self._update_payload)
            return SimpleNamespace(data=self._update_payload)
        if self._table == "connected_accounts":
            return SimpleNamespace(data=self._fake.connected_accounts)
        if self._table == "twins":
            return SimpleNamespace(data=self._fake.twin)
        raise AssertionError(f"Unexpected table {self._table}")


class _VerifySupabase:
    def __init__(self, *, connected_accounts, twin):
        self.connected_accounts = connected_accounts
        self.twin = twin
        self.updated_twins = []

    def table(self, name):
        return _VerifyQuery(name, self)


@pytest.mark.asyncio
async def test_verify_linkedin_updates_twin_identity_snapshot(monkeypatch):
    from routers import auto_create

    fake_supabase = _VerifySupabase(
        connected_accounts=[
            {
                "provider": "linkedin_oidc",
                "provider_user_id": "linkedin-sub",
                "profile_snapshot": {
                    "display_name": "Ada Lovelace",
                    "first_name": "Ada",
                    "last_name": "Lovelace",
                    "image_url": "https://cdn.example/ada.png",
                    "email": "ada@example.com",
                    "email_verified": True,
                    "locale": "en-US",
                },
            }
        ],
        twin={"settings": {"public_profile": {"display_name": "Ada"}}},
    )

    monkeypatch.setattr(auto_create, "get_supabase_client", lambda: fake_supabase)
    monkeypatch.setattr(auto_create, "verify_twin_ownership", lambda *_args, **_kwargs: True)

    response = await auto_create.verify_linkedin_identity(
        "twin-1",
        user={"user_id": "user-1", "tenant_id": "tenant-1"},
    )

    assert response["verified"] is True
    update = fake_supabase.updated_twins[0]["settings"]
    assert update["identity_verified"] is True
    assert update["identity_source"] == "linkedin"
    assert update["identity_snapshot"]["provider_user_id"] == "linkedin-sub"
    assert update["identity_snapshot"]["display_name"] == "Ada Lovelace"
    assert update["public_profile"]["verified_profile"] is True


@pytest.mark.asyncio
async def test_verify_linkedin_returns_clear_error_without_account(monkeypatch):
    from fastapi import HTTPException
    from routers import auto_create

    fake_supabase = _VerifySupabase(
        connected_accounts=[],
        twin={"settings": {}},
    )

    monkeypatch.setattr(auto_create, "get_supabase_client", lambda: fake_supabase)
    monkeypatch.setattr(auto_create, "verify_twin_ownership", lambda *_args, **_kwargs: True)

    with pytest.raises(HTTPException) as exc:
        await auto_create.verify_linkedin_identity(
            "twin-1",
            user={"user_id": "user-1", "tenant_id": "tenant-1"},
        )

    assert exc.value.status_code == 400
    assert "No LinkedIn account connected" in str(exc.value.detail)
