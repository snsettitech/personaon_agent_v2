"""Tests for Recall.ai Calendar V2 client."""

from __future__ import annotations

import pytest


class _FakeResp:
    """Minimal fake httpx.Response for unit tests."""

    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Fake httpx.AsyncClient that records calls into ``captured``."""

    def __init__(self, captured: dict, response: _FakeResp) -> None:
        self._captured = captured
        self._response = response

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(self, url: str, headers: dict, json: dict) -> _FakeResp:
        self._captured["method"] = "POST"
        self._captured["url"] = url
        self._captured["headers"] = headers
        self._captured["payload"] = json
        return self._response

    async def delete(self, url: str, headers: dict) -> _FakeResp:
        self._captured["method"] = "DELETE"
        self._captured["url"] = url
        self._captured["headers"] = headers
        return self._response

    async def get(
        self,
        url: str,
        headers: dict,
        params: dict | None = None,
    ) -> _FakeResp:
        self._captured["method"] = "GET"
        self._captured["url"] = url
        self._captured["headers"] = headers
        self._captured["params"] = params or {}
        return self._response


@pytest.mark.asyncio
async def test_register_calendar_passes_oauth_credentials(monkeypatch):
    """register_calendar should POST refresh_token + client creds to Recall."""
    from services import recall_calendar_v2

    captured: dict = {}
    response = _FakeResp(status_code=201, payload={"id": "cal_abc", "status": "connected"})
    monkeypatch.setattr(
        recall_calendar_v2.httpx,
        "AsyncClient",
        lambda timeout: _FakeClient(captured, response),
    )

    result = await recall_calendar_v2.register_calendar(
        twin_id="twin_xyz",
        platform="google_calendar",
        oauth_refresh_token="1//04xxxxxx",
        oauth_client_id="123-abc.apps.googleusercontent.com",
        oauth_client_secret="GOCSPX-secret",
    )

    assert result["id"] == "cal_abc"
    assert captured["method"] == "POST"
    assert "/api/v2/calendars/" in captured["url"]
    p = captured["payload"]
    assert p["platform"] == "google_calendar"
    assert p["oauth_refresh_token"] == "1//04xxxxxx"
    assert p["oauth_client_id"] == "123-abc.apps.googleusercontent.com"
    assert p["oauth_client_secret"] == "GOCSPX-secret"
    assert p["metadata"] == {"twin_id": "twin_xyz"}
    # webhook_url not provided → must not be in payload
    assert "webhook_url" not in p


@pytest.mark.asyncio
async def test_register_calendar_includes_webhook_url_when_set(monkeypatch):
    """When webhook_url is passed, it should be forwarded in the payload."""
    from services import recall_calendar_v2

    captured: dict = {}
    response = _FakeResp(status_code=201, payload={"id": "cal_def"})
    monkeypatch.setattr(
        recall_calendar_v2.httpx,
        "AsyncClient",
        lambda timeout: _FakeClient(captured, response),
    )

    await recall_calendar_v2.register_calendar(
        twin_id="twin_xyz",
        platform="microsoft_outlook",
        oauth_refresh_token="rt-1",
        oauth_client_id="cid-1",
        oauth_client_secret="cs-1",
        webhook_url="https://example.com/hook",
    )

    assert captured["payload"]["webhook_url"] == "https://example.com/hook"
    assert captured["payload"]["platform"] == "microsoft_outlook"


@pytest.mark.asyncio
async def test_disconnect_calendar_calls_delete(monkeypatch):
    """disconnect_calendar should DELETE the calendar by id."""
    from services import recall_calendar_v2

    captured: dict = {}
    response = _FakeResp(status_code=204)
    monkeypatch.setattr(
        recall_calendar_v2.httpx,
        "AsyncClient",
        lambda timeout: _FakeClient(captured, response),
    )

    result = await recall_calendar_v2.disconnect_calendar("cal_abc")

    assert result is None
    assert captured["method"] == "DELETE"
    assert captured["url"].endswith("/api/v2/calendars/cal_abc/")
    assert "Authorization" in captured["headers"]


@pytest.mark.asyncio
async def test_get_calendar_event_returns_payload(monkeypatch):
    """get_calendar_event should GET the event by id and return JSON."""
    from services import recall_calendar_v2

    captured: dict = {}
    response = _FakeResp(
        status_code=200,
        payload={"id": "evt_123", "start_time": "2026-05-20T10:00:00Z"},
    )
    monkeypatch.setattr(
        recall_calendar_v2.httpx,
        "AsyncClient",
        lambda timeout: _FakeClient(captured, response),
    )

    result = await recall_calendar_v2.get_calendar_event("evt_123")

    assert result["id"] == "evt_123"
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/api/v2/calendar-events/evt_123/")


@pytest.mark.asyncio
async def test_list_calendar_events_passes_updated_at(monkeypatch):
    """list_calendar_events should GET the events URL with updated_at__gte param."""
    from services import recall_calendar_v2

    captured: dict = {}
    response = _FakeResp(
        status_code=200,
        payload={"results": [{"id": "evt_1"}, {"id": "evt_2"}]},
    )
    monkeypatch.setattr(
        recall_calendar_v2.httpx,
        "AsyncClient",
        lambda timeout: _FakeClient(captured, response),
    )

    result = await recall_calendar_v2.list_calendar_events(
        "cal_abc",
        updated_at__gte="2026-05-19T10:00:00Z",
    )

    assert result == [{"id": "evt_1"}, {"id": "evt_2"}]
    assert captured["method"] == "GET"
    # URL is the collection endpoint; calendar_id is sent as a query param
    # alongside updated_at__gte (matches the Recall V2 contract).
    assert captured["url"].endswith("/api/v2/calendar-events/")
    assert captured["params"] == {
        "calendar_id": "cal_abc",
        "updated_at__gte": "2026-05-19T10:00:00Z",
    }
    assert "Authorization" in captured["headers"]


@pytest.mark.asyncio
async def test_list_calendar_events_omits_updated_at_when_none(monkeypatch):
    """When updated_at__gte is None, params dict should be empty (no filter)."""
    from services import recall_calendar_v2

    captured: dict = {}
    response = _FakeResp(status_code=200, payload=[{"id": "evt_only"}])
    monkeypatch.setattr(
        recall_calendar_v2.httpx,
        "AsyncClient",
        lambda timeout: _FakeClient(captured, response),
    )

    result = await recall_calendar_v2.list_calendar_events("cal_abc")

    # Raw list response is returned as-is. Params only carry the calendar_id;
    # no updated_at__gte since the caller didn't pass one.
    assert result == [{"id": "evt_only"}]
    assert captured["params"] == {"calendar_id": "cal_abc"}


@pytest.mark.asyncio
async def test_list_calendar_events_handles_plain_list(monkeypatch):
    """When Recall returns a bare list (non-paginated), it should be returned as-is."""
    from services import recall_calendar_v2

    captured: dict = {}
    response = _FakeResp(status_code=200, payload=[{"id": "evt_a"}, {"id": "evt_b"}])
    monkeypatch.setattr(
        recall_calendar_v2.httpx,
        "AsyncClient",
        lambda timeout: _FakeClient(captured, response),
    )

    result = await recall_calendar_v2.list_calendar_events("cal_xyz")

    assert result == [{"id": "evt_a"}, {"id": "evt_b"}]


class _PaginatedClient:
    """Fake httpx.AsyncClient that returns a scripted sequence of pages."""

    def __init__(self, captured: dict, pages: list[_FakeResp]) -> None:
        self._captured = captured
        self._pages = list(pages)
        self._captured.setdefault("get_calls", [])

    async def __aenter__(self) -> "_PaginatedClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def get(
        self,
        url: str,
        headers: dict,
        params: dict | None = None,
    ) -> _FakeResp:
        self._captured["get_calls"].append({"url": url, "params": params or {}})
        if not self._pages:
            return _FakeResp(status_code=200, payload={"results": [], "next": None})
        return self._pages.pop(0)


@pytest.mark.asyncio
async def test_list_calendar_events_follows_next_cursor_until_exhausted(monkeypatch):
    """H4: paginated responses must be fully drained (no silent 200-event truncation)."""
    from services import recall_calendar_v2

    page1 = _FakeResp(
        status_code=200,
        payload={
            "results": [{"id": "evt_1"}, {"id": "evt_2"}],
            "next": "https://us-east-1.recall.ai/api/v2/calendar-events/?cursor=p2",
        },
    )
    page2 = _FakeResp(
        status_code=200,
        payload={
            "results": [{"id": "evt_3"}],
            "next": "https://us-east-1.recall.ai/api/v2/calendar-events/?cursor=p3",
        },
    )
    page3 = _FakeResp(
        status_code=200,
        payload={"results": [{"id": "evt_4"}], "next": None},
    )

    captured: dict = {}
    monkeypatch.setattr(
        recall_calendar_v2.httpx,
        "AsyncClient",
        lambda timeout: _PaginatedClient(captured, [page1, page2, page3]),
    )

    result = await recall_calendar_v2.list_calendar_events("cal_paged")

    assert [r["id"] for r in result] == ["evt_1", "evt_2", "evt_3", "evt_4"], (
        f"all pages must be drained; got {result}"
    )
    # First call carries the calendar_id filter; subsequent paginated calls
    # follow the ``next`` URL (which already encodes the cursor), so we drop
    # our params on follow-ups.
    calls = captured["get_calls"]
    assert len(calls) == 3
    assert calls[0]["params"] == {"calendar_id": "cal_paged"}
    assert calls[1]["params"] == {}
    assert calls[2]["params"] == {}


@pytest.mark.asyncio
async def test_list_calendar_events_raises_on_initial_sync_cap(monkeypatch):
    """Initial full sync (``updated_at__gte=None``) that hits ``_MAX_LIST_PAGES``
    with more pages still pending must raise ``CalendarSyncTruncatedError``
    so the caller can stamp ``tool_connectors.last_error``. Silently dropping
    a power user's multi-year calendar history is unacceptable.
    """
    from services import recall_calendar_v2
    from services.recall_calendar_v2 import CalendarSyncTruncatedError

    # Each page always has another ``next`` -- without the cap we'd loop forever.
    def _always_more_page() -> _FakeResp:
        return _FakeResp(
            status_code=200,
            payload={
                "results": [{"id": "evt_x"}],
                "next": "https://us-east-1.recall.ai/api/v2/calendar-events/?cursor=more",
            },
        )

    captured: dict = {}
    pages = [_always_more_page() for _ in range(recall_calendar_v2._MAX_LIST_PAGES + 5)]
    monkeypatch.setattr(
        recall_calendar_v2.httpx,
        "AsyncClient",
        lambda timeout: _PaginatedClient(captured, pages),
    )

    with pytest.raises(CalendarSyncTruncatedError) as exc_info:
        # No updated_at__gte -> initial full sync; raise on cap.
        await recall_calendar_v2.list_calendar_events("cal_runaway")

    assert exc_info.value.recall_calendar_id == "cal_runaway"
    assert exc_info.value.pages == recall_calendar_v2._MAX_LIST_PAGES
    assert exc_info.value.events_fetched == recall_calendar_v2._MAX_LIST_PAGES
    assert len(captured["get_calls"]) == recall_calendar_v2._MAX_LIST_PAGES


@pytest.mark.asyncio
async def test_list_calendar_events_incremental_sync_warns_on_cap(monkeypatch):
    """Incremental sync (``updated_at__gte`` set) hitting the cap must NOT
    raise -- next webhook-driven sync will catch up. Warn + return partial.
    """
    from services import recall_calendar_v2

    def _always_more_page() -> _FakeResp:
        return _FakeResp(
            status_code=200,
            payload={
                "results": [{"id": "evt_x"}],
                "next": "https://us-east-1.recall.ai/api/v2/calendar-events/?cursor=more",
            },
        )

    captured: dict = {}
    pages = [_always_more_page() for _ in range(recall_calendar_v2._MAX_LIST_PAGES + 5)]
    monkeypatch.setattr(
        recall_calendar_v2.httpx,
        "AsyncClient",
        lambda timeout: _PaginatedClient(captured, pages),
    )

    # updated_at__gte set -> incremental; soft warn rather than raise.
    result = await recall_calendar_v2.list_calendar_events(
        "cal_runaway", updated_at__gte="2026-05-30T00:00:00Z"
    )

    assert len(captured["get_calls"]) == recall_calendar_v2._MAX_LIST_PAGES
    assert len(result) == recall_calendar_v2._MAX_LIST_PAGES


@pytest.mark.asyncio
async def test_list_calendar_events_initial_sync_under_cap_does_not_raise(monkeypatch):
    """Edge case: initial sync that exhausts pagination BEFORE the cap must
    not raise. The raise condition is "cap hit AND more pages remaining",
    not just "cap hit".
    """
    from services import recall_calendar_v2

    # All pages have ``next``, EXCEPT the last (natural exhaustion).
    pages: list[_FakeResp] = []
    for i in range(5):
        pages.append(
            _FakeResp(
                status_code=200,
                payload={
                    "results": [{"id": f"evt_{i}"}],
                    "next": (
                        "https://us-east-1.recall.ai/api/v2/calendar-events/?cursor=x"
                        if i < 4
                        else None
                    ),
                },
            )
        )

    captured: dict = {}
    monkeypatch.setattr(
        recall_calendar_v2.httpx,
        "AsyncClient",
        lambda timeout: _PaginatedClient(captured, pages),
    )

    result = await recall_calendar_v2.list_calendar_events("cal_short")

    assert [r["id"] for r in result] == [f"evt_{i}" for i in range(5)]
    assert len(captured["get_calls"]) == 5


@pytest.mark.asyncio
async def test_register_calendar_propagates_http_error(monkeypatch):
    """If Recall returns 4xx/5xx, register_calendar should propagate httpx.HTTPStatusError."""
    from services import recall_calendar_v2
    import httpx as _httpx

    class _ErrResp:
        status_code = 422

        def raise_for_status(self) -> None:
            raise _httpx.HTTPStatusError("422", request=None, response=None)  # type: ignore[arg-type]

        def json(self) -> dict:
            return {}

    class _Client:
        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *_a: object) -> None:
            return None

        async def post(self, url: str, headers: dict, json: dict) -> _ErrResp:
            return _ErrResp()

    monkeypatch.setattr(
        recall_calendar_v2.httpx, "AsyncClient", lambda timeout: _Client()
    )
    with pytest.raises(_httpx.HTTPStatusError):
        await recall_calendar_v2.register_calendar(
            twin_id="t",
            platform="google_calendar",
            oauth_refresh_token="r",
            oauth_client_id="c",
            oauth_client_secret="s",
        )
