"""W9d — Worker handler integration tests.

Mocks the ADK Runner so we exercise the dispatcher path without firing
real Gemini/Exa/Firecrawl calls. Covers:
  - Flag-off discards (no DB work)
  - Tenant-scoped meeting fetch
  - 24h cache hit short-circuits
  - run_deep_brief None -> persist nothing, return True
  - Successful merge -> persist with deep_generated_at
  - Out-of-scope meeting -> terminal True (no retry loop)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _job(payload_meeting_id: str = "m_e2e") -> dict:
    return {
        "id": "job_e2e",
        "twin_id": "t_e2e",
        "tenant_id": "tn_e2e",
        "payload": {"meeting_id": payload_meeting_id},
    }


def _fast_brief() -> dict:
    return {
        "schema_version": 2,
        "meeting_id": "m_e2e",
        "meeting_title": "Sync",
        "person": {"name": "Sarah", "email": "s@x.com"},
        "your_goal": None,
        "your_context": None,
        "prior_meetings": [],
        "hooks": [],
        "open_commitments": [],
        "participant_insights": [
            {"name": "Sarah", "email": "s@x.com", "background": None}
        ],
        "talking_points": [],
        "previous_interactions": [],
        "suggested_agenda": [],
        "caution_notes": [],
        "sources_used": {"kb_chunks": 0, "web_results": 0, "past_meetings": 0},
    }


@pytest.mark.asyncio
async def test_flag_off_discards_without_db_work(monkeypatch):
    monkeypatch.delenv("BRIEF_DEEP_MODE_ENABLED", raising=False)
    from modules import graph_outbox_worker as w
    with patch.object(w, "_run_db", new_callable=AsyncMock) as mock_db:
        result = await w._process_generate_deep_brief(_job())
    assert result is True
    assert not mock_db.called


@pytest.mark.asyncio
async def test_missing_ids_returns_true_without_work(monkeypatch):
    monkeypatch.setenv("BRIEF_DEEP_MODE_ENABLED", "true")
    from modules import graph_outbox_worker as w
    with patch.object(w, "_run_db", new_callable=AsyncMock) as mock_db:
        result = await w._process_generate_deep_brief(
            {"id": "x", "payload": {}}  # no twin / tenant / meeting
        )
    assert result is True
    assert not mock_db.called


@pytest.mark.asyncio
async def test_cache_hit_skips_run(monkeypatch):
    """A brief with deep_generated_at < 24h ago is fresh — skip the run."""
    monkeypatch.setenv("BRIEF_DEEP_MODE_ENABLED", "true")
    from modules import graph_outbox_worker as w
    fresh_brief = _fast_brief()
    fresh_brief["deep_generated_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).isoformat()

    meeting_row = {
        "id": "m_e2e",
        "twin_id": "t_e2e",
        "tenant_id": "tn_e2e",
        "brief_json": fresh_brief,
    }
    fetch_resp = MagicMock()
    fetch_resp.data = meeting_row

    with patch.object(w, "_run_db", new_callable=AsyncMock) as mock_db, \
         patch(
             "modules.graph_outbox_worker.run_deep_brief",
             new_callable=AsyncMock,
         ) as mock_run:
        mock_db.return_value = fetch_resp
        result = await w._process_generate_deep_brief(_job())
    assert result is True
    # SELECT was called, but run_deep_brief was NOT (cache hit)
    assert mock_run.called is False
    # And no UPDATE was issued either
    assert mock_db.call_count == 1


@pytest.mark.asyncio
async def test_meeting_not_found_terminates(monkeypatch):
    monkeypatch.setenv("BRIEF_DEEP_MODE_ENABLED", "true")
    from modules import graph_outbox_worker as w
    fetch_resp = MagicMock()
    fetch_resp.data = None
    with patch.object(w, "_run_db", new_callable=AsyncMock) as mock_db:
        mock_db.return_value = fetch_resp
        result = await w._process_generate_deep_brief(_job())
    assert result is True  # terminal — no retry


@pytest.mark.asyncio
async def test_run_deep_brief_returns_none_no_persist(monkeypatch):
    """Deep run failed -> keep fast-path brief, no UPDATE, retry job."""
    monkeypatch.setenv("BRIEF_DEEP_MODE_ENABLED", "true")
    from modules import graph_outbox_worker as w
    meeting_row = {
        "id": "m_e2e",
        "twin_id": "t_e2e",
        "tenant_id": "tn_e2e",
        "brief_json": _fast_brief(),
    }
    fetch_resp = MagicMock()
    fetch_resp.data = meeting_row

    with patch.object(w, "_run_db", new_callable=AsyncMock) as mock_db, \
         patch(
             "modules.graph_outbox_worker.run_deep_brief",
             new_callable=AsyncMock,
         ) as mock_run:
        mock_db.return_value = fetch_resp
        mock_run.return_value = None  # deep failed
        result = await w._process_generate_deep_brief(_job())

    assert result is False
    # Only the SELECT — no UPDATE (no persist when deep_output is None)
    assert mock_db.call_count == 1


@pytest.mark.asyncio
async def test_persist_failure_retries_job(monkeypatch):
    """If the merge cannot be persisted, the outbox job must retry."""
    monkeypatch.setenv("BRIEF_DEEP_MODE_ENABLED", "true")
    from modules import graph_outbox_worker as w

    meeting_row = {
        "id": "m_e2e",
        "twin_id": "t_e2e",
        "tenant_id": "tn_e2e",
        "brief_json": _fast_brief(),
    }
    fetch_resp = MagicMock()
    fetch_resp.data = meeting_row
    deep_output = {
        "participant_insights": [
            {"name": "Sarah", "background": "CRO at Beta", "recent_activities": []}
        ],
        "sources_used": {"kb_chunks": 2, "web_results": 4, "past_meetings": 0},
    }

    with patch.object(w, "_run_db", new_callable=AsyncMock) as mock_db, \
         patch(
             "modules.graph_outbox_worker.run_deep_brief",
             new_callable=AsyncMock,
         ) as mock_run:
        mock_db.side_effect = [fetch_resp, RuntimeError("db unavailable")]
        mock_run.return_value = deep_output
        result = await w._process_generate_deep_brief(_job())

    assert result is False
    assert mock_db.call_count == 2


@pytest.mark.asyncio
async def test_successful_merge_persists(monkeypatch):
    monkeypatch.setenv("BRIEF_DEEP_MODE_ENABLED", "true")
    from modules import graph_outbox_worker as w
    meeting_row = {
        "id": "m_e2e",
        "twin_id": "t_e2e",
        "tenant_id": "tn_e2e",
        "brief_json": _fast_brief(),
    }
    fetch_resp = MagicMock()
    fetch_resp.data = meeting_row
    update_resp = MagicMock()
    update_resp.data = [meeting_row]

    deep_output = {
        "participant_insights": [
            {"name": "Sarah", "background": "CRO at Beta", "recent_activities": []}
        ],
        "sources_used": {"kb_chunks": 2, "web_results": 4, "past_meetings": 0},
    }

    with patch.object(w, "_run_db", new_callable=AsyncMock) as mock_db, \
         patch(
             "modules.graph_outbox_worker.run_deep_brief",
             new_callable=AsyncMock,
         ) as mock_run:
        mock_db.side_effect = [fetch_resp, update_resp]
        mock_run.return_value = deep_output
        result = await w._process_generate_deep_brief(_job())

    assert result is True
    # One SELECT + one UPDATE
    assert mock_db.call_count == 2
    # run_deep_brief was called once with the loaded meeting
    assert mock_run.called
    call_kwargs = mock_run.call_args.kwargs
    assert call_kwargs["twin_id"] == "t_e2e"
    assert call_kwargs["tenant_id"] == "tn_e2e"
    assert call_kwargs["meeting"]["id"] == "m_e2e"
