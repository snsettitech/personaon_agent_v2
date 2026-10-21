"""Tests for the worker-smooth fixes (Layers 1-4).

Layer 1 — per-job timeout (asyncio.wait_for + per-op override map)
Layer 2 — zombie sweep (reset stale `processing` rows)
Layer 3 — smart retry classification (permanent vs transient errors)
Layer 4 — admin retry endpoint exercised by test_admin_graph_outbox.py
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Layer 1 -- per-job timeout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dispatch_timeout_marks_job_failed_for_retry() -> None:
    """A handler that exceeds the per-op timeout is cancelled and the job
    is marked failed (transient -> retry path)."""
    from modules.graph_outbox_worker import process_next_graph_outbox_job

    with patch.dict(
        "modules.graph_outbox_worker._PER_OP_TIMEOUT_OVERRIDES",
        {"slow_op": 1},
        clear=False,
    ):
        async def _slow_dispatch(_job):
            await asyncio.sleep(5)
            return True

        async def _list(limit: int = 1):
            return ["job-1"]

        async def _claim(job_id: str, worker_id: str):
            return {
                "id": "job-1",
                "operation": "slow_op",
                "attempt_count": 0,
                "max_attempts": 5,
                "scope_id": None,
            }

        mark_failed = AsyncMock()
        mark_completed = AsyncMock()

        with patch("modules.graph_outbox_worker._list_pending_job_ids", _list), \
             patch("modules.graph_outbox_worker._claim_job", _claim), \
             patch("modules.graph_outbox_worker._dispatch", _slow_dispatch), \
             patch("modules.graph_outbox_worker._mark_job_failed", mark_failed), \
             patch("modules.graph_outbox_worker._mark_job_completed", mark_completed):
            ran = await process_next_graph_outbox_job(worker_id="w-test")

    assert ran is True
    mark_failed.assert_awaited_once()
    args, kwargs = mark_failed.await_args
    assert "timeout after 1s" in args[1]
    assert kwargs.get("permanent") is False
    mark_completed.assert_not_awaited()


def test_timeout_for_operation_default_and_override() -> None:
    from modules.graph_outbox_worker import (
        _JOB_TIMEOUT_DEFAULT_SECONDS,
        _PER_OP_TIMEOUT_OVERRIDES,
        _timeout_for_operation,
    )

    assert _timeout_for_operation("unknown_op") == _JOB_TIMEOUT_DEFAULT_SECONDS
    assert _timeout_for_operation("generate_deep_brief") == _PER_OP_TIMEOUT_OVERRIDES["generate_deep_brief"]


# ---------------------------------------------------------------------------
# Layer 2 -- zombie sweep
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_reset_zombie_jobs_resets_stale_processing_to_pending() -> None:
    from modules.graph_outbox_worker import reset_zombie_jobs

    captured_updates: list[dict[str, Any]] = []

    select_resp = SimpleNamespace(
        data=[
            {
                "id": "zombie-1",
                "attempt_count": 1,
                "max_attempts": 5,
                "operation": "generate_meeting_summary",
                "error_message": None,
            }
        ]
    )
    update_resp = SimpleNamespace(data=[{"id": "zombie-1"}])

    select_chain = MagicMock()
    select_chain.select.return_value = select_chain
    select_chain.eq.return_value = select_chain
    select_chain.lt.return_value = select_chain
    select_chain.limit.return_value = select_chain
    select_chain.execute.return_value = select_resp

    update_chain = MagicMock()
    update_chain.update.side_effect = lambda payload: (
        captured_updates.append(payload) or update_chain
    )
    update_chain.eq.return_value = update_chain
    update_chain.execute.return_value = update_resp

    table_calls = [select_chain, update_chain]
    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda _name: table_calls.pop(0) if table_calls else update_chain

    with patch("modules.graph_outbox_worker.supabase", mock_sb):
        reset = await reset_zombie_jobs(stale_after_seconds=1800)

    assert reset == 1
    assert len(captured_updates) == 1
    payload = captured_updates[0]
    assert payload["status"] == "pending"
    assert payload["attempt_count"] == 2


@pytest.mark.asyncio
async def test_reset_zombie_jobs_marks_failed_when_max_attempts_reached() -> None:
    from modules.graph_outbox_worker import reset_zombie_jobs

    captured_updates: list[dict[str, Any]] = []

    select_chain = MagicMock()
    select_chain.select.return_value = select_chain
    select_chain.eq.return_value = select_chain
    select_chain.lt.return_value = select_chain
    select_chain.limit.return_value = select_chain
    select_chain.execute.return_value = SimpleNamespace(
        data=[
            {
                "id": "zombie-2",
                "attempt_count": 5,
                "max_attempts": 5,
                "operation": "enhance_notes",
                "error_message": "prior failure",
            }
        ]
    )

    update_chain = MagicMock()
    update_chain.update.side_effect = lambda payload: (
        captured_updates.append(payload) or update_chain
    )
    update_chain.eq.return_value = update_chain
    update_chain.execute.return_value = SimpleNamespace(data=[{"id": "zombie-2"}])

    table_calls = [select_chain, update_chain]
    mock_sb = MagicMock()
    mock_sb.table.side_effect = lambda _name: table_calls.pop(0) if table_calls else update_chain

    with patch("modules.graph_outbox_worker.supabase", mock_sb):
        reset = await reset_zombie_jobs()

    assert reset == 1
    payload = captured_updates[0]
    assert payload["status"] == "failed"
    assert "zombie_sweep" in payload["error_message"]


@pytest.mark.asyncio
async def test_reset_zombie_jobs_returns_zero_when_no_zombies() -> None:
    from modules.graph_outbox_worker import reset_zombie_jobs

    select_chain = MagicMock()
    select_chain.select.return_value = select_chain
    select_chain.eq.return_value = select_chain
    select_chain.lt.return_value = select_chain
    select_chain.limit.return_value = select_chain
    select_chain.execute.return_value = SimpleNamespace(data=[])

    mock_sb = MagicMock()
    mock_sb.table.return_value = select_chain

    with patch("modules.graph_outbox_worker.supabase", mock_sb):
        reset = await reset_zombie_jobs()

    assert reset == 0


# ---------------------------------------------------------------------------
# Global recap-timeout sweep (bot recaps never arm the per-meeting watchdog)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sweep_stuck_recaps_runs_global_scan() -> None:
    """sweep_stuck_recaps must invoke the recap-timeout watchdog as a GLOBAL scan
    (payload has NO meeting_id) so stuck bot/Recall recaps — which never arm the
    per-meeting recap_timeout_check — get flipped to failed. Guards the wiring the
    worker poll loop relies on."""
    from modules import graph_outbox_worker as gow

    captured: dict[str, Any] = {}

    async def _fake_check(job: dict[str, Any]) -> bool:
        captured["job"] = job
        return True

    with patch.object(gow, "_process_recap_timeout_check", _fake_check):
        result = await gow.sweep_stuck_recaps()

    assert result is True
    job = captured["job"]
    # Global scan => no target meeting_id (scans all tenants).
    assert (job.get("payload") or {}).get("meeting_id") is None


# ---------------------------------------------------------------------------
# Layer 3 -- smart retry classification
# ---------------------------------------------------------------------------

def test_is_permanent_error_value_error_is_permanent() -> None:
    from modules.graph_outbox_worker import _is_permanent_error
    assert _is_permanent_error(ValueError("bad payload")) is True


def test_is_permanent_error_key_error_is_permanent() -> None:
    from modules.graph_outbox_worker import _is_permanent_error
    assert _is_permanent_error(KeyError("twin_id")) is True


def test_is_permanent_error_timeout_is_transient() -> None:
    from modules.graph_outbox_worker import _is_permanent_error
    assert _is_permanent_error(asyncio.TimeoutError()) is False


def test_is_permanent_error_runtime_error_is_transient() -> None:
    from modules.graph_outbox_worker import _is_permanent_error
    assert _is_permanent_error(RuntimeError("supabase 503")) is False


def test_is_permanent_error_substring_marker() -> None:
    from modules.graph_outbox_worker import _is_permanent_error
    assert _is_permanent_error(Exception("missing required field: tenant_id")) is True


def test_is_permanent_error_httpx_4xx_permanent() -> None:
    import httpx
    from modules.graph_outbox_worker import _is_permanent_error

    request = httpx.Request("POST", "https://example.com")
    err_404 = httpx.HTTPStatusError(
        "not found", request=request, response=httpx.Response(404, request=request)
    )
    assert _is_permanent_error(err_404) is True


def test_is_permanent_error_httpx_429_transient() -> None:
    import httpx
    from modules.graph_outbox_worker import _is_permanent_error

    request = httpx.Request("POST", "https://example.com")
    err_429 = httpx.HTTPStatusError(
        "rate limited", request=request, response=httpx.Response(429, request=request)
    )
    assert _is_permanent_error(err_429) is False


def test_is_permanent_error_httpx_5xx_transient() -> None:
    import httpx
    from modules.graph_outbox_worker import _is_permanent_error

    request = httpx.Request("POST", "https://example.com")
    err_503 = httpx.HTTPStatusError(
        "server error", request=request, response=httpx.Response(503, request=request)
    )
    assert _is_permanent_error(err_503) is False


@pytest.mark.asyncio
async def test_mark_job_failed_permanent_skips_retries() -> None:
    from modules.graph_outbox_worker import _mark_job_failed

    captured: list[dict[str, Any]] = []
    update_chain = MagicMock()
    update_chain.update.side_effect = lambda payload: (
        captured.append(payload) or update_chain
    )
    update_chain.eq.return_value = update_chain
    update_chain.execute.return_value = SimpleNamespace(data=[])

    mock_sb = MagicMock()
    mock_sb.table.return_value = update_chain

    job = {"id": "job-perm", "attempt_count": 1, "max_attempts": 5}

    with patch("modules.graph_outbox_worker.supabase", mock_sb):
        await _mark_job_failed(job, "invalid_payload: missing twin_id", permanent=True)

    payload = captured[0]
    assert payload["status"] == "failed"
    assert payload["attempt_count"] == 5
    assert "invalid_payload" in payload["error_message"]
    assert "next_attempt_after" not in payload


@pytest.mark.asyncio
async def test_mark_job_failed_transient_increments_attempts() -> None:
    from modules.graph_outbox_worker import _mark_job_failed

    captured: list[dict[str, Any]] = []
    update_chain = MagicMock()
    update_chain.update.side_effect = lambda payload: (
        captured.append(payload) or update_chain
    )
    update_chain.eq.return_value = update_chain
    update_chain.execute.return_value = SimpleNamespace(data=[])

    mock_sb = MagicMock()
    mock_sb.table.return_value = update_chain

    job = {"id": "job-tran", "attempt_count": 1, "max_attempts": 5}

    with patch("modules.graph_outbox_worker.supabase", mock_sb):
        await _mark_job_failed(job, "supabase 503")

    payload = captured[0]
    assert payload["status"] == "pending"
    assert payload["attempt_count"] == 2
    assert "next_attempt_after" in payload
