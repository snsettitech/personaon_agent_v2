"""Tests for Microsoft Outlook OAuth flow (Task P1.1.C).

Verifies the parallel OAuth path mirrors the Google flow's behavior including
the Recall.ai V2 registration step from Task P1.1.B.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_microsoft_authorize_returns_500_when_unconfigured(monkeypatch):
    """Without MS_OAUTH_CLIENT_ID/SECRET, authorize must 500 cleanly."""
    monkeypatch.setattr("routers.calendar_booking.MS_OAUTH_CLIENT_ID", "")
    monkeypatch.setattr("routers.calendar_booking.MS_OAUTH_CLIENT_SECRET", "")
    from fastapi import HTTPException
    from routers.calendar_booking import microsoft_oauth_authorize

    with patch("routers.calendar_booking.verify_twin_ownership"):
        with pytest.raises(HTTPException) as exc_info:
            await microsoft_oauth_authorize(twin_id="t1", user={"user_id": "u1"})
    assert exc_info.value.status_code == 500
    assert "Microsoft OAuth is not configured" in exc_info.value.detail


@pytest.mark.asyncio
async def test_microsoft_authorize_builds_correct_url(monkeypatch):
    """Returned authorization_url must have client_id, redirect_uri, scope, state."""
    monkeypatch.setattr("routers.calendar_booking.MS_OAUTH_CLIENT_ID", "ms-client-id")
    monkeypatch.setattr("routers.calendar_booking.MS_OAUTH_CLIENT_SECRET", "ms-client-secret")
    monkeypatch.setattr("routers.calendar_booking.MS_OAUTH_REDIRECT_URI", "https://api.example.com/v2/calendar/microsoft/oauth/callback")

    with patch("routers.calendar_booking.verify_twin_ownership"):
        from routers.calendar_booking import microsoft_oauth_authorize
        result = await microsoft_oauth_authorize(twin_id="t1", user={"user_id": "u1"})

    assert "authorization_url" in result
    assert "state" in result
    url = result["authorization_url"]
    assert "login.microsoftonline.com" in url
    assert "client_id=ms-client-id" in url
    assert "Calendars.ReadWrite" in url
    assert "offline_access" in url


@pytest.mark.asyncio
async def test_microsoft_callback_registers_with_recall(monkeypatch):
    """Successful MS OAuth → Recall.register_calendar called with platform=microsoft_outlook."""
    state_data = {"twin_id": "twin-ms", "user_id": "u1", "provider": "microsoft"}

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {
        "access_token": "ms-access-token",
        "refresh_token": "ms-refresh-token",
    }

    mock_httpx_client = AsyncMock()
    mock_httpx_client.__aenter__ = AsyncMock(return_value=mock_httpx_client)
    mock_httpx_client.__aexit__ = AsyncMock(return_value=False)
    mock_httpx_client.post = AsyncMock(return_value=mock_token_resp)

    # Use a simple fake supabase that records updates
    update_payloads: list[dict] = []
    inserts: list[dict] = []
    select_results = [MagicMock(data=[])]  # no existing row

    class _Chain:
        def __init__(self):
            self.last_op = None
            self.last_payload = None
        def select(self, *a, **k): return self
        def insert(self, payload, *a, **k):
            inserts.append(payload)
            return self
        def update(self, payload, *a, **k):
            self.last_payload = payload
            update_payloads.append(payload)
            return self
        def delete(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self):
            if select_results:
                return select_results.pop(0)
            return MagicMock(data=[])

    mock_sb = MagicMock()
    mock_sb.table.return_value = _Chain()

    monkeypatch.setattr("routers.calendar_booking.MS_OAUTH_CLIENT_ID", "ms-client-id")
    monkeypatch.setattr("routers.calendar_booking.MS_OAUTH_CLIENT_SECRET", "ms-client-secret")

    with (
        patch("routers.calendar_booking._pop_oauth_state", return_value=state_data),
        patch("routers.calendar_booking.get_supabase_client", return_value=mock_sb),
        patch("httpx.AsyncClient", return_value=mock_httpx_client),
        patch("services.recall_calendar_v2.register_calendar",
              new_callable=AsyncMock,
              return_value={"id": "cal_ms_abc"}) as mock_register,
    ):
        from routers.calendar_booking import microsoft_oauth_callback
        result = await microsoft_oauth_callback(code="auth-code", state="state-x")

    mock_register.assert_awaited_once()
    kwargs = mock_register.await_args.kwargs
    assert kwargs["twin_id"] == "twin-ms"
    assert kwargs["platform"] == "microsoft_outlook"
    assert kwargs["oauth_refresh_token"] == "ms-refresh-token"

    # Verify the returned recall_calendar_id was written back to tool_connectors
    assert any("recall_calendar_id" in p for p in update_payloads), \
        "recall_calendar_id must be written back to tool_connectors"
    assert any(p.get("recall_calendar_id") == "cal_ms_abc" for p in update_payloads), \
        f"recall_calendar_id value must match Recall response; got: {update_payloads}"

    location = str(result.headers.get("location", ""))
    assert "outlook=connected" in location


@pytest.mark.asyncio
async def test_microsoft_callback_continues_when_recall_fails(monkeypatch):
    """If Recall fails, MS OAuth flow still completes with outlook=connected."""
    state_data = {"twin_id": "twin-ms", "user_id": "u1", "provider": "microsoft"}

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {
        "access_token": "ms-access-token",
        "refresh_token": "ms-refresh-token",
    }
    mock_httpx_client = AsyncMock()
    mock_httpx_client.__aenter__ = AsyncMock(return_value=mock_httpx_client)
    mock_httpx_client.__aexit__ = AsyncMock(return_value=False)
    mock_httpx_client.post = AsyncMock(return_value=mock_token_resp)

    class _Chain:
        def select(self, *a, **k): return self
        def insert(self, *a, **k): return self
        def update(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def execute(self): return MagicMock(data=[])
    mock_sb = MagicMock()
    mock_sb.table.return_value = _Chain()

    monkeypatch.setattr("routers.calendar_booking.MS_OAUTH_CLIENT_ID", "ms-client-id")
    monkeypatch.setattr("routers.calendar_booking.MS_OAUTH_CLIENT_SECRET", "ms-client-secret")

    with (
        patch("routers.calendar_booking._pop_oauth_state", return_value=state_data),
        patch("routers.calendar_booking.get_supabase_client", return_value=mock_sb),
        patch("httpx.AsyncClient", return_value=mock_httpx_client),
        patch("services.recall_calendar_v2.register_calendar",
              new_callable=AsyncMock,
              side_effect=Exception("Recall down")),
    ):
        from routers.calendar_booking import microsoft_oauth_callback
        result = await microsoft_oauth_callback(code="auth-code", state="state-x")

    location = str(result.headers.get("location", ""))
    assert "outlook=connected" in location
    assert "outlook=error" not in location


def test_ms_scopes_include_calendars_readwrite_and_offline_access():
    """Sanity check: scopes must include both Calendars.ReadWrite and offline_access."""
    from routers.calendar_booking import _MS_SCOPES
    assert any("Calendars.ReadWrite" in s for s in _MS_SCOPES)
    assert "offline_access" in _MS_SCOPES
