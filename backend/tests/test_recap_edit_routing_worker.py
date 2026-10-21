"""Tests for route_recap_edit_to_store worker."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _result(data: Any) -> SimpleNamespace:
    return SimpleNamespace(data=data)


def _chain(execute_results: list[Any]) -> MagicMock:
    """Fluent supabase mock that resolves to the next item per .execute() call."""
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.maybe_single.return_value = chain
    chain.single.return_value = chain
    chain.update.return_value = chain
    chain.execute.side_effect = execute_results
    return chain


@pytest.mark.asyncio
async def test_route_recap_edit_worker_classifies_and_updates_store() -> None:
    from modules.graph_outbox_worker import _process_route_recap_edit_to_store

    edit = {
        "id": "edit-1",
        "field": "tldr",
        "before": "Old",
        "after": "New",
        "tenant_id": "tenant-1",
    }
    chain = _chain([_result(edit), _result([{"id": "edit-1"}])])
    captured_updates: list[dict[str, Any]] = []
    chain.update.side_effect = lambda payload: (captured_updates.append(payload) or chain)

    with patch("modules.graph_outbox_worker.supabase") as mock_sb, \
         patch("services.recap_router.classify_edit_to_store", new_callable=AsyncMock, return_value="style"):
        mock_sb.table.return_value = chain
        ok = await _process_route_recap_edit_to_store({
            "id": "job-route-1",
            "operation": "route_recap_edit_to_store",
            "tenant_id": "tenant-1",
            "payload": {"edit_id": "edit-1", "tenant_id": "tenant-1"},
        })

    assert ok is True
    assert captured_updates == [{"store_routing": "style"}]


@pytest.mark.asyncio
async def test_route_recap_edit_worker_missing_edit_id_skips() -> None:
    from modules.graph_outbox_worker import _process_route_recap_edit_to_store

    ok = await _process_route_recap_edit_to_store({
        "id": "job-route-empty",
        "operation": "route_recap_edit_to_store",
        "payload": {},
    })

    assert ok is True


@pytest.mark.asyncio
async def test_route_recap_edit_worker_skips_if_already_routed() -> None:
    """Regression for review blocker #6 (F2.2): if `store_routing` is
    already populated on the edit, the worker MUST NOT call Gemini
    again (would otherwise overwrite a correct routing on retry).
    """
    from modules.graph_outbox_worker import _process_route_recap_edit_to_store

    already_routed = {
        "id": "edit-already",
        "field": "tldr",
        "before": "old",
        "after": "new",
        "tenant_id": "tenant-1",
        "store_routing": "facts",  # already classified
    }
    chain = _chain([_result(already_routed)])

    classify_mock = AsyncMock(return_value="positions")
    update_count = 0
    original_update = chain.update

    def _track_update(payload: dict[str, Any]) -> MagicMock:
        nonlocal update_count
        update_count += 1
        return original_update(payload)

    chain.update.side_effect = _track_update

    with patch("modules.graph_outbox_worker.supabase") as mock_sb, \
         patch("services.recap_router.classify_edit_to_store", classify_mock):
        mock_sb.table.return_value = chain
        ok = await _process_route_recap_edit_to_store({
            "id": "job-retry",
            "operation": "route_recap_edit_to_store",
            "tenant_id": "tenant-1",
            "payload": {"edit_id": "edit-already", "tenant_id": "tenant-1"},
        })

    assert ok is True
    # Critical: Gemini classify NOT called; UPDATE NOT called.
    classify_mock.assert_not_called()
    assert update_count == 0


@pytest.mark.asyncio
async def test_route_recap_edit_worker_skips_cross_tenant_edit() -> None:
    """Regression for review blocker #2: SELECT filters by tenant_id, so an
    edit_id whose row belongs to a different tenant returns 0 rows and the
    worker short-circuits with True (done) without calling Gemini.
    """
    from modules.graph_outbox_worker import _process_route_recap_edit_to_store

    # SELECT with .eq("id", edit_id).eq("tenant_id", "tenant-A") on a row
    # owned by tenant-B returns no data.
    chain = _chain([_result(None)])

    classify_mock = AsyncMock(return_value="facts")
    with patch("modules.graph_outbox_worker.supabase") as mock_sb, \
         patch("services.recap_router.classify_edit_to_store", classify_mock):
        mock_sb.table.return_value = chain
        ok = await _process_route_recap_edit_to_store({
            "id": "job-route-cross-tenant",
            "operation": "route_recap_edit_to_store",
            "tenant_id": "tenant-A",
            "payload": {"edit_id": "edit-belonging-to-tenant-B", "tenant_id": "tenant-A"},
        })

    assert ok is True  # done, nothing to retry
    # Critical: Gemini classification MUST NOT have been called for a
    # cross-tenant edit.
    classify_mock.assert_not_called()
