"""Tests for the global exception handler's PostHog capture side effect.

Verifies that adding ph_capture_exception() to _global_exception_handler
does not change the existing logged-error / 500-response contract, and that
the capture call receives the exception plus request context.
"""

import asyncio
import json

from starlette.requests import Request


def _make_request(path: str = "/boom", method: str = "GET", state: dict | None = None) -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [],
        "query_string": b"",
        "state": state or {},
    }
    return Request(scope)


def test_global_exception_handler_still_returns_generic_500(monkeypatch):
    import main

    monkeypatch.setattr(main, "ph_capture_exception", lambda *a, **k: None)

    request = _make_request()
    exc = ValueError("kaboom")

    response = asyncio.run(main._global_exception_handler(request, exc))

    assert response.status_code == 500
    body = json.loads(bytes(response.body))
    assert "detail" in body
    assert "Internal server error" in body["detail"]


def test_global_exception_handler_calls_ph_capture_exception_with_context(monkeypatch):
    import main

    captured = {}

    def fake_capture(exc, **kwargs):
        captured["exc"] = exc
        captured.update(kwargs)

    monkeypatch.setattr(main, "ph_capture_exception", fake_capture)

    request = _make_request(path="/v1/twins", method="POST")
    exc = RuntimeError("db down")

    asyncio.run(main._global_exception_handler(request, exc))

    assert captured["exc"] is exc
    assert captured["context"]["path"] == "/v1/twins"
    assert captured["context"]["method"] == "POST"
    assert "correlation_id" in captured["context"]


def test_global_exception_handler_extracts_user_id_when_present(monkeypatch):
    import main

    captured = {}

    def fake_capture(exc, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(main, "ph_capture_exception", fake_capture)

    request = _make_request(state={"user": {"id": "user-123"}})
    asyncio.run(main._global_exception_handler(request, ValueError("x")))

    assert captured["user_id"] == "user-123"


def test_global_exception_handler_survives_posthog_capture_raising(monkeypatch):
    """Document the boundary: the real ph_capture_exception must never raise
    (covered by test_posthog_analytics.py's fire-and-forget tests). This test
    uses a raising fake to show the handler itself doesn't locally wrap the
    call -- correctness depends on ph_capture_exception's internal
    try/except, not on _global_exception_handler."""
    import main

    def raising_capture(*a, **k):
        raise RuntimeError("posthog sdk exploded")

    monkeypatch.setattr(main, "ph_capture_exception", raising_capture)

    request = _make_request()
    try:
        asyncio.run(main._global_exception_handler(request, ValueError("x")))
        raised = False
    except RuntimeError:
        raised = True
    assert raised
