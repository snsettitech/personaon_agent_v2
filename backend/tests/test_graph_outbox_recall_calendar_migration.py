"""Contract tests for the recall_calendar_sync graph_outbox migration."""
from __future__ import annotations

from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260519000300_graph_outbox_recall_calendar_sync.sql"
)


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_exists() -> None:
    assert MIGRATION_PATH.exists(), (
        f"recall_calendar_sync migration must exist at {MIGRATION_PATH}"
    )


def test_migration_drops_old_constraint_first() -> None:
    sql = _sql()
    drop_pos = sql.find("DROP CONSTRAINT IF EXISTS graph_outbox_operation_check")
    add_pos = sql.find("ADD CONSTRAINT graph_outbox_operation_check")
    assert drop_pos != -1, "must DROP the old constraint"
    assert add_pos != -1, "must ADD the new constraint"
    assert drop_pos < add_pos, "DROP must come before ADD per migration linter"


def test_migration_includes_recall_calendar_sync() -> None:
    sql = _sql()
    assert "'recall_calendar_sync'" in sql, (
        "migration must add 'recall_calendar_sync' to graph_outbox_operation_check"
    )


def test_migration_preserves_existing_operations() -> None:
    """Spot-check that the new constraint still allows all existing operations."""
    sql = _sql()
    required_ops = (
        # Core graph ops
        "create_episode",
        "create_claims",
        "update_claim_status",
        "create_relationship",
        "delete_twin_graph",
        "extract_claims",
        "evaluate_contradictions",
        "refresh_snapshot",
        # Background / enrichment
        "persona_research",
        "firecrawl_extract",
        "enrich_from_web",
        # Meeting pipeline
        "schedule_meeting_bot",
        "process_meeting_transcript",
        "generate_meeting_summary",
        "warm_meeting_cache",
        "index_meeting_transcript",
        "generate_meeting_briefing",
        "generate_meeting_followup",
        "generate_weekly_digest",
        "enrich_twin_responses",
        "prep_meeting_context",
        # Billing + lifecycle
        "stripe_meter_event",
        "send_lifecycle_email",
    )
    for op in required_ops:
        assert f"'{op}'" in sql, (
            f"operation {op!r} must remain allowed after this migration"
        )


def test_migration_targets_graph_outbox_table() -> None:
    sql = _sql()
    assert "graph_outbox" in sql, "migration must target the graph_outbox table"
    assert "DROP TABLE" not in sql, "migration must not drop tables"
    assert "DROP COLUMN" not in sql, "migration must not be destructive"
