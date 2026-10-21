"""Tests for the handle-claim collision path (execution-board task 0.8).

Handle uniqueness used to be application-layer-only: claim_handle read the
full twins table, computed a "taken" set in Python, and picked the first free
candidate — not atomic, so two concurrent /handles/claim requests for the
identical handle could both read the same "taken" set and both attempt to
write it. A DB-level unique index (idx_twins_handle_unique on
lower(settings->>'handle'), see
supabase/migrations/20260703000000_twins_handle_unique_constraint.sql) now
guarantees at most one such write commits; these tests verify claim_handle's
in-process handling of the resulting unique-violation exception raised by the
losing write — retry with a fresh candidate, and a clean 409 (never a raw
500) once retries are exhausted.

NOTE: these are not true concurrency tests — pytest here runs claim_handle
sequentially against a scripted mock, not two real coroutines racing against
a real Postgres unique index. That would require a live database and is out
of scope for the unit-test mock harness used across this repo (see
tests/_supabase_mock.py). What IS verified end-to-end: claim_handle's
except-block correctly detects a unique-violation raised mid-request,
re-picks a candidate against the now-current state, retries, and succeeds —
which is exactly the code path a real race exercises on the loser's request.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from tests._supabase_mock import result

OWNER = {"user_id": "user-1", "tenant_id": "tenant-1"}


def _chain(final_result: Any = None, final_exc: Exception | None = None) -> MagicMock:
    """One-shot fluent chain mock: configures only the terminal .execute() call."""
    m = MagicMock()
    for name in ("select", "eq", "neq", "single", "insert", "update", "delete"):
        getattr(m, name).return_value = m
    if final_exc is not None:
        m.execute.side_effect = final_exc
    else:
        m.execute.return_value = final_result
    return m


class _RouterPatches:
    """Context manager patching routers.handles module globals for a test."""

    def __init__(self, module: Any, table_mock: MagicMock) -> None:
        self._module = module
        self._table_mock = table_mock
        self._patches: list[Any] = []

    def __enter__(self) -> _RouterPatches:
        supabase_mock = MagicMock()
        supabase_mock.table = self._table_mock

        p1 = patch.object(self._module, "supabase", supabase_mock)
        p2 = patch.object(self._module, "verify_twin_ownership", MagicMock(return_value=True))
        p3 = patch.object(self._module, "revalidate_persona", AsyncMock(return_value=None))
        for p in (p1, p2, p3):
            p.start()
            self._patches.append(p)
        return self

    def __exit__(self, *exc: Any) -> None:
        for p in self._patches:
            p.stop()


@pytest.mark.asyncio
async def test_claim_retries_after_unique_violation_race() -> None:
    """
    Two signups race for the same handle within the same second: this
    request's first write attempt loses the DB race (unique-violation raised
    on the underlying idx_twins_handle_unique index) after the winner's
    handle is now visible in a re-read of the twins table. claim_handle must
    retry with a freshly re-picked candidate and succeed — never a raw 500,
    never silently accept the collision.

    The retry (attempt=1) now jitters its starting numeric suffix (see
    _find_available_handle) instead of always restarting the scan at -2, so
    that concurrent losers racing for the same base handle don't converge on
    the identical next candidate every round. random.randint is pinned here
    so the test stays deterministic while still exercising the real
    attempt-aware code path.
    """
    from routers import handles as r
    from routers.handles import HandleClaimRequest

    twin_row_chain = _chain(final_result=result({"id": "twin-1", "settings": {}}))

    # Attempt 1 (attempt=0): nothing taken yet in this snapshot -> picks "alice".
    all_twins_attempt_1 = _chain(final_result=result([
        {"id": "twin-1", "settings": {}},
    ]))
    # Attempt 1's write loses the race: the DB unique index rejected it
    # because a concurrent request's write for "alice" committed first.
    update_attempt_1 = _chain(final_exc=Exception(
        'duplicate key value violates unique constraint "idx_twins_handle_unique"'
    ))

    # Attempt 2 (attempt=1): re-read now shows the winner's committed handle.
    # With random.randint pinned to 2, the jittered scan starts at -2 (same
    # as the old deterministic behavior) -> picks "alice-2".
    all_twins_attempt_2 = _chain(final_result=result([
        {"id": "twin-1", "settings": {}},
        {"id": "twin-2", "settings": {"handle": "alice"}},
    ]))
    update_attempt_2 = _chain(final_result=result([{"id": "twin-1"}]))

    table_mock = MagicMock(side_effect=[
        twin_row_chain,
        all_twins_attempt_1,
        update_attempt_1,
        all_twins_attempt_2,
        update_attempt_2,
    ])

    with _RouterPatches(r, table_mock), patch.object(r.random, "randint", return_value=2):
        resp = await r.claim_handle(
            request=HandleClaimRequest(twin_id="twin-1", handle="Alice"),
            user=OWNER,
        )

    assert resp["handle"] == "alice-2"
    assert resp["url"] == "/p/alice-2"
    # 1 twin-row read + 2 (all-twins read + update) round trips = 5 calls.
    assert table_mock.call_count == 5


@pytest.mark.asyncio
async def test_claim_retry_jitters_instead_of_lockstep_candidate() -> None:
    """
    Without jitter, every concurrent loser re-picks the exact same next
    candidate each retry round (only one winner can resolve per round via
    the DB unique-violation), so a handle further out in the sequence never
    gets reached before MAX_HANDLE_CLAIM_ATTEMPTS is exhausted. On retry
    (attempt >= 1), _find_available_handle must start its scan from a
    randomized offset instead of always restarting at -2.
    """
    from routers import handles as r
    from routers.handles import HandleClaimRequest

    twin_row_chain = _chain(final_result=result({"id": "twin-1", "settings": {}}))

    all_twins_attempt_1 = _chain(final_result=result([
        {"id": "twin-1", "settings": {}},
    ]))
    update_attempt_1 = _chain(final_exc=Exception(
        'duplicate key value violates unique constraint "idx_twins_handle_unique"'
    ))

    all_twins_attempt_2 = _chain(final_result=result([
        {"id": "twin-1", "settings": {}},
        {"id": "twin-2", "settings": {"handle": "alice"}},
    ]))
    update_attempt_2 = _chain(final_result=result([{"id": "twin-1"}]))

    table_mock = MagicMock(side_effect=[
        twin_row_chain,
        all_twins_attempt_1,
        update_attempt_1,
        all_twins_attempt_2,
        update_attempt_2,
    ])

    # Pin the jittered starting offset to 40 (far from the deterministic -2
    # the old code always tried first) and confirm the retry lands there
    # instead of lockstep-converging back onto "alice-2".
    with _RouterPatches(r, table_mock), patch.object(r.random, "randint", return_value=40):
        resp = await r.claim_handle(
            request=HandleClaimRequest(twin_id="twin-1", handle="Alice"),
            user=OWNER,
        )

    assert resp["handle"] == "alice-40"
    assert resp["url"] == "/p/alice-40"


@pytest.mark.asyncio
async def test_claim_returns_409_when_retries_exhausted() -> None:
    """
    If every retry keeps losing the unique-violation race (persistently
    wrong, e.g. a stuck client hammering the same handle), claim_handle must
    surface a clean 409 collision response — never let the raw exception
    propagate as an unhandled 500.
    """
    from routers import handles as r
    from routers.handles import HandleClaimRequest, MAX_HANDLE_CLAIM_ATTEMPTS

    twin_row_chain = _chain(final_result=result({"id": "twin-1", "settings": {}}))

    chains = [twin_row_chain]
    for _ in range(MAX_HANDLE_CLAIM_ATTEMPTS):
        chains.append(_chain(final_result=result([{"id": "twin-1", "settings": {}}])))
        chains.append(_chain(final_exc=Exception("duplicate key value violates unique constraint")))

    table_mock = MagicMock(side_effect=chains)

    with _RouterPatches(r, table_mock):
        with pytest.raises(HTTPException) as exc_info:
            await r.claim_handle(
                request=HandleClaimRequest(twin_id="twin-1", handle="Alice"),
                user=OWNER,
            )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_claim_wraps_unrelated_db_error_as_500_not_raw() -> None:
    """A non-unique-violation DB error still surfaces as a clean HTTPException
    (500 with a user-safe message), not a raw unhandled exception."""
    from routers import handles as r
    from routers.handles import HandleClaimRequest

    twin_row_chain = _chain(final_result=result({"id": "twin-1", "settings": {}}))
    all_twins_chain = _chain(final_result=result([{"id": "twin-1", "settings": {}}]))
    update_chain = _chain(final_exc=Exception("connection reset by peer"))

    table_mock = MagicMock(side_effect=[twin_row_chain, all_twins_chain, update_chain])

    with _RouterPatches(r, table_mock):
        with pytest.raises(HTTPException) as exc_info:
            await r.claim_handle(
                request=HandleClaimRequest(twin_id="twin-1", handle="Alice"),
                user=OWNER,
            )

    assert exc_info.value.status_code == 500


@pytest.mark.asyncio
async def test_claim_retry_preserves_concurrent_settings_write() -> None:
    """
    claim_handle must not clobber a concurrent settings write (e.g. a
    bio-edit PATCH) that lands on the same twin between the initial pre-loop
    settings read and a retried claim. Each retry re-fetches all_twins
    fresh; the update payload must be built from that fresh per-attempt
    snapshot of this twin's settings, not the one-time pre-loop snapshot, or
    it silently reverts the concurrent edit when it writes back the whole
    settings JSONB blob.
    """
    from routers import handles as r
    from routers.handles import HandleClaimRequest

    # Pre-loop snapshot: settings is empty (read before any concurrent edit).
    twin_row_chain = _chain(final_result=result({"id": "twin-1", "settings": {}}))

    # Attempt 1 (attempt=0): fresh read still shows empty settings -> picks "alice".
    all_twins_attempt_1 = _chain(final_result=result([
        {"id": "twin-1", "settings": {}},
    ]))
    update_attempt_1 = _chain(final_exc=Exception(
        'duplicate key value violates unique constraint "idx_twins_handle_unique"'
    ))

    # Between attempt 1 and attempt 2: another twin claims "alice", AND a
    # concurrent bio-edit PATCH commits {"bio": "concurrent update"} onto
    # twin-1's own settings -- visible in this attempt's fresh all_twins read
    # but absent from the stale pre-loop twin_row_chain snapshot above.
    all_twins_attempt_2 = _chain(final_result=result([
        {"id": "twin-1", "settings": {"bio": "concurrent update"}},
        {"id": "twin-2", "settings": {"handle": "alice"}},
    ]))
    update_attempt_2 = _chain(final_result=result([{"id": "twin-1"}]))

    table_mock = MagicMock(side_effect=[
        twin_row_chain,
        all_twins_attempt_1,
        update_attempt_1,
        all_twins_attempt_2,
        update_attempt_2,
    ])

    with _RouterPatches(r, table_mock), patch.object(r.random, "randint", return_value=2):
        resp = await r.claim_handle(
            request=HandleClaimRequest(twin_id="twin-1", handle="Alice"),
            user=OWNER,
        )

    assert resp["handle"] == "alice-2"

    # The winning UPDATE call must carry forward the concurrently-written
    # "bio" field alongside the new handle -- not just {"handle": ...} built
    # from the stale, bio-less pre-loop snapshot.
    update_call_kwargs = update_attempt_2.update.call_args
    written_settings = update_call_kwargs.args[0]["settings"]
    assert written_settings == {"bio": "concurrent update", "handle": "alice-2"}
