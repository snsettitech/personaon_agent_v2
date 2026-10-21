"""Contract tests for the resolve_meeting_speakers graph_outbox migration."""
from __future__ import annotations

from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260520000300_graph_outbox_resolve_speakers.sql"
)


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_exists() -> None:
    assert MIGRATION_PATH.exists(), (
        f"resolve_meeting_speakers migration must exist at {MIGRATION_PATH}"
    )


def test_migration_drops_old_constraint_first() -> None:
    sql = _sql()
    drop_pos = sql.find("DROP CONSTRAINT IF EXISTS graph_outbox_operation_check")
    add_pos = sql.find("ADD CONSTRAINT graph_outbox_operation_check")
    assert drop_pos != -1, "must DROP the old constraint"
    assert add_pos != -1, "must ADD the new constraint"
    assert drop_pos < add_pos, "DROP must come before ADD per migration linter"


def test_migration_includes_resolve_meeting_speakers() -> None:
    sql = _sql()
    assert "'resolve_meeting_speakers'" in sql, (
        "migration must add 'resolve_meeting_speakers' to graph_outbox_operation_check"
    )


def test_migration_preserves_existing_operations() -> None:
    """All previously allowed operations must remain in the CHECK constraint."""
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
        # Phase 30-D
        "recall_calendar_sync",
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
