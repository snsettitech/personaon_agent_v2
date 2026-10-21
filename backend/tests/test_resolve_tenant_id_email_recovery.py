

class _Query:
    def __init__(self, table_name, state):
        self._table_name = table_name
        self._state = state
        self._filters = {}
        self._order_desc = False

    def select(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def eq(self, field, value):  # noqa: ANN001
        self._filters[field] = value
        return self

    def limit(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def order(self, _field, desc=False):  # noqa: ANN001
        self._order_desc = desc
        return self

    def insert(self, payload):  # noqa: ANN001
        self._state["insert_calls"].append((self._table_name, payload))
        return self

    def upsert(self, payload):  # noqa: ANN001
        self._state["upsert_calls"].append((self._table_name, payload))
        return self

    def execute(self):
        if self._table_name == "users":
            user_id = self._filters.get("id")
            email = self._filters.get("email")
            if user_id is not None:
                row = self._state["users_by_id"].get(user_id)
                return type("Resp", (), {"data": [row] if row else []})()
            if email is not None:
                rows = list(self._state["users_by_email"].get(email, []))
                rows.sort(
                    key=lambda r: ((r.get("last_active_at") or ""), (r.get("created_at") or "")),
                    reverse=self._order_desc,
                )
                return type("Resp", (), {"data": rows})()
            return type("Resp", (), {"data": []})()

        if self._table_name == "tenants":
            owner_id = self._filters.get("owner_id")
            rows = list(self._state["tenants_by_owner_id"].get(owner_id, []))
            rows.sort(key=lambda r: (r.get("created_at") or ""), reverse=self._order_desc)
            return type("Resp", (), {"data": rows})()

        return type("Resp", (), {"data": []})()


class _Supabase:
    def __init__(self, state):
        self._state = state

    def table(self, name):  # noqa: ANN001
        return _Query(name, self._state)


def test_resolve_tenant_id_recovers_by_email_without_new_tenant(monkeypatch):
    from modules import auth_guard
    import modules.observability as obs

    state = {
        "users_by_id": {
            "new-user-id": {"id": "new-user-id", "tenant_id": None},
        },
        "users_by_email": {
            "owner@example.com": [
                {
                    "id": "old-user-id",
                    "email": "owner@example.com",
                    "tenant_id": "tenant-existing",
                    "last_active_at": "2026-02-08T10:00:00+00:00",
                    "created_at": "2026-01-01T00:00:00+00:00",
                }
            ]
        },
        "tenants_by_owner_id": {},
        "insert_calls": [],
        "upsert_calls": [],
    }
    monkeypatch.setattr(obs, "supabase", _Supabase(state))

    tenant_id = auth_guard.resolve_tenant_id("new-user-id", "owner@example.com", create_if_missing=True)

    assert tenant_id == "tenant-existing"
    assert state["insert_calls"] == []
    assert ("users", {"id": "new-user-id", "tenant_id": "tenant-existing", "email": "owner@example.com"}) in state["upsert_calls"]


def test_resolve_tenant_id_email_recovery_prefers_most_recent_active(monkeypatch):
    from modules import auth_guard
    import modules.observability as obs

    state = {
        "users_by_id": {
            "new-user-id": {"id": "new-user-id", "tenant_id": None},
        },
        "users_by_email": {
            "owner@example.com": [
                {
                    "id": "older-user",
                    "email": "owner@example.com",
                    "tenant_id": "tenant-older",
                    "last_active_at": "2026-02-07T10:00:00+00:00",
                    "created_at": "2026-01-01T00:00:00+00:00",
                },
                {
                    "id": "newer-user",
                    "email": "owner@example.com",
                    "tenant_id": "tenant-newer",
                    "last_active_at": "2026-02-08T10:00:00+00:00",
                    "created_at": "2026-02-01T00:00:00+00:00",
                },
            ]
        },
        "tenants_by_owner_id": {},
        "insert_calls": [],
        "upsert_calls": [],
    }
    monkeypatch.setattr(obs, "supabase", _Supabase(state))

    tenant_id = auth_guard.resolve_tenant_id("new-user-id", "owner@example.com", create_if_missing=True)

    assert tenant_id == "tenant-newer"
