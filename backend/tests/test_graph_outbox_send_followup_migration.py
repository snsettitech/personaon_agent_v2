"""Contract tests for the send_followup_draft graph_outbox migration."""
from __future__ import annotations

from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260619000100_graph_outbox_ops_send_followup.sql"
)


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_exists() -> None:
    assert MIGRATION_PATH.exists(), (
        f"send_followup_draft migration must exist at {MIGRATION_PATH}"
    )


def test_migration_drops_old_constraint_first() -> None:
    sql = _sql()
    drop_pos = sql.find("DROP CONSTRAINT IF EXISTS graph_outbox_operation_check")
    add_pos = sql.find("ADD CONSTRAINT graph_outbox_operation_check")
    assert drop_pos != -1, "must DROP the old constraint"
    assert add_pos != -1, "must ADD the new constraint"
    assert drop_pos < add_pos, "DROP must come before ADD per migration linter"


def test_migration_includes_send_followup_draft() -> None:
    assert "'send_followup_draft'" in _sql()


def test_migration_preserves_existing_operations() -> None:
    """The new constraint must still allow every prior operation (superset)."""
    sql = _sql()
    required_ops = (
        "create_episode",
        "create_claims",
        "persona_research",
        "firecrawl_extract",
        "schedule_meeting_bot",
        "process_meeting_transcript",
        "generate_meeting_summary",
        "send_action_item_reminder",
        "send_lifecycle_email",
        "recall_calendar_sync",
        "recap_timeout_check",
        "stripe_meter_event",
        # legacy retained
        "post_meeting_followup",
        "weekly_digest",
    )
    for op in required_ops:
        assert f"'{op}'" in sql, f"operation {op!r} must remain allowed"


def test_migration_targets_graph_outbox_table() -> None:
    sql = _sql()
    assert "graph_outbox" in sql
    assert "DROP TABLE" not in sql
    assert "DROP COLUMN" not in sql
