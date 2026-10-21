"""Worker-side tests for _process_recall_calendar_sync.

Covers H5 (cancel-event scope) and H6 (status lookup TOCTOU race) from the
calendar integration audit.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_supabase_for_meetings(
    *,
    twins_tenant_id: str | None = "tenant-1",
    existing_status_rows: list[dict] | None = None,
    existing_status_raises: bool = False,
) -> tuple[MagicMock, dict[str, Any]]:
    """Build a chained supabase mock that satisfies the worker's queries.

    Returns (mock, captured) where captured records all update/upsert
    payloads + the .eq() filters used on each terminal call so the H5/H6
    tests can assert exact scoping.
    """
    sb = MagicMock()
    captured: dict[str, Any] = {
        "meetings_updates": [],   # list of (payload, eq_chain) for UPDATE calls
        "meetings_inserts": [],   # list of payload dicts for INSERT calls (new-row path)
        "meetings_upserts": [],   # legacy: any payload written, regardless of method
    }

    # Coarse routing by .table(name): each table returns its own chain.
    twin_chain = MagicMock()
    twin_chain.select.return_value = twin_chain
    twin_chain.eq.return_value = twin_chain
    twin_chain.single.return_value = twin_chain
    if twins_tenant_id is None:
        twin_chain.execute.return_value = MagicMock(data=None)
    else:
        twin_chain.execute.return_value = MagicMock(data={"tenant_id": twins_tenant_id})

    def _build_meetings_chain() -> MagicMock:
        chain = MagicMock()

        # SELECT path (lookup_existing_status)
        def _select(*args: Any, **kwargs: Any):
            sel = MagicMock()
            sel.eq.return_value = sel
            sel.limit.return_value = sel
            if existing_status_raises:
                sel.execute.side_effect = RuntimeError("transient DB error")
            else:
                sel.execute.return_value = MagicMock(data=existing_status_rows or [])
            return sel

        # UPDATE path (cancel)
        def _update(payload: dict) -> MagicMock:
            upd = MagicMock()
            eq_chain: list[tuple] = []
            captured["meetings_updates"].append((payload, eq_chain))

            def _eq(*args: Any, **kwargs: Any) -> MagicMock:
                eq_chain.append(args)
                return upd

            upd.eq.side_effect = _eq
            upd.execute.return_value = MagicMock(data=None)
            return upd

        # INSERT path (new-row write)
        def _insert(payload: dict) -> MagicMock:
            ins = MagicMock()
            captured["meetings_inserts"].append(payload)
            captured["meetings_upserts"].append(payload)  # legacy alias
            ins.execute.return_value = MagicMock(data=None)
            return ins

        # UPSERT path (still wired for any test that exercises the legacy code path)
        def _upsert(payload: dict, on_conflict: str | None = None) -> MagicMock:
            ups = MagicMock()
            captured["meetings_upserts"].append(payload)
            ups.execute.return_value = MagicMock(data=None)
            return ups

        chain.select.side_effect = _select
        chain.update.side_effect = _update
        chain.insert.side_effect = _insert
        chain.upsert.side_effect = _upsert
        return chain

    def _table_dispatch(name: str) -> MagicMock:
        if name == "twins":
            return twin_chain
        if name == "meetings":
            return _build_meetings_chain()
        return MagicMock()

    sb.table.side_effect = _table_dispatch
    return sb, captured


@pytest.mark.asyncio
async def test_cancel_scoped_by_calendar_id() -> None:
    """H5: a 'deleted' event must mark the row canceled scoped by full key
    tuple, not just (twin_id, provider_event_id). Two calendars can share
    an event id via forwarded events / ical_uid reuse."""
    from modules import graph_outbox_worker

    sb, captured = _fake_supabase_for_meetings()

    events = [{
        "id": "evt_shared",
        "calendar_id": "cal_A",
        "instance_id": "",
        "platform": "google_calendar",
        "status": "deleted",
    }]

    job = {
        "id": "job-1",
        "payload": {
            "recall_calendar_id": "cal_A",
            "twin_id": "twin-1",
            "tenant_id": "tenant-1",
            "last_updated_ts": None,
        },
    }

    with (
        patch.object(graph_outbox_worker, "supabase", sb),
        patch(
            "services.recall_calendar_v2.list_calendar_events",
            new_callable=AsyncMock,
            return_value=events,
        ),
    ):
        ok = await graph_outbox_worker._process_recall_calendar_sync(job)

    assert ok is True
    assert len(captured["meetings_updates"]) == 1
    payload, eq_chain = captured["meetings_updates"][0]
    assert payload.get("status") == "canceled"

    # eq_chain entries are positional args tuples from each .eq() call.
    flat_eq = [a for entry in eq_chain for a in entry]
    # MUST include the calendar id scope so a delete on cal_A can't cascade
    # to a meeting on cal_B sharing the same provider_event_id.
    assert "cal_A" in flat_eq, (
        f"cancel update must be scoped by provider_calendar_id; got eq args: {eq_chain}"
    )
    assert "twin-1" in flat_eq
    assert "evt_shared" in flat_eq
    assert "google_calendar" in flat_eq


@pytest.mark.asyncio
async def test_upsert_omits_lifecycle_on_status_lookup_failure() -> None:
    """H6 (TOCTOU): if the status lookup raises, the upsert must NOT set
    status/twin_attends/mode -- doing so would resurrect a terminal-status
    meeting back to 'scheduled' (re-dispatching the bot)."""
    from modules import graph_outbox_worker

    sb, captured = _fake_supabase_for_meetings(existing_status_raises=True)

    events = [{
        "id": "evt_existing",
        "calendar_id": "cal_A",
        "instance_id": "",
        "platform": "google_calendar",
        "status": "confirmed",
        "start_time": "2026-06-01T15:00:00Z",
        "end_time": "2026-06-01T15:30:00Z",
        "title": "Existing meeting",
    }]

    job = {
        "id": "job-2",
        "payload": {
            "recall_calendar_id": "cal_A",
            "twin_id": "twin-1",
            "tenant_id": "tenant-1",
            "last_updated_ts": "2026-05-31T15:00:00Z",
        },
    }

    with (
        patch.object(graph_outbox_worker, "supabase", sb),
        patch(
            "services.recall_calendar_v2.list_calendar_events",
            new_callable=AsyncMock,
            return_value=events,
        ),
    ):
        ok = await graph_outbox_worker._process_recall_calendar_sync(job)

    assert ok is True
    assert len(captured["meetings_upserts"]) == 1
    upsert_row = captured["meetings_upserts"][0]
    assert "status" not in upsert_row, (
        "lookup failure must not write status (would resurrect terminal state)"
    )
    assert "twin_attends" not in upsert_row, (
        "lookup failure must not write twin_attends (would override user toggle)"
    )
    assert "mode" not in upsert_row, (
        "lookup failure must not write mode (would override user toggle)"
    )
    # Metadata fields still refresh on the existing row
    assert upsert_row["title"] == "Existing meeting"
    assert upsert_row["meeting_start"] == "2026-06-01T15:00:00Z"


@pytest.mark.asyncio
async def test_event_with_ical_uid_uses_ical_uid_for_lookup_and_upsert() -> None:
    """An event payload carrying ical_uid must be looked up + UPDATEd by
    (twin_id, ical_uid, instance_id) rather than the legacy provider_event_id
    scope. This is what makes the same Google/Outlook event survive Recall
    calendar churn (disconnect+reconnect -> new recall_calendar_id but same
    ical_uid -> matches existing row, UPDATEs it, no duplicate)."""
    from modules import graph_outbox_worker

    sb, captured = _fake_supabase_for_meetings(
        existing_status_rows=[{"status": "scheduled"}],
    )

    events = [{
        "id": "recall-uuid-new-calendar",  # changes per Recall calendar
        "platform_id": "google-event-abc",
        "ical_uid": "google-event-abc@google.com",  # STABLE
        "calendar_id": "cal_NEW",
        "instance_id": "",
        "platform": "google_calendar",
        "status": "confirmed",
        "start_time": "2026-06-01T15:00:00Z",
        "end_time": "2026-06-01T15:30:00Z",
        "title": "Meeting that survived a Recall reconnect",
    }]

    job = {
        "id": "job-icaluid-test",
        "payload": {
            "recall_calendar_id": "cal_NEW",
            "twin_id": "twin-1",
            "tenant_id": "tenant-1",
            "last_updated_ts": "2026-05-31T10:00:00Z",
        },
    }

    with (
        patch.object(graph_outbox_worker, "supabase", sb),
        patch(
            "services.recall_calendar_v2.list_calendar_events",
            new_callable=AsyncMock,
            return_value=events,
        ),
    ):
        ok = await graph_outbox_worker._process_recall_calendar_sync(job)

    assert ok is True
    # Did not double-insert; existing row was updated instead.
    assert len(captured["meetings_inserts"]) == 0, (
        f"existing-row path must not INSERT; got: {captured['meetings_inserts']}"
    )

    # Find the UPDATE for this synced event (cancel UPDATEs are a separate path).
    sync_updates = [
        u for u in captured["meetings_updates"]
        if isinstance(u[0], dict) and u[0].get("title") == "Meeting that survived a Recall reconnect"
    ]
    assert len(sync_updates) == 1, (
        f"expected one sync UPDATE; got {captured['meetings_updates']}"
    )
    payload, eq_chain = sync_updates[0]
    flat_eq = [a for entry in eq_chain for a in entry]

    # UPDATE is scoped by ical_uid (NOT by provider_calendar_id) -- that's the
    # whole point of this fix.
    assert "google-event-abc@google.com" in flat_eq, (
        f"UPDATE must be scoped by ical_uid; got eq args: {eq_chain}"
    )
    assert "ical_uid" in flat_eq, "an .eq('ical_uid', ...) call must appear in the chain"
    # Recall calendar id MUST NOT scope this UPDATE -- otherwise the same event
    # under a new Recall calendar after reconnect would be skipped.
    assert "cal_NEW" not in flat_eq, (
        "UPDATE must NOT be scoped by provider_calendar_id when ical_uid is "
        f"present; got eq args: {eq_chain}"
    )

    # Row payload includes ical_uid so the INSERT path (or future row) carries it.
    assert payload.get("title") == "Meeting that survived a Recall reconnect"


@pytest.mark.asyncio
async def test_new_event_with_ical_uid_writes_ical_uid_on_insert() -> None:
    """A new event payload carrying ical_uid must store ical_uid on the inserted
    row (so future syncs from a different Recall calendar id can match it)."""
    from modules import graph_outbox_worker

    sb, captured = _fake_supabase_for_meetings(existing_status_rows=[])

    events = [{
        "id": "recall-uuid-1",
        "platform_id": "google-evt-1",
        "ical_uid": "google-evt-1@google.com",
        "calendar_id": "cal_A",
        "instance_id": "",
        "platform": "google_calendar",
        "status": "confirmed",
        "start_time": "2026-06-02T10:00:00Z",
        "end_time": "2026-06-02T10:30:00Z",
        "title": "Brand new meeting",
    }]

    job = {
        "id": "job-insert-icaluid",
        "payload": {
            "recall_calendar_id": "cal_A",
            "twin_id": "twin-1",
            "tenant_id": "tenant-1",
            "last_updated_ts": None,
        },
    }

    with (
        patch.object(graph_outbox_worker, "supabase", sb),
        patch(
            "services.recall_calendar_v2.list_calendar_events",
            new_callable=AsyncMock,
            return_value=events,
        ),
    ):
        ok = await graph_outbox_worker._process_recall_calendar_sync(job)

    assert ok is True
    assert len(captured["meetings_inserts"]) == 1
    inserted = captured["meetings_inserts"][0]
    assert inserted["ical_uid"] == "google-evt-1@google.com", (
        f"new row must store ical_uid for future stable-key lookups; got: {inserted}"
    )
    # provider_event_id is still written for backward compatibility / debugging.
    assert inserted.get("provider_event_id") == "recall-uuid-1"


@pytest.mark.asyncio
async def test_event_with_empty_ical_uid_falls_back_to_legacy_scope() -> None:
    """Defensive: an empty-string ical_uid ("" from a malformed provider
    response) must take the legacy path, NOT be written as an empty-string
    ical_uid column value. Locks in the falsy-guard contract so a future
    refactor that changes `if ical_uid_raw` to `if ical_uid_raw is not None`
    cannot silently promote empties."""
    from modules import graph_outbox_worker

    sb, captured = _fake_supabase_for_meetings(existing_status_rows=[])

    events = [{
        "id": "recall-uuid-empty",
        "ical_uid": "",  # malformed/missing on provider side
        "calendar_id": "cal_A",
        "instance_id": "",
        "platform": "google_calendar",
        "status": "confirmed",
        "start_time": "2026-06-05T10:00:00Z",
        "end_time": "2026-06-05T10:30:00Z",
        "title": "Empty ical_uid event",
    }]

    job = {
        "id": "job-empty-icaluid",
        "payload": {
            "recall_calendar_id": "cal_A",
            "twin_id": "twin-1",
            "tenant_id": "tenant-1",
            "last_updated_ts": None,
        },
    }

    with (
        patch.object(graph_outbox_worker, "supabase", sb),
        patch(
            "services.recall_calendar_v2.list_calendar_events",
            new_callable=AsyncMock,
            return_value=events,
        ),
    ):
        ok = await graph_outbox_worker._process_recall_calendar_sync(job)

    assert ok is True
    assert len(captured["meetings_inserts"]) == 1
    inserted = captured["meetings_inserts"][0]
    # Empty ical_uid string must be normalised to None on the row (not "").
    # Writing "" would violate the partial index's IS NOT NULL guard semantics
    # AND would cause future ical_uid lookups to match the wrong row.
    assert inserted.get("ical_uid") is None, (
        f"empty-string ical_uid must be stored as NULL, not ''; got: {inserted.get('ical_uid')!r}"
    )


@pytest.mark.asyncio
async def test_event_without_ical_uid_falls_back_to_legacy_scope() -> None:
    """Pre-ical_uid rows / events that don't carry ical_uid (rare) must still
    work via the legacy (twin_id, provider, calendar_id, event_id, instance_id)
    UPDATE scope."""
    from modules import graph_outbox_worker

    sb, captured = _fake_supabase_for_meetings(
        existing_status_rows=[{"status": "scheduled"}],
    )

    events = [{
        "id": "recall-uuid-2",
        "platform_id": "evt-2",
        # NO ical_uid -- legacy path
        "calendar_id": "cal_A",
        "instance_id": "",
        "platform": "google_calendar",
        "status": "confirmed",
        "start_time": "2026-06-03T10:00:00Z",
        "end_time": "2026-06-03T10:30:00Z",
        "title": "Legacy event",
    }]

    job = {
        "id": "job-legacy",
        "payload": {
            "recall_calendar_id": "cal_A",
            "twin_id": "twin-1",
            "tenant_id": "tenant-1",
            "last_updated_ts": "2026-05-31T10:00:00Z",
        },
    }

    with (
        patch.object(graph_outbox_worker, "supabase", sb),
        patch(
            "services.recall_calendar_v2.list_calendar_events",
            new_callable=AsyncMock,
            return_value=events,
        ),
    ):
        ok = await graph_outbox_worker._process_recall_calendar_sync(job)

    assert ok is True
    sync_updates = [
        u for u in captured["meetings_updates"]
        if isinstance(u[0], dict) and u[0].get("title") == "Legacy event"
    ]
    assert len(sync_updates) == 1
    _, eq_chain = sync_updates[0]
    flat_eq = [a for entry in eq_chain for a in entry]

    # Legacy scope: must include calendar_id (no ical_uid available to use instead)
    assert "cal_A" in flat_eq
    assert "recall-uuid-2" in flat_eq
    assert "google_calendar" in flat_eq


@pytest.mark.asyncio
async def test_existing_row_updates_not_inserts() -> None:
    """When the status lookup confirms a row exists, the worker UPDATES it
    (preserving lifecycle state) rather than INSERTing a duplicate. This is
    the path that was previously broken by .upsert(on_conflict=...) matching
    no constraint -> PostgREST 42P10 silently swallowed by the SDK -> writes
    lost entirely."""
    from modules import graph_outbox_worker

    sb, captured = _fake_supabase_for_meetings(
        existing_status_rows=[{"status": "scheduled"}],
    )

    events = [{
        "id": "evt_existing_row",
        "calendar_id": "cal_A",
        "instance_id": "",
        "platform": "google_calendar",
        "status": "confirmed",
        "start_time": "2026-06-01T15:00:00Z",
        "end_time": "2026-06-01T15:30:00Z",
        "title": "Re-synced existing meeting",
    }]

    job = {
        "id": "job-update-test",
        "payload": {
            "recall_calendar_id": "cal_A",
            "twin_id": "twin-1",
            "tenant_id": "tenant-1",
            "last_updated_ts": "2026-05-31T10:00:00Z",
        },
    }

    with (
        patch.object(graph_outbox_worker, "supabase", sb),
        patch(
            "services.recall_calendar_v2.list_calendar_events",
            new_callable=AsyncMock,
            return_value=events,
        ),
    ):
        ok = await graph_outbox_worker._process_recall_calendar_sync(job)

    assert ok is True
    assert len(captured["meetings_inserts"]) == 0, (
        "existing-row path must not INSERT; got inserts="
        f"{captured['meetings_inserts']}"
    )
    # Exactly one UPDATE for the synced event (cancel updates are a separate path).
    sync_updates = [
        u for u in captured["meetings_updates"]
        if isinstance(u[0], dict) and u[0].get("title") == "Re-synced existing meeting"
    ]
    assert len(sync_updates) == 1, (
        f"existing-row path must UPDATE exactly once; got: {captured['meetings_updates']}"
    )

    # The UPDATE must be scoped by the FULL 5-key tuple matching the partial
    # unique index, otherwise a same-id event on a different calendar could be
    # overwritten.
    payload, eq_chain = sync_updates[0]
    flat_eq = [a for entry in eq_chain for a in entry]
    assert "twin-1" in flat_eq
    assert "google_calendar" in flat_eq
    assert "cal_A" in flat_eq
    assert "evt_existing_row" in flat_eq

    # Lifecycle fields MUST NOT appear in an UPDATE payload (would clobber state).
    assert "status" not in payload
    assert "twin_attends" not in payload
    assert "mode" not in payload


@pytest.mark.asyncio
async def test_upsert_sets_lifecycle_only_on_verified_new_row() -> None:
    """Confirm the positive path: when status lookup confirms an empty result,
    the upsert sets status='scheduled', twin_attends=False, mode='off'."""
    from modules import graph_outbox_worker

    sb, captured = _fake_supabase_for_meetings(existing_status_rows=[])

    events = [{
        "id": "evt_brand_new",
        "calendar_id": "cal_A",
        "instance_id": "",
        "platform": "google_calendar",
        "status": "confirmed",
        "start_time": "2026-06-02T15:00:00Z",
        "end_time": "2026-06-02T15:30:00Z",
        "title": "Brand new meeting",
    }]

    job = {
        "id": "job-3",
        "payload": {
            "recall_calendar_id": "cal_A",
            "twin_id": "twin-1",
            "tenant_id": "tenant-1",
            "last_updated_ts": None,
        },
    }

    with (
        patch.object(graph_outbox_worker, "supabase", sb),
        patch(
            "services.recall_calendar_v2.list_calendar_events",
            new_callable=AsyncMock,
            return_value=events,
        ),
    ):
        ok = await graph_outbox_worker._process_recall_calendar_sync(job)

    assert ok is True
    assert len(captured["meetings_upserts"]) == 1
    row = captured["meetings_upserts"][0]
    assert row["status"] == "scheduled"
    assert row["twin_attends"] is False
    assert row["mode"] == "off"
