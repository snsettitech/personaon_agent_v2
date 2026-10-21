from datetime import datetime

import pytest
from fastapi import HTTPException


class _DashboardWalkthroughQuery:
    def __init__(self, state):
        self._state = state
        self._filters = {}
        self._update_payload = None

    def select(self, *_args, **_kwargs):  # noqa: ANN001
        return self

    def eq(self, field, value):  # noqa: ANN001
        self._filters[field] = value
        return self

    def maybe_single(self):
        return self

    def update(self, payload):  # noqa: ANN001
        self._update_payload = payload
        return self

    def execute(self):
        user_id = self._filters.get("id")

        if self._update_payload is not None:
            if self._state.get("raise_on_update"):
                raise RuntimeError("update failed")
            self._state["updates"].append((user_id, self._update_payload))
            return type("Resp", (), {"data": self._update_payload})()

        return type("Resp", (), {"data": self._state["users"].get(user_id)})()


class _DashboardWalkthroughSupabase:
    def __init__(self, state):
        self._state = state

    def table(self, name):  # noqa: ANN001
        assert name == "users"
        return _DashboardWalkthroughQuery(self._state)


@pytest.mark.asyncio
async def test_get_dashboard_walkthrough_status_returns_completion(monkeypatch):
    from routers import auth as auth_router

    completed_at = "2026-05-05T10:15:30+00:00"
    monkeypatch.setattr(
        auth_router,
        "supabase",
        _DashboardWalkthroughSupabase(
            {
                "users": {"user-1": {"dashboard_walkthrough_completed_at": completed_at}},
                "updates": [],
            }
        ),
    )

    result = await auth_router.get_dashboard_walkthrough_status(user={"user_id": "user-1"})

    assert result.completed_at == completed_at


@pytest.mark.asyncio
async def test_get_dashboard_walkthrough_status_requires_authenticated_user():
    from routers import auth as auth_router

    with pytest.raises(HTTPException) as exc:
        await auth_router.get_dashboard_walkthrough_status(user=None)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_complete_dashboard_walkthrough_persists_timestamp(monkeypatch):
    from routers import auth as auth_router

    state = {"users": {}, "updates": []}
    monkeypatch.setattr(auth_router, "supabase", _DashboardWalkthroughSupabase(state))

    result = await auth_router.complete_dashboard_walkthrough(user={"user_id": "user-1"})

    datetime.fromisoformat(result.completed_at)
    assert state["updates"] == [
        ("user-1", {"dashboard_walkthrough_completed_at": result.completed_at})
    ]


@pytest.mark.asyncio
async def test_complete_dashboard_walkthrough_requires_authenticated_user():
    from routers import auth as auth_router

    with pytest.raises(HTTPException) as exc:
        await auth_router.complete_dashboard_walkthrough(user=None)

    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_complete_dashboard_walkthrough_returns_503_when_update_fails(monkeypatch):
    from routers import auth as auth_router

    monkeypatch.setattr(
        auth_router,
        "supabase",
        _DashboardWalkthroughSupabase({"users": {}, "updates": [], "raise_on_update": True}),
    )

    with pytest.raises(HTTPException) as exc:
        await auth_router.complete_dashboard_walkthrough(user={"user_id": "user-1"})

    assert exc.value.status_code == 503
