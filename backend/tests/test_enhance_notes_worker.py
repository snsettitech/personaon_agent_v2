"""Tests for the _process_enhance_notes graph_outbox worker handler (Batch 3).

Covers:
- ready path: writes enhanced_notes_json + status='ready'
- skipped path: no notes AND no segments -> status='skipped', returns True
- failure path: service returns None -> status='failed', returns False (retry)
- missing meeting row -> returns True (nothing to retry)
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

MEETING_ID = "11111111-1111-1111-1111-111111111111"


def _result(data: Any) -> SimpleNamespace:
    return SimpleNamespace(data=data)


def _supabase(*, meeting_row: dict[str, Any] | None, segments: list[dict[str, Any]]) -> tuple[MagicMock, list[dict[str, Any]]]:
    """Route by table name. meetings: select->row, update->capture.
    meeting_transcript_segments: select->segments."""
    updates: list[dict[str, Any]] = []

    meetings_chain = MagicMock()
    for method in ("select", "eq", "maybe_single"):
        getattr(meetings_chain, method).return_value = meetings_chain
    meetings_chain.execute.return_value = _result(meeting_row)

    def _update(payload: dict[str, Any]) -> MagicMock:
        updates.append(payload)
        return meetings_chain

    meetings_chain.update.side_effect = _update

    seg_chain = MagicMock()
    for method in ("select", "eq", "order"):
        getattr(seg_chain, method).return_value = seg_chain
    seg_chain.execute.return_value = _result(segments)

    sb = MagicMock()
    sb.table.side_effect = lambda name: meetings_chain if name == "meetings" else seg_chain
    return sb, updates


def _supabase_capture_eq(
    *, meeting_row: dict[str, Any] | None, segments: list[dict[str, Any]]
) -> tuple[MagicMock, list[dict[str, Any]], list[dict[str, Any]]]:
    """Like _supabase but ALSO captures the .eq() filters applied to each meetings
    UPDATE so a tenant-scope test (QG2 F3) can assert tenant_id is present."""
    updates: list[dict[str, Any]] = []
    update_filters: list[dict[str, Any]] = []
    # current filters accumulated since the last .update() call
    _pending: dict[str, Any] = {}

    meetings_chain = MagicMock()
    for method in ("select", "maybe_single"):
        getattr(meetings_chain, method).return_value = meetings_chain

    def _eq(field: str, value: Any) -> MagicMock:
        _pending[field] = value
        return meetings_chain

    meetings_chain.eq.side_effect = _eq

    def _update(payload: dict[str, Any]) -> MagicMock:
        updates.append(payload)
        _pending.clear()
        return meetings_chain

    meetings_chain.update.side_effect = _update

    def _execute() -> SimpleNamespace:
        # On each execute after an update, snapshot the filters applied.
        if len(update_filters) < len(updates):
            update_filters.append(dict(_pending))
        return _result(meeting_row)

    meetings_chain.execute.side_effect = _execute

    seg_chain = MagicMock()
    for method in ("select", "eq", "order"):
        getattr(seg_chain, method).return_value = seg_chain
    seg_chain.execute.return_value = _result(segments)

    sb = MagicMock()
    sb.table.side_effect = lambda name: meetings_chain if name == "meetings" else seg_chain
    return sb, updates, update_filters


def _job() -> dict[str, Any]:
    return {
        "id": "job-enhance-1",
        "operation": "enhance_notes",
        "tenant_id": "tenant-1",
        "payload": {"meeting_id": MEETING_ID, "tenant_id": "tenant-1", "twin_id": None},
    }


@pytest.mark.asyncio
async def test_enhance_notes_ready_path() -> None:
    from modules.graph_outbox_worker import _process_enhance_notes

    meeting_row = {"id": MEETING_ID, "tenant_id": "tenant-1", "twin_id": None, "user_notes_json": {"text": "Notes"}}
    segments = [{"seq": 0, "speaker": "Alice", "text": "hi", "start_ms": 100}]
    sb, updates = _supabase(meeting_row=meeting_row, segments=segments)

    artifact = {"title": "T", "sections": [{"heading": "H", "from_user": True, "body_md": "B", "evidence": []}]}

    with patch("modules.graph_outbox_worker.supabase", sb), \
         patch("services.enhanced_notes_service.generate_enhanced_notes", new_callable=AsyncMock, return_value=artifact):
        ok = await _process_enhance_notes(_job())

    assert ok is True
    # first update marks generating; final update writes ready + artifact
    assert updates[0]["enhanced_notes_status"] == "generating"
    final = updates[-1]
    assert final["enhanced_notes_status"] == "ready"
    assert final["enhanced_notes_json"] == artifact
    assert final["recap_stage"] == "enhanced_ready"


@pytest.mark.asyncio
async def test_enhance_notes_skipped_no_input() -> None:
    from modules.graph_outbox_worker import _process_enhance_notes

    meeting_row = {"id": MEETING_ID, "tenant_id": "tenant-1", "twin_id": None, "user_notes_json": {"text": ""}}
    sb, updates = _supabase(meeting_row=meeting_row, segments=[])

    # Service must NOT be called when there's nothing to merge.
    gen = AsyncMock(side_effect=AssertionError("should not generate"))
    with patch("modules.graph_outbox_worker.supabase", sb), \
         patch("services.enhanced_notes_service.generate_enhanced_notes", gen):
        ok = await _process_enhance_notes(_job())

    assert ok is True
    assert updates[-1]["enhanced_notes_status"] == "skipped"
    gen.assert_not_called()


@pytest.mark.asyncio
async def test_enhance_notes_failure_returns_false() -> None:
    from modules.graph_outbox_worker import _process_enhance_notes

    meeting_row = {"id": MEETING_ID, "tenant_id": "tenant-1", "twin_id": None, "user_notes_json": {"text": "Notes"}}
    segments = [{"seq": 0, "text": "hi", "start_ms": 100}]
    sb, updates = _supabase(meeting_row=meeting_row, segments=segments)

    with patch("modules.graph_outbox_worker.supabase", sb), \
         patch("services.enhanced_notes_service.generate_enhanced_notes", new_callable=AsyncMock, return_value=None):
        ok = await _process_enhance_notes(_job())

    assert ok is False  # triggers retry
    assert updates[-1]["enhanced_notes_status"] == "failed"


@pytest.mark.asyncio
async def test_enhance_notes_missing_meeting_returns_true() -> None:
    from modules.graph_outbox_worker import _process_enhance_notes

    sb, _updates = _supabase(meeting_row=None, segments=[])
    with patch("modules.graph_outbox_worker.supabase", sb):
        ok = await _process_enhance_notes(_job())
    assert ok is True  # nothing to retry


@pytest.mark.asyncio
async def test_enhance_notes_updates_are_tenant_scoped() -> None:
    """QG2 F3: every meetings UPDATE in the enhance handler must filter on
    tenant_id (not just id) per the tenant_scope_mutations policy."""
    from modules.graph_outbox_worker import _process_enhance_notes

    meeting_row = {"id": MEETING_ID, "tenant_id": "tenant-1", "twin_id": None, "user_notes_json": {"text": "Notes"}}
    segments = [{"seq": 0, "speaker": "Alice", "text": "hi", "start_ms": 100}]
    sb, updates, update_filters = _supabase_capture_eq(meeting_row=meeting_row, segments=segments)

    artifact = {"title": "T", "sections": [{"heading": "H", "from_user": True, "body_md": "B", "evidence": []}]}

    with patch("modules.graph_outbox_worker.supabase", sb), \
         patch("services.enhanced_notes_service.generate_enhanced_notes", new_callable=AsyncMock, return_value=artifact):
        ok = await _process_enhance_notes(_job())

    assert ok is True
    # Two UPDATEs occur on the ready path (generating + ready). Every one must be
    # scoped to BOTH id and tenant_id.
    assert len(update_filters) == len(updates) == 2
    for filt in update_filters:
        assert filt.get("id") == MEETING_ID
        assert filt.get("tenant_id") == "tenant-1"
