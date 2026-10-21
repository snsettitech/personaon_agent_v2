import pytest
from fastapi import HTTPException


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def eq(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def order(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def execute(self):
        return type("Resp", (), {"data": self._rows})()


class _Supabase:
    def __init__(self, rows):
        self._rows = rows

    def table(self, _name):  # noqa: ANN001
        return _Query(self._rows)


@pytest.mark.asyncio
async def test_get_my_twins_returns_503_when_tenant_resolution_crashes(monkeypatch):
    from routers import auth as auth_router

    monkeypatch.setattr(
        auth_router,
        "resolve_tenant_id",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("db timeout")),
    )

    with pytest.raises(HTTPException) as exc:
        await auth_router.get_my_twins(user={"user_id": "u1", "email": "u@example.com"})

    assert exc.value.status_code == 503
    assert "Unable to resolve tenant" in exc.value.detail


@pytest.mark.asyncio
async def test_get_my_twins_filters_archived(monkeypatch):
    from routers import auth as auth_router

    rows = [
        {"id": "live-1", "settings": {}},
        {"id": "archived-1", "settings": {"deleted_at": "2026-02-08T00:00:00Z"}},
    ]
    monkeypatch.setattr(auth_router, "resolve_tenant_id", lambda *_args, **_kwargs: "tenant-1")
    monkeypatch.setattr(auth_router, "supabase", _Supabase(rows))

    twins = await auth_router.get_my_twins(user={"user_id": "u1", "email": "u@example.com"})

    assert [t["id"] for t in twins] == ["live-1"]
