"""Contract tests for PATCH /v2/meetings/{twin_id}/{meeting_id} (Task P1.1.F)."""
from unittest.mock import MagicMock, patch
import pytest


def _user(tenant_id="t-x"):
    return {"user_id": "u1", "tenant_id": tenant_id}


@pytest.mark.asyncio
async def test_patch_updates_user_goal_and_context(monkeypatch):
    from routers.meetings import update_meeting, UpdateMeetingRequest

    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[{"id": "m1", "user_goal": "Discuss pricing", "user_context": "investor"}])
    )

    captured_payload: dict = {}
    original_update = mock_sb.table.return_value.update
    def capture_update(payload):
        captured_payload.update(payload)
        return original_update.return_value
    mock_sb.table.return_value.update.side_effect = capture_update

    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings.MEETING_INTELLIGENCE_ENABLED", True),
    ):
        body = UpdateMeetingRequest(user_goal="Discuss pricing", user_context="investor")
        result = await update_meeting(
            twin_id="twin-1",
            meeting_id="m1",
            body=body,
            request=MagicMock(),
        )

    assert result["status"] == "ok"
    assert captured_payload["user_goal"] == "Discuss pricing"
    assert captured_payload["user_context"] == "investor"
    assert "updated_at" in captured_payload

    # Defense-in-depth: verify the UPDATE chain filtered by tenant_id="t-x".
    # A future refactor that drops `.eq("tenant_id", ...)` would silently allow
    # cross-tenant writes; this assertion fails loudly if that happens.
    tenant_id_filtered = any(
        "tenant_id" in str(call) and "t-x" in str(call)
        for call in mock_sb.mock_calls
    )
    assert tenant_id_filtered, (
        f"UPDATE must filter by tenant_id; calls: {mock_sb.mock_calls[:15]}"
    )


@pytest.mark.asyncio
async def test_patch_trims_and_caps_user_goal():
    """user_goal must be stripped and capped to 500 chars."""
    from routers.meetings import update_meeting, UpdateMeetingRequest

    captured: dict = {}
    mock_sb = MagicMock()
    def capture_update(payload):
        captured.update(payload)
        m = MagicMock()
        m.eq.return_value.eq.return_value.eq.return_value.execute.return_value = (
            MagicMock(data=[{"id": "m1"}])
        )
        return m
    mock_sb.table.return_value.update = capture_update

    long_goal = "  " + ("x" * 600) + "  "
    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings.MEETING_INTELLIGENCE_ENABLED", True),
    ):
        body = UpdateMeetingRequest(user_goal=long_goal)
        await update_meeting(twin_id="t1", meeting_id="m1", body=body, request=MagicMock())

    assert len(captured["user_goal"]) == 500
    assert captured["user_goal"][0] == "x"  # leading whitespace stripped


@pytest.mark.asyncio
async def test_patch_404_when_meeting_not_owned():
    from fastapi import HTTPException
    from routers.meetings import update_meeting, UpdateMeetingRequest

    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = (
        MagicMock(data=[])  # tenant scope filtered out the row
    )

    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings.MEETING_INTELLIGENCE_ENABLED", True),
    ):
        body = UpdateMeetingRequest(user_goal="X")
        with pytest.raises(HTTPException) as exc_info:
            await update_meeting(twin_id="t1", meeting_id="m_other", body=body, request=MagicMock())

    assert exc_info.value.status_code == 404

    # Defense-in-depth: even on the 404 path, the UPDATE must have been
    # tenant-scoped — that's WHY it returned empty data. Verifies the tenant
    # filter is still on the chain (not just the id+twin_id filter).
    tenant_id_filtered = any(
        "tenant_id" in str(call) and "t-x" in str(call)
        for call in mock_sb.mock_calls
    )
    assert tenant_id_filtered, (
        f"UPDATE must filter by tenant_id; calls: {mock_sb.mock_calls[:15]}"
    )


@pytest.mark.asyncio
async def test_patch_empty_body_returns_existing_row():
    from routers.meetings import update_meeting, UpdateMeetingRequest

    mock_sb = MagicMock()
    # Empty body path uses SELECT.maybe_single().execute()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = (
        MagicMock(data={"id": "m1", "user_goal": "prev", "user_context": "prev ctx"})
    )

    with (
        patch("routers.meetings.supabase", mock_sb),
        patch("routers.meetings._get_current_user", return_value=_user()),
        patch("routers.meetings.MEETING_INTELLIGENCE_ENABLED", True),
    ):
        body = UpdateMeetingRequest()  # both fields None
        result = await update_meeting(twin_id="t1", meeting_id="m1", body=body, request=MagicMock())

    assert result["data"]["user_goal"] == "prev"
