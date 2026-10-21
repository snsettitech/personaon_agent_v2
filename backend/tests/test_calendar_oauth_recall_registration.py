"""Tests for Recall Calendar V2 registration in calendar_booking OAuth flow.

Covers Task P1.1.B: after a successful Google OAuth callback, the captured
refresh_token must be registered with Recall.ai Calendar V2. Failure of the
Recall call must NOT fail the OAuth flow (booking still works on local creds).

Likewise, disconnecting the calendar should deregister from Recall first, but
local cleanup must always run even if the Recall API is down.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ─── Test helpers ────────────────────────────────────────────────────────────


def _make_token_response(refresh_token: str = "1//04test_refresh") -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {
        "access_token": "ya29.test",
        "refresh_token": refresh_token,
    }
    resp.text = ""
    return resp


def _make_httpx_client(token_resp: MagicMock) -> MagicMock:
    """Build a context-manager-capable AsyncClient mock that returns ``token_resp``."""
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=token_resp)
    return client


class _FakeSupabaseChain:
    """Records table()/select()/eq()/execute() calls and replays canned responses.

    Coarser than a strict chain mock — every method returns ``self`` so we can
    answer regardless of how oauth_callback decides to chain its calls. The
    ``.data`` attribute returned by execute() is read from a small script.
    """

    def __init__(self, execute_results: list[Any]) -> None:
        self._execute_results = list(execute_results)
        self.calls: list[tuple[str, Any]] = []
        # Capture the .update() payloads so we can assert recall_calendar_id was stored
        self.update_payloads: list[dict] = []
        # Capture delete invocations so we can assert local cleanup ran
        self.delete_call_count = 0

    def table(self, name: str) -> "_FakeSupabaseChain":
        self.calls.append(("table", name))
        return self

    def select(self, *args: Any, **kwargs: Any) -> "_FakeSupabaseChain":
        self.calls.append(("select", (args, kwargs)))
        return self

    def insert(self, payload: Any) -> "_FakeSupabaseChain":
        self.calls.append(("insert", payload))
        return self

    def update(self, payload: dict) -> "_FakeSupabaseChain":
        self.calls.append(("update", payload))
        self.update_payloads.append(payload)
        return self

    def delete(self) -> "_FakeSupabaseChain":
        self.calls.append(("delete", None))
        self.delete_call_count += 1
        return self

    def eq(self, *args: Any, **kwargs: Any) -> "_FakeSupabaseChain":
        self.calls.append(("eq", (args, kwargs)))
        return self

    def limit(self, *args: Any, **kwargs: Any) -> "_FakeSupabaseChain":
        self.calls.append(("limit", (args, kwargs)))
        return self

    def execute(self) -> Any:
        self.calls.append(("execute", None))
        if not self._execute_results:
            return MagicMock(data=[])
        return self._execute_results.pop(0)


# ─── OAuth callback: Recall registration ─────────────────────────────────────


@pytest.mark.asyncio
async def test_oauth_callback_registers_with_recall() -> None:
    """Successful OAuth -> Recall.register_calendar called with refresh_token."""
    from routers import calendar_booking

    state_data = {"twin_id": "twin-abc", "user_id": "u1"}
    token_resp = _make_token_response(refresh_token="1//04test_refresh")
    httpx_client = _make_httpx_client(token_resp)

    # Script: 1st execute = SELECT (existing) -> empty; 2nd execute = INSERT;
    # 3rd execute = UPDATE recall_calendar_id.
    fake_sb = _FakeSupabaseChain(execute_results=[
        MagicMock(data=[]),
        MagicMock(data=None),
        MagicMock(data=None),
    ])

    with (
        patch.object(calendar_booking, "_pop_oauth_state", return_value=state_data),
        patch.object(calendar_booking, "get_supabase_client", return_value=fake_sb),
        patch("httpx.AsyncClient", return_value=httpx_client),
        patch(
            "services.recall_calendar_v2.register_calendar",
            new_callable=AsyncMock,
            return_value={"id": "cal_abc", "status": "connected"},
        ) as mock_register,
    ):
        result = await calendar_booking.oauth_callback(
            code="auth-code-test", state="state-test"
        )

    # Recall called with the captured refresh_token
    mock_register.assert_awaited_once()
    kwargs = mock_register.await_args.kwargs
    assert kwargs["twin_id"] == "twin-abc"
    assert kwargs["platform"] == "google_calendar"
    assert kwargs["oauth_refresh_token"] == "1//04test_refresh"
    # Task P1.1.D: webhook_url is passed (None when CLOUD_RUN_SERVICE_URL unset,
    # otherwise the backend's /v2/meeting-calendar/webhook endpoint).
    assert "webhook_url" in kwargs, "Task P1.1.D wires webhook_url into Recall registration"
    webhook_url = kwargs["webhook_url"]
    assert webhook_url is None or webhook_url.endswith("/v2/meeting-calendar/webhook"), (
        f"webhook_url must be None or point at the calendar webhook endpoint; got {webhook_url!r}"
    )

    # recall_calendar_id persisted back to tool_connectors
    assert any(
        payload.get("recall_calendar_id") == "cal_abc"
        for payload in fake_sb.update_payloads
    ), "recall_calendar_id must be written back to tool_connectors"

    # The writeback UPDATE must be scoped to the right row -- a regression that
    # wrote to ALL rows would still pass the previous assertion. Walk the call
    # log from the update() forward and collect the eq() args until execute().
    # _FakeSupabaseChain records eq() calls as ("eq", (args, kwargs)).
    eq_args_after_update: list[tuple] = []
    saw_update = False
    for entry in fake_sb.calls:
        name = entry[0]
        if name == "update":
            saw_update = True
            continue
        if not saw_update:
            continue
        if name == "eq":
            args, _kwargs = entry[1]
            eq_args_after_update.append(args)
        elif name == "execute":
            break

    assert ("twin_id", "twin-abc") in eq_args_after_update, (
        f"writeback UPDATE must be scoped by twin_id; got eq args: {eq_args_after_update}"
    )
    assert ("connector_type", "google_calendar") in eq_args_after_update, (
        "writeback UPDATE must be scoped by connector_type; "
        f"got eq args: {eq_args_after_update}"
    )

    # OAuth flow completed successfully
    assert "gcal=connected" in str(result.headers.get("location", ""))


@pytest.mark.asyncio
async def test_oauth_callback_continues_when_recall_fails() -> None:
    """If Recall.register_calendar raises, OAuth flow still completes successfully."""
    from routers import calendar_booking

    state_data = {"twin_id": "twin-xyz", "user_id": "u1"}
    token_resp = _make_token_response()
    httpx_client = _make_httpx_client(token_resp)

    fake_sb = _FakeSupabaseChain(execute_results=[
        MagicMock(data=[]),
        MagicMock(data=None),
    ])

    with (
        patch.object(calendar_booking, "_pop_oauth_state", return_value=state_data),
        patch.object(calendar_booking, "get_supabase_client", return_value=fake_sb),
        patch("httpx.AsyncClient", return_value=httpx_client),
        patch(
            "services.recall_calendar_v2.register_calendar",
            new_callable=AsyncMock,
            side_effect=Exception("Recall API down"),
        ),
    ):
        result = await calendar_booking.oauth_callback(
            code="auth-code-test", state="state-test"
        )

    location = str(result.headers.get("location", ""))
    assert "gcal=connected" in location, (
        f"OAuth flow must succeed even if Recall fails; got redirect: {location}"
    )
    assert "gcal=error" not in location


@pytest.mark.asyncio
async def test_oauth_callback_skips_recall_when_no_refresh_token() -> None:
    """If Google returns no refresh_token, Recall must not be called."""
    from routers import calendar_booking

    state_data = {"twin_id": "twin-no-rt", "user_id": "u1"}
    # Token response without refresh_token (Google sometimes omits it on re-auth)
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {"access_token": "ya29.test"}
    token_resp.text = ""
    httpx_client = _make_httpx_client(token_resp)

    fake_sb = _FakeSupabaseChain(execute_results=[
        MagicMock(data=[]),
        MagicMock(data=None),
    ])

    with (
        patch.object(calendar_booking, "_pop_oauth_state", return_value=state_data),
        patch.object(calendar_booking, "get_supabase_client", return_value=fake_sb),
        patch("httpx.AsyncClient", return_value=httpx_client),
        patch(
            "services.recall_calendar_v2.register_calendar",
            new_callable=AsyncMock,
        ) as mock_register,
    ):
        result = await calendar_booking.oauth_callback(
            code="auth-code-test", state="state-test"
        )

    mock_register.assert_not_awaited()
    assert "gcal=connected" in str(result.headers.get("location", ""))


# ─── Disconnect: Recall deregistration ───────────────────────────────────────


@pytest.mark.asyncio
async def test_disconnect_calls_recall_when_id_present() -> None:
    """Disconnect with a stored recall_calendar_id -> Recall.disconnect_calendar called."""
    from routers import calendar_booking

    # SELECT returns a row with recall_calendar_id; subsequent DELETE has no data
    fake_sb = _FakeSupabaseChain(execute_results=[
        MagicMock(data=[{"id": "row-1", "recall_calendar_id": "cal_abc"}]),
        MagicMock(data=None),
    ])

    with (
        patch.object(calendar_booking, "get_supabase_client", return_value=fake_sb),
        patch.object(calendar_booking, "verify_twin_ownership"),
        patch(
            "services.recall_calendar_v2.disconnect_calendar",
            new_callable=AsyncMock,
        ) as mock_disconnect,
    ):
        result = await calendar_booking.disconnect_calendar(
            twin_id="twin-abc", user={"user_id": "u1", "tenant_id": "t1"}
        )

    mock_disconnect.assert_awaited_once_with("cal_abc")
    assert fake_sb.delete_call_count == 1, "local delete must still run"
    assert result["status"] == "disconnected"


@pytest.mark.asyncio
async def test_disconnect_skips_recall_when_id_absent() -> None:
    """No recall_calendar_id -> Recall.disconnect_calendar not called, but local delete runs."""
    from routers import calendar_booking

    fake_sb = _FakeSupabaseChain(execute_results=[
        MagicMock(data=[{"id": "row-1", "recall_calendar_id": None}]),
        MagicMock(data=None),
    ])

    with (
        patch.object(calendar_booking, "get_supabase_client", return_value=fake_sb),
        patch.object(calendar_booking, "verify_twin_ownership"),
        patch(
            "services.recall_calendar_v2.disconnect_calendar",
            new_callable=AsyncMock,
        ) as mock_disconnect,
    ):
        result = await calendar_booking.disconnect_calendar(
            twin_id="twin-abc", user={"user_id": "u1", "tenant_id": "t1"}
        )

    mock_disconnect.assert_not_awaited()
    assert fake_sb.delete_call_count == 1
    assert result["status"] == "disconnected"


@pytest.mark.asyncio
async def test_google_token_exchange_failure_does_not_log_response_body() -> None:
    """H9: Google token-exchange failure must NOT log the full response body
    (Google may echo client identifiers or the OAuth code on errors).

    Mirrors the existing Microsoft callback scrubbing pattern at line ~635.
    """
    from routers import calendar_booking
    import logging

    state_data = {"twin_id": "twin-1", "user_id": "u1"}

    # Build a failed token-exchange response. resp.text contains the OAuth
    # code (a sensitive value); we must verify it never reaches the log.
    err_resp = MagicMock()
    err_resp.status_code = 400
    err_resp.headers = {"content-type": "application/json"}
    err_resp.json.return_value = {
        "error": "invalid_grant",
        "error_description": "Bad request",
    }
    err_resp.text = (
        '{"error":"invalid_grant","error_description":"4/0Aabc-OAUTH-CODE-SECRET"}'
    )

    httpx_client = _make_httpx_client(err_resp)

    captured: list[str] = []

    class _Catcher(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(self.format(record))

    handler = _Catcher()
    handler.setFormatter(logging.Formatter("%(message)s"))
    cb_logger = logging.getLogger("routers.calendar_booking")
    cb_logger.addHandler(handler)
    cb_logger.setLevel(logging.DEBUG)
    try:
        with (
            patch.object(calendar_booking, "_pop_oauth_state", return_value=state_data),
            patch("httpx.AsyncClient", return_value=httpx_client),
        ):
            await calendar_booking.oauth_callback(code="auth-code-test", state="s")
    finally:
        cb_logger.removeHandler(handler)

    full_log = "\n".join(captured)
    assert "4/0Aabc-OAUTH-CODE-SECRET" not in full_log, (
        "raw response body leaked into log; "
        "Google token-exchange error must scrub to error code only"
    )
    # The structured error code should still be present so operators can debug.
    assert "invalid_grant" in full_log, (
        "scrubbed log should still include the OAuth error code"
    )


@pytest.mark.asyncio
async def test_disconnect_soft_marks_row_when_recall_fails() -> None:
    """Recall.disconnect failure must NOT hard-delete the local row.

    Hard-deleting on Recall failure orphans the Recall calendar (we lose the
    recall_calendar_id needed to retry the delete). New behavior: soft-mark
    the row (is_active=False, last_error set), preserve recall_calendar_id,
    and return ``partial_disconnect`` so the UI and any retry path can act.
    """
    from routers import calendar_booking

    fake_sb = _FakeSupabaseChain(execute_results=[
        MagicMock(data=[{"id": "row-1", "recall_calendar_id": "cal_abc"}]),
        MagicMock(data=None),
    ])

    with (
        patch.object(calendar_booking, "get_supabase_client", return_value=fake_sb),
        patch.object(calendar_booking, "verify_twin_ownership"),
        patch(
            "services.recall_calendar_v2.disconnect_calendar",
            new_callable=AsyncMock,
            side_effect=Exception("Recall API down"),
        ),
    ):
        result = await calendar_booking.disconnect_calendar(
            twin_id="twin-abc", user={"user_id": "u1", "tenant_id": "t1"}
        )

    assert fake_sb.delete_call_count == 0, (
        "row must NOT be hard-deleted when Recall disconnect fails -- "
        "recall_calendar_id is needed for retry / next-reconnect cleanup"
    )

    # An UPDATE must have run to set is_active=False with a recall_disconnect_failed
    # last_error so the status endpoint can surface the broken state.
    soft_mark_payloads = [
        p for p in fake_sb.update_payloads
        if p.get("is_active") is False
        and isinstance(p.get("last_error"), str)
        and "recall_disconnect_failed" in p["last_error"]
    ]
    assert soft_mark_payloads, (
        f"expected an is_active=False / last_error update; got {fake_sb.update_payloads}"
    )

    assert result["status"] == "partial_disconnect"
    assert result["reason"] == "recall_unavailable"


@pytest.mark.asyncio
async def test_disconnect_hard_deletes_when_recall_succeeds() -> None:
    """Happy path: Recall confirms delete -> local row hard-deleted, no soft-mark."""
    from routers import calendar_booking

    fake_sb = _FakeSupabaseChain(execute_results=[
        MagicMock(data=[{"id": "row-1", "recall_calendar_id": "cal_abc"}]),
        MagicMock(data=None),
    ])

    with (
        patch.object(calendar_booking, "get_supabase_client", return_value=fake_sb),
        patch.object(calendar_booking, "verify_twin_ownership"),
        patch(
            "services.recall_calendar_v2.disconnect_calendar",
            new_callable=AsyncMock,
        ),
    ):
        result = await calendar_booking.disconnect_calendar(
            twin_id="twin-abc", user={"user_id": "u1", "tenant_id": "t1"}
        )

    assert fake_sb.delete_call_count == 1
    soft_mark_payloads = [
        p for p in fake_sb.update_payloads if p.get("is_active") is False
    ]
    assert not soft_mark_payloads, (
        f"soft-mark must not run when Recall succeeded; got {fake_sb.update_payloads}"
    )
    assert result["status"] == "disconnected"


@pytest.mark.asyncio
async def test_oauth_callback_marks_last_error_on_register_failure() -> None:
    """If register_calendar raises, tool_connectors gets last_error set so the
    status endpoint can surface 'needs reconnect' to the UI."""
    from routers import calendar_booking

    state_data = {"twin_id": "twin-failreg", "user_id": "u1"}
    token_resp = _make_token_response()
    httpx_client = _make_httpx_client(token_resp)

    # 1st execute = SELECT empty (no prior row), 2nd = INSERT (creds stored),
    # 3rd = UPDATE last_error from the new failure-handling branch.
    fake_sb = _FakeSupabaseChain(execute_results=[
        MagicMock(data=[]),
        MagicMock(data=None),
        MagicMock(data=None),
    ])

    with (
        patch.object(calendar_booking, "_pop_oauth_state", return_value=state_data),
        patch.object(calendar_booking, "get_supabase_client", return_value=fake_sb),
        patch("httpx.AsyncClient", return_value=httpx_client),
        patch(
            "services.recall_calendar_v2.register_calendar",
            new_callable=AsyncMock,
            side_effect=Exception("Recall 503 down"),
        ),
    ):
        result = await calendar_booking.oauth_callback(
            code="auth-code-test", state="state-test"
        )

    last_error_payloads = [
        p for p in fake_sb.update_payloads
        if isinstance(p.get("last_error"), str)
        and "recall_register_failed" in p["last_error"]
    ]
    assert last_error_payloads, (
        f"expected a last_error update mentioning recall_register_failed; "
        f"got update payloads: {fake_sb.update_payloads}"
    )

    # The OAuth flow itself still completes -- failure is degradation, not error.
    assert "gcal=connected" in str(result.headers.get("location", ""))


@pytest.mark.asyncio
async def test_oauth_callback_clears_last_error_on_register_success() -> None:
    """On successful register_calendar after a prior failure, last_error is cleared."""
    from routers import calendar_booking

    state_data = {"twin_id": "twin-recovers", "user_id": "u1"}
    token_resp = _make_token_response()
    httpx_client = _make_httpx_client(token_resp)

    # SELECT existing row carrying a prior last_error; UPDATE creds; UPDATE
    # recall_calendar_id + last_error=None.
    fake_sb = _FakeSupabaseChain(execute_results=[
        MagicMock(data=[{"id": "row-1", "recall_calendar_id": None,
                         "last_error": "recall_register_failed: old"}]),
        MagicMock(data=None),
        MagicMock(data=None),
    ])

    with (
        patch.object(calendar_booking, "_pop_oauth_state", return_value=state_data),
        patch.object(calendar_booking, "get_supabase_client", return_value=fake_sb),
        patch("httpx.AsyncClient", return_value=httpx_client),
        patch(
            "services.recall_calendar_v2.register_calendar",
            new_callable=AsyncMock,
            return_value={"id": "cal_new", "status": "connected"},
        ),
    ):
        await calendar_booking.oauth_callback(
            code="auth-code-test", state="state-test"
        )

    success_writebacks = [
        p for p in fake_sb.update_payloads
        if p.get("recall_calendar_id") == "cal_new"
    ]
    assert success_writebacks, (
        f"expected writeback of new recall_calendar_id; got {fake_sb.update_payloads}"
    )
    assert success_writebacks[0].get("last_error") is None, (
        "successful register must clear last_error so the UI stops showing 'needs reconnect'"
    )
