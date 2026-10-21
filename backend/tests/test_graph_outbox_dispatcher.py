"""Tests for the graph_outbox dispatcher (``_dispatch``).

Covers the 2026-05-31 audit findings:

* Fix 2: Jobs enqueued for ``UPDATE_CLAIM_STATUS``, ``DELETE_TWIN_GRAPH``,
  ``CREATE_RELATIONSHIP``, and ``EXTRACT_COMMITMENTS`` previously fell
  through to the catch-all ``return True`` and were silently marked
  completed despite no real work happening. The dispatcher now returns
  ``False`` so the job retries to exhaustion and lands on the failed pile
  where operators can see it.

* Fix 2 (continued): The truly-unknown-operation branch (no enum match)
  also returns ``False`` rather than silently completing.

* Fix 3: ``_process_firecrawl_extract`` re-raises if the terminal
  ``_mark_job_completed`` call fails, so the job doesn\'t get stuck in
  ``processing``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_job(operation: str) -> dict[str, Any]:
    """Minimal job row shape for the dispatcher."""
    return {
        "id": f"job-{operation}",
        "tenant_id": "tenant-1",
        "twin_id": "twin-1",
        "operation": operation,
        "payload": {},
        "attempt_count": 0,
        "max_attempts": 5,
    }


# Fix 2 -- _dispatch returns False for unhandled known + unknown operations.

@pytest.mark.asyncio
@pytest.mark.parametrize(
    "operation_value",
    [
        "update_claim_status",
        "delete_twin_graph",
        "create_relationship",
        "extract_commitments",
    ],
)
async def test_dispatch_returns_false_for_known_but_unhandled_operations(
    operation_value: str,
) -> None:
    """Each unhandled GraphOperationType enum value must return False, NOT
    True. Returning True silently completes a job that did no real work --
    the operator has no way to tell the work didn\'t happen.
    """
    from modules import graph_outbox_worker
    from modules.graph_outbox import GraphOperationType

    # Sanity: confirm the operation value really is a known enum (this
    # is the whole point -- it\'s enum-known but handler-missing).
    assert operation_value in {e.value for e in GraphOperationType}

    job = _make_job(operation_value)
    result = await graph_outbox_worker._dispatch(job)

    assert result is False, (
        f"unhandled known operation {operation_value!r} must return False "
        f"(would otherwise silently complete a no-op job)"
    )


@pytest.mark.asyncio
async def test_dispatch_returns_false_for_completely_unknown_operation() -> None:
    """An operation string that doesn\'t match any enum value (typo, stale
    job from a removed enum, future enum on an old worker) must also return
    False -- silently completing it masks queue mis-configuration."""
    from modules import graph_outbox_worker

    job = _make_job("totally_made_up_operation_xyz")
    result = await graph_outbox_worker._dispatch(job)

    assert result is False


@pytest.mark.asyncio
async def test_dispatch_still_routes_handled_operations() -> None:
    """Regression guard: the unhandled-fallthrough fix must NOT change the
    behavior of operations that DO have handlers wired up. We patch one
    handler and confirm the dispatcher still routes to it.
    """
    from modules import graph_outbox_worker
    from modules.graph_outbox import GraphOperationType

    job = _make_job(GraphOperationType.REFRESH_SNAPSHOT.value)
    job["payload"] = {"scope_id": None}

    with patch.object(
        graph_outbox_worker,
        "_process_refresh_snapshot",
        new_callable=AsyncMock,
        return_value=True,
    ) as mock_handler:
        result = await graph_outbox_worker._dispatch(job)

    assert result is True
    mock_handler.assert_awaited_once_with(job)


# End-to-end through process_next_graph_outbox_job: False -> _mark_job_failed.

@pytest.mark.asyncio
async def test_unhandled_operation_marks_job_failed_via_process_next() -> None:
    """End-to-end: a job for one of the unhandled enums goes through
    process_next_graph_outbox_job -> _dispatch (returns False) ->
    _mark_job_failed (NOT _mark_job_completed). This is the operator-
    visible outcome of fix 2.
    """
    from modules import graph_outbox_worker
    from modules.graph_outbox import GraphOperationType

    job = _make_job(GraphOperationType.DELETE_TWIN_GRAPH.value)

    with (
        patch.object(
            graph_outbox_worker,
            "_list_pending_job_ids",
            new_callable=AsyncMock,
            return_value=[job["id"]],
        ),
        patch.object(
            graph_outbox_worker,
            "_claim_job",
            new_callable=AsyncMock,
            return_value=job,
        ),
        patch.object(
            graph_outbox_worker,
            "_mark_job_completed",
            new_callable=AsyncMock,
        ) as mock_completed,
        patch.object(
            graph_outbox_worker,
            "_mark_job_failed",
            new_callable=AsyncMock,
        ) as mock_failed,
    ):
        ran = await graph_outbox_worker.process_next_graph_outbox_job("worker-test")

    assert ran is True
    mock_completed.assert_not_awaited()
    mock_failed.assert_awaited_once()
    failed_args = mock_failed.await_args
    assert failed_args is not None
    assert failed_args.args[0] is job  # the job row
    assert "unsuccessful" in failed_args.args[1].lower()


# Fix 3 -- _process_firecrawl_extract re-raises on _mark_job_completed failure.

@pytest.mark.asyncio
async def test_firecrawl_extract_reraises_when_mark_completed_fails_on_success_path() -> None:
    """If the success-path _mark_job_completed call raises (transient DB
    flap), the function must re-raise rather than swallow + return None.
    The outer dispatcher would otherwise treat None as 'self-marked' and
    skip error handling, leaving the job in 'processing' forever."""
    from modules import graph_outbox_worker

    job = {
        "id": "firecrawl-1",
        "payload": {"person_name": "Ada Lovelace"},
    }

    fake_mark = AsyncMock(side_effect=RuntimeError("supabase write timeout"))
    fake_extract = MagicMock(return_value={"name": "Ada Lovelace"})

    with (
        patch.object(graph_outbox_worker, "_mark_job_completed", fake_mark),
        patch(
            "adk_core.services.firecrawl_service.extract_profile",
            fake_extract,
        ),
    ):
        with pytest.raises(RuntimeError, match="supabase write timeout"):
            await graph_outbox_worker._process_firecrawl_extract(job)


@pytest.mark.asyncio
async def test_firecrawl_extract_reraises_when_mark_completed_fails_on_empty_name() -> None:
    """Same guarantee on the missing-person_name short-circuit branch: a
    failed self-mark must propagate so the dispatcher fails the job."""
    from modules import graph_outbox_worker

    job = {"id": "firecrawl-2", "payload": {}}  # no person_name

    fake_mark = AsyncMock(side_effect=RuntimeError("supabase write timeout"))

    with patch.object(graph_outbox_worker, "_mark_job_completed", fake_mark):
        with pytest.raises(RuntimeError, match="supabase write timeout"):
            await graph_outbox_worker._process_firecrawl_extract(job)


@pytest.mark.asyncio
async def test_firecrawl_extract_returns_none_on_happy_path() -> None:
    """Sanity: when _mark_job_completed succeeds, _process_firecrawl_extract
    returns None (the self-marked sentinel the dispatcher relies on)."""
    from modules import graph_outbox_worker

    job = {
        "id": "firecrawl-3",
        "payload": {"person_name": "Grace Hopper"},
    }

    fake_mark = AsyncMock()
    fake_extract = MagicMock(return_value={"name": "Grace Hopper"})

    with (
        patch.object(graph_outbox_worker, "_mark_job_completed", fake_mark),
        patch(
            "adk_core.services.firecrawl_service.extract_profile",
            fake_extract,
        ),
    ):
        result = await graph_outbox_worker._process_firecrawl_extract(job)

    assert result is None
    fake_mark.assert_awaited_once()
