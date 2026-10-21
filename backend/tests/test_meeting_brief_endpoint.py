"""Contract tests for GET /v2/meetings/{twin_id}/{meeting_id}/brief (P1.2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _user(tenant_id: str = "t-x", email: str = "owner@example.com") -> dict:
    return {"user_id": "u1", "tenant_id": tenant_id, "email": email, "id": "u1"}


def _select_chain(data):
    """Build a chain that supports .eq().eq().eq().maybe_single().execute()."""
    chain = MagicMock()
    chain.execute.return_value = MagicMock(data=data)
    chain.maybe_single.return_value = chain
    chain.single.return_value = chain
    chain.eq.return_value = chain
    return chain


def _query_chain(data, *, count=None):
    """Build a Supabase query chain for endpoint tests."""
    chain = MagicMock()
    result = MagicMock(data=data)
    if count is not None:
        result.count = count
    chain.execute.return_value = result
    for method in ("eq", "gte", "in_", "like", "limit", "maybe_single", "single"):
        getattr(chain, method).return_value = chain
    return chain


@pytest.mark.asyncio
async def test_brief_returns_persisted_brief_without_regenerating():
    """If brief_json already exists, the endpoint must return it without
    invoking the brief engine."""
    from routers.meetings import get_meeting_brief

    saved_brief = {
        "meeting_id": "m1",
        "meeting_title": "Coffee",
        "meeting_start": "2026-05-20T14:30:00Z",
        "person": {"name": "Alex Chen", "email": "alex@example.com", "role": "VP", "company": "Acme", "bio": "", "signals": []},
        "your_goal": "Lock in tier 2",
        "your_context": None,
        "prior_meetings": [],
        "hooks": [{"label": "Probe", "text": "Ask about scope."}],
        "open_commitments": [],
        "generated_at": "2026-05-20T13:30:00Z",
    }

    mock_sb = MagicMock()
    chain = _select_chain({
        "id": "m1",
        "twin_id": "twin-1",
        "tenant_id": "t-x",
        "title": "Coffee",
        "brief_json": saved_brief,
    })
    mock_sb.table.return_value.select.return_value = chain

    sentinel = AsyncMock(side_effect=AssertionError("brief engine should NOT be called when brief_json exists"))

    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings.MEETING_INTELLIGENCE_ENABLED", True),
        patch("adk_core.services.persona_core.brief.generate_brief", sentinel),
    ):
        result = await get_meeting_brief(twin_id="twin-1", meeting_id="m1", request=MagicMock())

    assert result["status"] == "ok"
    assert result["data"] == saved_brief


@pytest.mark.asyncio
async def test_brief_lazy_generates_and_persists():
    """When brief_json is null, the endpoint must call the engine, return the
    generated brief, and persist it via a tenant-scoped UPDATE."""
    from routers.meetings import get_meeting_brief

    generated_brief = {
        "meeting_id": "m1",
        "meeting_title": "Coffee",
        "meeting_start": "2026-05-20T14:30:00Z",
        "person": {"name": "Alex", "email": "alex@example.com", "role": "", "company": "", "bio": "", "signals": []},
        "your_goal": None,
        "your_context": None,
        "prior_meetings": [],
        "hooks": [],
        "open_commitments": [],
        "generated_at": "2026-05-20T13:30:00Z",
    }

    captured_update_payload: dict = {}
    update_filters: list[tuple] = []

    def _update_payload_capture(payload):
        captured_update_payload.update(payload)
        update_chain = MagicMock()

        def _eq(field, value):
            update_filters.append((field, value))
            return update_chain

        update_chain.eq.side_effect = _eq
        update_chain.execute.return_value = MagicMock(data=[])
        return update_chain

    mock_sb = MagicMock()
    select_chain = _select_chain({
        "id": "m1",
        "twin_id": "twin-1",
        "tenant_id": "t-x",
        "title": "Coffee",
        "brief_json": None,
    })

    def _table(name):
        tbl = MagicMock()
        tbl.select.return_value = select_chain
        tbl.update.side_effect = _update_payload_capture
        return tbl

    mock_sb.table.side_effect = _table

    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings.MEETING_INTELLIGENCE_ENABLED", True),
        patch(
            "adk_core.services.persona_core.brief.generate_brief",
            new=AsyncMock(return_value=generated_brief),
        ),
        patch("routers.meetings._enqueue_brief_email"),
    ):
        result = await get_meeting_brief(twin_id="twin-1", meeting_id="m1", request=MagicMock())

    assert result["status"] == "ok"
    assert result["data"]["meeting_id"] == "m1"
    assert captured_update_payload["brief_json"] == generated_brief
    assert "brief_generated_at" in captured_update_payload

    # Tenant-scoped UPDATE — all three .eq() filters must have fired.
    filter_fields = [f[0] for f in update_filters]
    assert filter_fields == ["id", "twin_id", "tenant_id"], filter_fields
    assert dict(update_filters)["tenant_id"] == "t-x"


@pytest.mark.asyncio
async def test_brief_returns_404_when_meeting_missing():
    """Tenant-scoped SELECT returns no row → 404."""
    from fastapi import HTTPException
    from routers.meetings import get_meeting_brief

    mock_sb = MagicMock()
    chain = _select_chain(None)
    mock_sb.table.return_value.select.return_value = chain

    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings.MEETING_INTELLIGENCE_ENABLED", True),
    ):
        with pytest.raises(HTTPException) as exc:
            await get_meeting_brief(twin_id="twin-1", meeting_id="m1", request=MagicMock())

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_trigger_deep_brief_reuses_active_job_without_resubmitting(monkeypatch):
    from routers.meetings import trigger_deep_brief

    meeting_chain = _query_chain({"id": "m1", "brief_json": None})
    rate_chain = _query_chain([], count=0)
    active_chain = _query_chain([{"id": "job-active", "status": "pending"}])
    chains = {
        "meetings": [meeting_chain],
        "graph_outbox": [rate_chain, active_chain],
    }

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: MagicMock(
        select=MagicMock(return_value=chains[name].pop(0))
    )
    fake_outbox = MagicMock()
    fake_outbox.submit.side_effect = AssertionError("active job should be reused")

    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings._deep_brief_enabled", return_value=True),
        patch("routers.meetings.get_graph_outbox", return_value=fake_outbox),
    ):
        result = await trigger_deep_brief(
            twin_id="twin-1",
            meeting_id="m1",
            request=MagicMock(),
        )

    assert result == {"status": "queued", "job_id": "job-active"}


@pytest.mark.asyncio
async def test_trigger_deep_brief_uses_per_attempt_idempotency_key(monkeypatch):
    from routers.meetings import trigger_deep_brief

    meeting_chain = _query_chain({"id": "m1", "brief_json": None})
    rate_chain = _query_chain([], count=0)
    active_chain = _query_chain([])
    chains = {
        "meetings": [meeting_chain],
        "graph_outbox": [rate_chain, active_chain],
    }

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: MagicMock(
        select=MagicMock(return_value=chains[name].pop(0))
    )
    fake_outbox = MagicMock()
    fake_outbox.submit.return_value = "job-new"

    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings._deep_brief_enabled", return_value=True),
        patch("routers.meetings.get_graph_outbox", return_value=fake_outbox),
    ):
        result = await trigger_deep_brief(
            twin_id="twin-1",
            meeting_id="m1",
            request=MagicMock(),
        )

    idempotency_key = fake_outbox.submit.call_args.kwargs["idempotency_key"]
    assert result == {"status": "queued", "job_id": "job-new"}
    assert idempotency_key.startswith("deep_brief:twin-1:m1:")
    assert idempotency_key != "deep_brief:twin-1:m1"


@pytest.mark.asyncio
async def test_trigger_deep_brief_rate_count_filters_failed_rows(monkeypatch):
    """PR #132 post-merge audit fix: the daily cap must exclude `failed`
    rows so a tenant whose meeting hit the retry ceiling isn't locked
    out for 24h on jobs that produced zero output. Regression catches
    accidental removal of the .in_(status, ...) filter.
    """
    from routers.meetings import trigger_deep_brief

    meeting_chain = _query_chain({"id": "m1", "brief_json": None})
    rate_chain = _query_chain([], count=0)
    active_chain = _query_chain([])
    chains = {
        "meetings": [meeting_chain],
        "graph_outbox": [rate_chain, active_chain],
    }

    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda name: MagicMock(
        select=MagicMock(return_value=chains[name].pop(0))
    )
    fake_outbox = MagicMock()
    fake_outbox.submit.return_value = "job-new"

    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings._deep_brief_enabled", return_value=True),
        patch("routers.meetings.get_graph_outbox", return_value=fake_outbox),
    ):
        await trigger_deep_brief(
            twin_id="twin-1",
            meeting_id="m1",
            request=MagicMock(),
        )

    # The rate-count chain MUST have been called with .in_("status", ...)
    # that EXCLUDES "failed". Otherwise a meeting that exhausted retries
    # silently consumes a daily slot for 24h.
    in_calls = rate_chain.in_.call_args_list
    matching = [
        c for c in in_calls
        if len(c.args) >= 2
        and c.args[0] == "status"
        and "failed" not in c.args[1]
        and {"pending", "processing", "completed"}.issubset(set(c.args[1]))
    ]
    assert matching, (
        "rate-limit count query must filter status to exclude 'failed' rows; "
        f"got in_ calls: {[c.args for c in in_calls]}"
    )
