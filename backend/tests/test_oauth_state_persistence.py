"""Tests for the Supabase-backed OAuth state store.

Verifies _save_oauth_state / _pop_oauth_state round-trip through a mocked
Supabase client, and that the "pop" is single-use (a second pop returns
None). Also covers the local-dev fallback when the DB is unreachable.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest


class _FakeDeleteResp:
    def __init__(self, data: list[dict[str, Any]]):
        self.data = data


class _FakeOAuthStatesTable:
    """Hand-rolled fluent mock that emulates a single PostgREST table.

    Records inserts/deletes in lists so tests can assert on payloads. Models
    a tiny key->row store keyed by ``state`` so the round-trip behaves like
    a real DB call.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.inserts: list[dict[str, Any]] = []
        self.deletes: list[str] = []
        self._pending_op: str | None = None
        self._pending_filter_state: str | None = None
        self._pending_filter_expires_gte: bool = False
        self._pending_filter_expires_lt: bool = False

    def _reset_pending(self) -> None:
        self._pending_op = None
        self._pending_filter_state = None
        self._pending_filter_expires_gte = False
        self._pending_filter_expires_lt = False

    def insert(self, payload: dict[str, Any]) -> "_FakeOAuthStatesTable":
        self._pending_op = "insert"
        self.inserts.append(payload)
        # Store the row under its state key for later pop.
        self.rows[payload["state"]] = dict(payload)
        return self

    def delete(self) -> "_FakeOAuthStatesTable":
        self._pending_op = "delete"
        return self

    def eq(self, column: str, value: Any) -> "_FakeOAuthStatesTable":
        if column == "state":
            self._pending_filter_state = value
        return self

    def gte(self, column: str, _value: Any) -> "_FakeOAuthStatesTable":
        if column == "expires_at":
            self._pending_filter_expires_gte = True
        return self

    def lt(self, column: str, _value: Any) -> "_FakeOAuthStatesTable":
        if column == "expires_at":
            self._pending_filter_expires_lt = True
        return self

    def execute(self) -> _FakeDeleteResp:
        op = self._pending_op
        state_filter = self._pending_filter_state
        is_sweep = self._pending_filter_expires_lt
        self._reset_pending()

        if op == "insert":
            return _FakeDeleteResp([])
        if op == "delete":
            if is_sweep:
                # Sweep: best-effort cleanup of expired rows; tests don't
                # need to model expiration so this is a no-op delete.
                return _FakeDeleteResp([])
            if state_filter is not None:
                row = self.rows.pop(state_filter, None)
                if row is not None:
                    self.deletes.append(state_filter)
                    return _FakeDeleteResp([row])
                return _FakeDeleteResp([])
        return _FakeDeleteResp([])


def _make_mock_supabase(table: _FakeOAuthStatesTable) -> MagicMock:
    sb = MagicMock()
    sb.table.return_value = table
    return sb


def test_save_then_pop_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """_save_oauth_state writes; _pop_oauth_state returns the same payload."""
    table = _FakeOAuthStatesTable()
    mock_sb = _make_mock_supabase(table)

    with patch(
        "routers.calendar_booking.get_supabase_client",
        return_value=mock_sb,
    ):
        from routers.calendar_booking import _pop_oauth_state, _save_oauth_state

        payload = {
            "twin_id": "twin-abc",
            "user_id": "user-123",
            "provider": "google",
        }
        _save_oauth_state("state-token-xyz", payload)

        # Insert happened with the right shape.
        assert len(table.inserts) == 1
        inserted = table.inserts[0]
        assert inserted["state"] == "state-token-xyz"
        assert inserted["provider"] == "google"
        assert inserted["tenant_id"] == "user-123"
        assert inserted["payload"] == payload
        assert "expires_at" in inserted
        assert "created_at" in inserted

        # Pop returns the original payload.
        result = _pop_oauth_state("state-token-xyz")
        assert result == payload


def test_pop_is_single_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """A second _pop_oauth_state for the same state returns None."""
    table = _FakeOAuthStatesTable()
    mock_sb = _make_mock_supabase(table)

    with patch(
        "routers.calendar_booking.get_supabase_client",
        return_value=mock_sb,
    ):
        from routers.calendar_booking import _pop_oauth_state, _save_oauth_state

        _save_oauth_state(
            "single-use-state",
            {"twin_id": "t1", "user_id": "u1", "provider": "microsoft"},
        )

        first = _pop_oauth_state("single-use-state")
        assert first is not None
        assert first["twin_id"] == "t1"

        # Second pop must return None — the row was deleted in the first call.
        second = _pop_oauth_state("single-use-state")
        assert second is None


def test_pop_unknown_state_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """Popping a state that was never saved returns None."""
    table = _FakeOAuthStatesTable()
    mock_sb = _make_mock_supabase(table)

    with patch(
        "routers.calendar_booking.get_supabase_client",
        return_value=mock_sb,
    ):
        from routers.calendar_booking import _pop_oauth_state

        # In-memory fallback dict is also empty (module-level _oauth_states
        # may have residue from earlier tests; the unknown key is fresh).
        result = _pop_oauth_state("never-saved-state-uniq")
        assert result is None


def test_save_falls_back_to_in_memory_when_db_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When get_supabase_client raises, state still saves to the in-memory dict."""
    # Reset the in-memory dict to avoid cross-test pollution.
    from routers import calendar_booking

    calendar_booking._oauth_states.clear()

    with patch(
        "routers.calendar_booking.get_supabase_client",
        side_effect=RuntimeError("supabase not configured"),
    ):
        calendar_booking._save_oauth_state(
            "local-dev-state",
            {"twin_id": "t1", "user_id": "u1", "provider": "google"},
        )

        # Fallback path: state ended up in the in-memory dict.
        assert "local-dev-state" in calendar_booking._oauth_states

        # Pop on the same path returns the payload.
        result = calendar_booking._pop_oauth_state("local-dev-state")
        assert result is not None
        assert result["twin_id"] == "t1"

        # Single-use semantics hold in the fallback too.
        assert calendar_booking._pop_oauth_state("local-dev-state") is None


def test_save_falls_back_when_db_insert_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the insert .execute() raises, _save_oauth_state still writes the in-memory entry."""
    from routers import calendar_booking

    calendar_booking._oauth_states.clear()

    # Build a table whose insert chain raises on execute().
    failing_table = MagicMock()
    insert_chain = MagicMock()
    insert_chain.execute.side_effect = RuntimeError("DB unreachable")
    failing_table.insert.return_value = insert_chain
    failing_table.delete.return_value.lt.return_value.execute.return_value = _FakeDeleteResp([])

    failing_sb = MagicMock()
    failing_sb.table.return_value = failing_table

    with patch(
        "routers.calendar_booking.get_supabase_client",
        return_value=failing_sb,
    ):
        calendar_booking._save_oauth_state(
            "fallback-state",
            {"twin_id": "t1", "user_id": "u1", "provider": "google"},
        )

    # Insert was attempted on the DB once, then we fell back to memory.
    failing_table.insert.assert_called_once()
    assert "fallback-state" in calendar_booking._oauth_states
