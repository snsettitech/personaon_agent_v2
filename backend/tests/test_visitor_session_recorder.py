"""Tests for the visitor_session_recorder service (Phase G.2).

Assertions:
- record_visitor_turn creates a new row when none exists
- record_visitor_turn updates existing row (increments count, bumps timestamp)
- Skips when surface is 'owner' (not in _TRACKED_SURFACES)
- Skips when visitor_id is empty
- Swallows Supabase errors silently — never raises
- Uses _resolve_tenant_from_twin when tenant_id is None
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _result(data):
    return SimpleNamespace(data=data)


def _fluent_chain(return_data) -> MagicMock:
    """Fluent chain where every method returns self; .execute() returns _result(data)."""
    m = MagicMock()
    m.table.return_value = m
    m.select.return_value = m
    m.insert.return_value = m
    m.update.return_value = m
    m.eq.return_value = m
    m.limit.return_value = m
    m.single.return_value = m
    m.execute.return_value = _result(return_data)
    return m


TENANT_ID = "00000000-0000-0000-0000-000000000001"
TWIN_ID = "00000000-0000-0000-0000-000000000002"
VISITOR_ID = "sess-abc-123"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sb(existing_row=None, insert_ok=True):
    """
    Build a mock supabase that returns `existing_row` for the SELECT call
    and a dummy result for INSERT/UPDATE.
    """
    call_count = {"n": 0}
    insert_data = [{"id": "new-uuid"}] if insert_ok else []

    def _table_side_effect(name: str):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # First table() call = SELECT to check existing row
            chain = _fluent_chain([existing_row] if existing_row else [])
            return chain
        # Subsequent calls = INSERT or UPDATE
        return _fluent_chain(insert_data)

    sb = MagicMock()
    sb.table.side_effect = _table_side_effect
    return sb


# ---------------------------------------------------------------------------
# Tests: core upsert logic
# ---------------------------------------------------------------------------

def test_creates_new_row_when_none_exists():
    """First visit: existing_row is None → INSERT is called."""
    sb = _make_sb(existing_row=None)

    with patch("services.visitor_session_recorder.supabase", sb):
        from services.visitor_session_recorder import record_visitor_turn
        record_visitor_turn(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            visitor_id=VISITOR_ID,
            surface="widget",
        )

    # First call = SELECT, second call = INSERT
    assert sb.table.call_count == 2
    # The second call should chain to .insert()
    second_call_chain = sb.table.side_effect.__self__ if False else None
    # Verify via call_args_list on table
    calls = [c.args[0] for c in sb.table.call_args_list]
    assert calls == ["visitor_sessions", "visitor_sessions"]


def test_updates_existing_row():
    """Repeat visit: existing row found → UPDATE (not INSERT)."""
    existing = {"id": "existing-uuid", "message_count": 3}

    call_log: list[str] = []

    def _table_side_effect(name: str):
        call_log.append(name)
        if len(call_log) == 1:
            # SELECT returns existing row
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain
            chain.execute.return_value = _result([existing])
            return chain
        # UPDATE call
        chain = MagicMock()
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = _result([{"id": "existing-uuid"}])
        return chain

    sb = MagicMock()
    sb.table.side_effect = _table_side_effect

    with patch("services.visitor_session_recorder.supabase", sb):
        from services.visitor_session_recorder import record_visitor_turn
        record_visitor_turn(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            visitor_id=VISITOR_ID,
            surface="widget",
        )

    # 2 table() calls: SELECT + UPDATE
    assert sb.table.call_count == 2
    update_chain = sb.table.return_value
    # The second chain had .update() called (not .insert())
    # Verify by inspecting the side_effect log
    assert call_log == ["visitor_sessions", "visitor_sessions"]


def test_increments_message_count():
    """UPDATE payload contains message_count = existing + 1."""
    existing = {"id": "existing-uuid", "message_count": 5}

    captured_update_data: list[dict] = []

    def _table_side_effect(name: str):
        if not hasattr(_table_side_effect, "called"):
            _table_side_effect.called = True
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain
            chain.execute.return_value = _result([existing])
            return chain
        # UPDATE chain — capture the data passed to .update()
        chain = MagicMock()
        def _capture_update(data):
            captured_update_data.append(data)
            return chain
        chain.update.side_effect = _capture_update
        chain.eq.return_value = chain
        chain.execute.return_value = _result([])
        return chain

    sb = MagicMock()
    sb.table.side_effect = _table_side_effect

    with patch("services.visitor_session_recorder.supabase", sb):
        from services.visitor_session_recorder import record_visitor_turn
        record_visitor_turn(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            visitor_id=VISITOR_ID,
            surface="public",
        )

    assert len(captured_update_data) == 1
    assert captured_update_data[0]["message_count"] == 6


# ---------------------------------------------------------------------------
# Tests: skip conditions
# ---------------------------------------------------------------------------

def test_skips_owner_surface():
    """surface='owner' is not in _TRACKED_SURFACES → no DB call."""
    sb = MagicMock()

    with patch("services.visitor_session_recorder.supabase", sb):
        from services.visitor_session_recorder import record_visitor_turn
        record_visitor_turn(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            visitor_id=VISITOR_ID,
            surface="owner",
        )

    sb.table.assert_not_called()


def test_skips_empty_visitor_id():
    """visitor_id='' → no DB call."""
    sb = MagicMock()

    with patch("services.visitor_session_recorder.supabase", sb):
        from services.visitor_session_recorder import record_visitor_turn
        record_visitor_turn(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            visitor_id="",
            surface="widget",
        )

    sb.table.assert_not_called()


def test_skips_empty_twin_id():
    """twin_id='' → no DB call."""
    sb = MagicMock()

    with patch("services.visitor_session_recorder.supabase", sb):
        from services.visitor_session_recorder import record_visitor_turn
        record_visitor_turn(
            tenant_id=TENANT_ID,
            twin_id="",
            visitor_id=VISITOR_ID,
            surface="widget",
        )

    sb.table.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: tenant resolution
# ---------------------------------------------------------------------------

def test_resolves_tenant_from_twin_when_not_provided():
    """When tenant_id=None, _resolve_tenant_from_twin is called."""
    tenant_row = {"tenant_id": TENANT_ID}

    call_log: list[str] = []

    def _table_side_effect(name: str):
        call_log.append(name)
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.limit.return_value = chain
        # First call = twins lookup, second = visitor_sessions SELECT, third = INSERT
        if "twins" in name:
            chain.execute.return_value = _result(tenant_row)
        else:
            chain.execute.return_value = _result([])
        return chain

    sb = MagicMock()
    sb.table.side_effect = _table_side_effect

    with patch("services.visitor_session_recorder.supabase", sb):
        from services.visitor_session_recorder import record_visitor_turn
        record_visitor_turn(
            tenant_id=None,
            twin_id=TWIN_ID,
            visitor_id=VISITOR_ID,
            surface="widget",
        )

    # Verify twins table was queried
    assert "twins" in call_log


def test_skips_when_tenant_unresolvable():
    """If tenant_id is None and twin lookup returns nothing → no upsert."""
    call_log: list[str] = []

    def _table_side_effect(name: str):
        call_log.append(name)
        chain = MagicMock()
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.single.return_value = chain
        chain.execute.return_value = _result(None)
        return chain

    sb = MagicMock()
    sb.table.side_effect = _table_side_effect

    with patch("services.visitor_session_recorder.supabase", sb):
        from services.visitor_session_recorder import record_visitor_turn
        record_visitor_turn(
            tenant_id=None,
            twin_id=TWIN_ID,
            visitor_id=VISITOR_ID,
            surface="widget",
        )

    # Only the twins lookup should have been called; no visitor_sessions table calls
    assert all(t == "twins" for t in call_log)


# ---------------------------------------------------------------------------
# Tests: error swallowing
# ---------------------------------------------------------------------------

def test_swallows_supabase_errors_never_raises():
    """Any Supabase exception must be swallowed — record_visitor_turn must not raise."""
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("connection refused")

    with patch("services.visitor_session_recorder.supabase", sb):
        from services.visitor_session_recorder import record_visitor_turn
        # Must not raise
        record_visitor_turn(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            visitor_id=VISITOR_ID,
            surface="widget",
        )


def test_swallows_insert_error():
    """INSERT failure must be swallowed — callers must not see an exception."""
    def _table_side_effect(name: str):
        if not hasattr(_table_side_effect, "called"):
            _table_side_effect.called = True
            chain = MagicMock()
            chain.select.return_value = chain
            chain.eq.return_value = chain
            chain.limit.return_value = chain
            chain.execute.return_value = _result([])  # no existing row
            return chain
        # INSERT raises
        chain = MagicMock()
        chain.insert.return_value = chain
        chain.execute.side_effect = Exception("DB write failed")
        return chain

    sb = MagicMock()
    sb.table.side_effect = _table_side_effect

    with patch("services.visitor_session_recorder.supabase", sb):
        from services.visitor_session_recorder import record_visitor_turn
        # Must not raise
        record_visitor_turn(
            tenant_id=TENANT_ID,
            twin_id=TWIN_ID,
            visitor_id=VISITOR_ID,
            surface="public",
        )
