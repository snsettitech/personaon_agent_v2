import pytest
from fastapi import HTTPException


class _Query:
    def __init__(self, state, table_name):
        self._state = state
        self._table_name = table_name

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def insert(self, payload):  # noqa: ANN001
        self._state["insert_calls"].append((self._table_name, payload))
        return self

    def upsert(self, payload):  # noqa: ANN001
        self._state["upsert_calls"].append((self._table_name, payload))
        return self

    def execute(self):
        if self._state.get("raise_lookup"):
            raise Exception("lookup failed")
        if self._table_name == "users":
            return type("Resp", (), {"data": self._state.get("users_data", [])})()
        if self._table_name == "tenants":
            return type("Resp", (), {"data": self._state.get("tenants_data", [])})()
        return type("Resp", (), {"data": []})()


class _Supabase:
    def __init__(self, state):
        self._state = state

    def table(self, name):  # noqa: ANN001
        return _Query(self._state, name)


def test_resolve_tenant_id_read_only_mode_does_not_create(monkeypatch):
    from modules import auth_guard
    import modules.observability as obs

    state = {
        "users_data": [{"id": "user-1", "tenant_id": None}],
        "tenants_data": [],
        "insert_calls": [],
        "upsert_calls": [],
    }
    monkeypatch.setattr(obs, "supabase", _Supabase(state))

    with pytest.raises(HTTPException) as exc:
        auth_guard.resolve_tenant_id("user-1", "u@example.com", create_if_missing=False)

    assert exc.value.status_code == 404
    assert state["insert_calls"] == []
    assert state["upsert_calls"] == []


def test_resolve_tenant_id_lookup_failure_is_non_mutating(monkeypatch):
    from modules import auth_guard
    import modules.observability as obs

    state = {
        "raise_lookup": True,
        "insert_calls": [],
        "upsert_calls": [],
    }
    monkeypatch.setattr(obs, "supabase", _Supabase(state))

    with pytest.raises(HTTPException) as exc:
        auth_guard.resolve_tenant_id("user-1", "u@example.com", create_if_missing=True)

    assert exc.value.status_code == 503
    assert state["insert_calls"] == []
    assert state["upsert_calls"] == []
