import pytest
from fastapi import Response


class _Query:
    def __init__(self, table_name, state):
        self._table_name = table_name
        self._state = state
        self._filters = {}

    def select(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def eq(self, field, value):  # noqa: ANN001
        self._filters[field] = value
        return self

    def order(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def limit(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def upsert(self, payload):  # noqa: ANN001
        self._state["upsert_calls"].append((self._table_name, payload))
        return self

    def execute(self):
        if self._table_name == "users":
            user_id = self._filters.get("id")
            if user_id is not None:
                row = self._state["users_by_id"].get(user_id)
                return type("Resp", (), {"data": [row] if row else []})()
            return type("Resp", (), {"data": []})()

        if self._table_name == "twins":
            tenant_id = self._filters.get("tenant_id")
            twins = self._state["twins_by_tenant"].get(tenant_id, [])
            return type("Resp", (), {"data": twins})()

        return type("Resp", (), {"data": []})()


class _Supabase:
    def __init__(self, state):
        self._state = state

    def table(self, name):  # noqa: ANN001
        return _Query(name, self._state)


class _Request:
    def __init__(self):
        self.headers = {}


@pytest.mark.asyncio
async def test_sync_user_reuses_recovered_tenant_instead_of_new_creation(monkeypatch):
    from routers import auth as auth_router

    state = {
        "users_by_id": {},
        "twins_by_tenant": {"tenant-existing": [{"id": "twin-1"}]},
        "upsert_calls": [],
    }
    monkeypatch.setattr(auth_router, "supabase", _Supabase(state))
    monkeypatch.setattr(auth_router, "resolve_tenant_id", lambda *_args, **_kwargs: "tenant-existing")

    user = {
        "user_id": "new-user-id",
        "email": "owner@example.com",
        "user_metadata": {"full_name": "Owner"},
    }

    result = await auth_router.sync_user(_Request(), Response(), user=user)

    assert result.user.tenant_id == "tenant-existing"
    assert result.needs_onboarding is False
    assert ("users", {
        "id": "new-user-id",
        "email": "owner@example.com",
        "tenant_id": "tenant-existing",
        "full_name": "Owner",
    }) in state["upsert_calls"]


class _TenantConflictQuery:
    def __init__(self, table_name, state):
        self._table_name = table_name
        self._state = state
        self._filters = {}
        self._insert_payload = None
        self._upsert_payload = None

    def select(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def eq(self, field, value):  # noqa: ANN001
        self._filters[field] = value
        return self

    def order(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def limit(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def insert(self, payload):  # noqa: ANN001
        self._insert_payload = payload
        return self

    def upsert(self, payload):  # noqa: ANN001
        self._upsert_payload = payload
        return self

    def execute(self):
        if self._table_name == "users":
            if self._upsert_payload is not None:
                self._state["user_upserts"].append(self._upsert_payload)
                return type("Resp", (), {"data": [self._upsert_payload]})()
            return type("Resp", (), {"data": []})()

        if self._table_name == "tenants":
            if self._filters.get("owner_id"):
                return type("Resp", (), {"data": []})()
            if self._insert_payload and self._insert_payload["name"] == "test's Workspace":
                self._state["tenant_inserts"].append(self._insert_payload)
                raise Exception('duplicate key value violates unique constraint "tenants_name_key"')
            if self._insert_payload:
                self._state["tenant_inserts"].append(self._insert_payload)
                return type("Resp", (), {"data": [{"id": "tenant-suffixed"}]})()

        return type("Resp", (), {"data": []})()


class _TenantConflictSupabase:
    def __init__(self, state):
        self._state = state

    def table(self, name):  # noqa: ANN001
        return _TenantConflictQuery(name, self._state)


def test_resolve_tenant_retries_with_suffix_on_duplicate_workspace_name(monkeypatch):
    from modules import auth_guard, observability

    state = {"tenant_inserts": [], "user_upserts": []}
    monkeypatch.setattr(observability, "supabase", _TenantConflictSupabase(state))
    monkeypatch.setattr(auth_guard.time, "sleep", lambda *_args, **_kwargs: None)

    tenant_id = auth_guard.resolve_tenant_id(
        "65110a4c-4705-43d5-8e55-115734a7cd41",
        "test@example.com",
        create_if_missing=True,
    )

    assert tenant_id == "tenant-suffixed"
    assert state["tenant_inserts"] == [
        {"name": "test's Workspace"},
        {"name": "test's Workspace (65110a4c)"},
    ]
    assert state["user_upserts"] == [
        {
            "id": "65110a4c-4705-43d5-8e55-115734a7cd41",
            "tenant_id": "tenant-suffixed",
            "email": "test@example.com",
        }
    ]
