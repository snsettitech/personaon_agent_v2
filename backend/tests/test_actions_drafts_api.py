"""Tests for the owner-scoped action drafts API (Phase B2)."""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from tests._supabase_mock import fluent

OWNER = {"user_id": "user-1", "tenant_id": "tenant-1"}


def _draft(**over: Any) -> dict[str, Any]:
    base = {
        "id": "draft-1",
        "twin_id": "twin-1",
        "status": "pending",
        "proposed_action": {"action_type": "draft_email", "params": {"to": "x@y.com"}},
        "context": {"source": "chat"},
        "created_at": "2026-06-19T00:00:00Z",
        "expires_at": None,
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_list_drafts_returns_pending_for_owner() -> None:
    from routers import actions_drafts as r

    with patch.object(r, "get_supabase_client", return_value=fluent([_draft()])), \
            patch.object(r, "verify_twin_ownership"):
        resp = await r.list_drafts(twin_id="twin-1", user=OWNER)

    assert resp.status == "ok"
    assert len(resp.data.drafts) == 1
    assert resp.data.drafts[0].id == "draft-1"


@pytest.mark.asyncio
async def test_list_drafts_non_owner_403() -> None:
    from routers import actions_drafts as r

    with patch.object(r, "get_supabase_client", return_value=fluent([])), \
            patch.object(r, "verify_twin_ownership",
                         side_effect=HTTPException(status_code=403, detail="nope")):
        with pytest.raises(HTTPException) as exc:
            await r.list_drafts(twin_id="twin-1", user=OWNER)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_approve_enqueues_send_and_does_not_execute_inline() -> None:
    from routers import actions_drafts as r
    from modules.graph_outbox import GraphOperationType

    outbox = MagicMock()
    outbox.submit.return_value = "job-9"
    with patch.object(r, "get_supabase_client", return_value=fluent(_draft())), \
            patch.object(r, "verify_twin_ownership"), \
            patch.object(r, "get_graph_outbox", return_value=outbox):
        resp = await r.approve_draft(twin_id="twin-1", draft_id="draft-1", user=OWNER)

    assert resp.data.status == "approved"
    assert resp.data.job_id == "job-9"
    outbox.submit.assert_called_once()
    kwargs = outbox.submit.call_args.kwargs
    assert kwargs["operation"] == GraphOperationType.SEND_FOLLOWUP_DRAFT
    assert kwargs["idempotency_key"] == "send_followup:draft-1"
    assert kwargs["payload"]["draft_id"] == "draft-1"


@pytest.mark.asyncio
async def test_approve_non_pending_returns_409() -> None:
    from routers import actions_drafts as r

    outbox = MagicMock()
    with patch.object(r, "get_supabase_client", return_value=fluent(_draft(status="approved"))), \
            patch.object(r, "verify_twin_ownership"), \
            patch.object(r, "get_graph_outbox", return_value=outbox):
        with pytest.raises(HTTPException) as exc:
            await r.approve_draft(twin_id="twin-1", draft_id="draft-1", user=OWNER)
    assert exc.value.status_code == 409
    outbox.submit.assert_not_called()


@pytest.mark.asyncio
async def test_approve_cross_tenant_draft_404() -> None:
    from routers import actions_drafts as r

    outbox = MagicMock()
    with patch.object(r, "get_supabase_client", return_value=fluent(None)), \
            patch.object(r, "verify_twin_ownership"), \
            patch.object(r, "get_graph_outbox", return_value=outbox):
        with pytest.raises(HTTPException) as exc:
            await r.approve_draft(twin_id="twin-1", draft_id="draft-1", user=OWNER)
    assert exc.value.status_code == 404
    outbox.submit.assert_not_called()


@pytest.mark.asyncio
async def test_discard_marks_rejected() -> None:
    from routers import actions_drafts as r

    with patch.object(r, "get_supabase_client", return_value=fluent(_draft())), \
            patch.object(r, "verify_twin_ownership"):
        resp = await r.discard_draft(twin_id="twin-1", draft_id="draft-1", user=OWNER)
    assert resp.data.status == "rejected"


@pytest.mark.asyncio
async def test_discard_non_owner_403() -> None:
    from routers import actions_drafts as r

    with patch.object(r, "get_supabase_client", return_value=fluent(_draft())), \
            patch.object(r, "verify_twin_ownership",
                         side_effect=HTTPException(status_code=403, detail="nope")):
        with pytest.raises(HTTPException) as exc:
            await r.discard_draft(twin_id="twin-1", draft_id="draft-1", user=OWNER)
    assert exc.value.status_code == 403
