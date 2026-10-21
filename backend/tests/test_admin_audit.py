"""Tests for modules/admin_audit.py — best-effort audit logging."""
from __future__ import annotations

from unittest.mock import MagicMock

import modules.admin_audit as aa


def test_record_admin_action_inserts_row(monkeypatch) -> None:
    captured: dict = {}
    table = MagicMock()

    def _insert(row):
        captured["row"] = row
        return table

    table.insert.side_effect = _insert
    table.execute.return_value = MagicMock()
    sb = MagicMock()
    sb.table.return_value = table
    monkeypatch.setattr(aa, "get_supabase_client", lambda: sb)

    ok = aa.record_admin_action(
        actor={"user_id": "u1", "email": "a@personaon.com", "tenant_id": "u1"},
        action=aa.ACTION_PLAN_CHANGED,
        target_type="user",
        target_id="u2",
        before={"plan": "free"},
        after={"plan": "business"},
    )

    assert ok is True
    row = captured["row"]
    assert row["actor_id"] == "u1"
    assert row["action"] == "user_plan_changed"
    assert row["target_type"] == "user"
    assert row["target_id"] == "u2"
    assert row["after"] == {"plan": "business"}


def test_record_admin_action_never_raises(monkeypatch) -> None:
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(aa, "get_supabase_client", _boom)
    ok = aa.record_admin_action(actor={"user_id": "u1"}, action=aa.ACTION_USER_DELETED)
    assert ok is False
