"""Tests for the People Data Labs (PDL) enrichment client.

Covers:
  - enrich_by_email 200 happy path
  - enrich_by_email 404 (no match) → None
  - enrich_by_email with no PDL_API_KEY → None (no network call)
  - enrich_by_linkedin sends profile= param
"""

from __future__ import annotations

import pytest


class _FakeResp:
    def __init__(self, status_code: int = 200, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400 and self.status_code != 404:
            import httpx as _httpx
            raise _httpx.HTTPStatusError("err", request=None, response=None)  # type: ignore[arg-type]

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, captured: dict, response: _FakeResp) -> None:
        self._captured = captured
        self._response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, url: str, headers: dict, params: dict | None = None) -> _FakeResp:
        self._captured["method"] = "GET"
        self._captured["url"] = url
        self._captured["headers"] = headers
        self._captured["params"] = params or {}
        return self._response


@pytest.mark.asyncio
async def test_enrich_by_email_returns_data_on_200(monkeypatch):
    monkeypatch.setenv("PDL_API_KEY", "pdl-key")
    from services.enrichment import pdl_client

    captured: dict = {}
    pdl_payload = {
        "status": 200,
        "data": {
            "full_name": "Alex Chen",
            "job_title": "VP Sales",
            "job_company_name": "Acme",
            "summary": "5 yrs enterprise sales.",
            "headline": "VP Sales @ Acme",
            "experience": [{"company": {"name": "Acme"}, "title": {"name": "VP Sales"}}],
            "location_name": "San Francisco",
        },
    }
    monkeypatch.setattr(
        pdl_client.httpx,
        "AsyncClient",
        lambda timeout: _FakeClient(captured, _FakeResp(200, pdl_payload)),
    )

    result = await pdl_client.enrich_by_email("ALEX@example.com")

    assert result is not None
    assert result["full_name"] == "Alex Chen"
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/person/enrich")
    # API key sent in header
    assert captured["headers"]["X-Api-Key"] == "pdl-key"
    # email lowercased before sending
    assert captured["params"] == {"email": "alex@example.com"}


@pytest.mark.asyncio
async def test_enrich_by_email_returns_none_on_404(monkeypatch):
    monkeypatch.setenv("PDL_API_KEY", "pdl-key")
    from services.enrichment import pdl_client

    monkeypatch.setattr(
        pdl_client.httpx,
        "AsyncClient",
        lambda timeout: _FakeClient({}, _FakeResp(404, {})),
    )

    result = await pdl_client.enrich_by_email("unknown@example.com")
    assert result is None


@pytest.mark.asyncio
async def test_enrich_by_email_returns_none_without_api_key(monkeypatch):
    monkeypatch.delenv("PDL_API_KEY", raising=False)
    from services.enrichment import pdl_client

    # If we hit AsyncClient we want to know — the client should short-circuit.
    def _boom(*_a, **_kw):
        raise AssertionError("AsyncClient should not be invoked without an API key")

    monkeypatch.setattr(pdl_client.httpx, "AsyncClient", _boom)

    result = await pdl_client.enrich_by_email("anyone@example.com")
    assert result is None


@pytest.mark.asyncio
async def test_enrich_by_linkedin_passes_profile_param(monkeypatch):
    monkeypatch.setenv("PDL_API_KEY", "pdl-key")
    from services.enrichment import pdl_client

    captured: dict = {}
    pdl_payload = {"data": {"full_name": "Alex Chen"}}
    monkeypatch.setattr(
        pdl_client.httpx,
        "AsyncClient",
        lambda timeout: _FakeClient(captured, _FakeResp(200, pdl_payload)),
    )

    result = await pdl_client.enrich_by_linkedin("https://linkedin.com/in/alexchen")

    assert result is not None
    assert result["full_name"] == "Alex Chen"
    assert captured["params"] == {"profile": "https://linkedin.com/in/alexchen"}


@pytest.mark.asyncio
async def test_enrich_by_email_blank_input_returns_none(monkeypatch):
    monkeypatch.setenv("PDL_API_KEY", "pdl-key")
    from services.enrichment import pdl_client

    # Even with a key, blank inputs should not hit the network.
    def _boom(*_a, **_kw):
        raise AssertionError("AsyncClient should not be invoked on blank input")

    monkeypatch.setattr(pdl_client.httpx, "AsyncClient", _boom)

    assert await pdl_client.enrich_by_email("") is None
    assert await pdl_client.enrich_by_email("   ") is None
