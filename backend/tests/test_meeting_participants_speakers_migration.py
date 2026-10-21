"""Contract tests for the meeting_participants speakers migration (P1.3.A)."""
from __future__ import annotations

import re
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260520000000_meeting_participants_speakers.sql"
)


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_exists() -> None:
    assert MIGRATION_PATH.exists(), (
        f"meeting_participants speakers migration must exist at {MIGRATION_PATH}"
    )


def test_migration_alters_meeting_participants() -> None:
    sql = _sql()
    assert "ALTER TABLE public.meeting_participants" in sql, (
        "migration must target public.meeting_participants"
    )


def test_migration_adds_diarization_label_column() -> None:
    sql = _sql()
    assert re.search(
        r"ADD COLUMN IF NOT EXISTS diarization_label\s+TEXT",
        sql,
        re.IGNORECASE,
    ), "must add diarization_label TEXT column idempotently"


def test_migration_adds_person_node_id_column() -> None:
    sql = _sql()
    assert re.search(
        r"ADD COLUMN IF NOT EXISTS person_node_id\s+UUID",
        sql,
        re.IGNORECASE,
    ), "must add person_node_id UUID column idempotently"


def test_migration_adds_diarization_partial_index() -> None:
    sql = _sql()
    assert "idx_meeting_participants_diarization" in sql, (
        "must create idx_meeting_participants_diarization"
    )
    # Partial index: WHERE diarization_label IS NOT NULL
    assert re.search(
        r"idx_meeting_participants_diarization[\s\S]*WHERE\s+diarization_label\s+IS\s+NOT\s+NULL",
        sql,
        re.IGNORECASE,
    ), "diarization index must be partial (WHERE diarization_label IS NOT NULL)"


def test_migration_adds_node_partial_index() -> None:
    sql = _sql()
    assert "idx_meeting_participants_node" in sql, (
        "must create idx_meeting_participants_node"
    )
    assert re.search(
        r"idx_meeting_participants_node[\s\S]*WHERE\s+person_node_id\s+IS\s+NOT\s+NULL",
        sql,
        re.IGNORECASE,
    ), "node index must be partial (WHERE person_node_id IS NOT NULL)"


def test_migration_is_additive_only() -> None:
    sql = _sql()
    assert "DROP COLUMN" not in sql, "migration must be additive (no DROP COLUMN)"
    assert "DROP TABLE" not in sql, "migration must not drop tables"
    assert "DROP INDEX" not in sql, "migration must not drop indexes"
