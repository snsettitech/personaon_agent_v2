"""Contract tests for the 20260520000100_meeting_brief.sql migration."""

from __future__ import annotations

import re
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260520000100_meeting_brief.sql"
)


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_exists() -> None:
    assert MIGRATION_PATH.exists(), (
        f"meeting brief migration must exist at {MIGRATION_PATH}"
    )


def test_migration_adds_brief_columns_idempotently() -> None:
    sql = _sql()
    assert "CREATE TABLE" not in sql, "migration must not recreate the meetings table"
    assert "DROP COLUMN" not in sql, "migration must not be destructive"
    assert "DROP TABLE" not in sql, "migration must not drop tables"
    assert "ALTER TABLE public.meetings" in sql, (
        "migration must use schema-qualified public.meetings"
    )

    for column in ("brief_json", "brief_generated_at"):
        assert re.search(
            rf"ADD COLUMN IF NOT EXISTS {column}\b",
            sql,
            flags=re.IGNORECASE,
        ), f"missing idempotent column add: {column}"


def test_brief_json_is_jsonb_and_generated_at_is_timestamptz() -> None:
    sql = _sql()
    assert re.search(r"brief_json\s+JSONB", sql, re.IGNORECASE), (
        "brief_json must be declared as JSONB"
    )
    assert re.search(r"brief_generated_at\s+TIMESTAMPTZ", sql, re.IGNORECASE), (
        "brief_generated_at must be declared as TIMESTAMPTZ"
    )


def test_partial_index_for_brief_pending_exists() -> None:
    sql = _sql()
    assert re.search(
        r"CREATE INDEX IF NOT EXISTS idx_meetings_brief_pending\s+"
        r"ON\s+(public\.)?meetings\s*\(\s*meeting_start\s*\)\s+"
        # now() is not IMMUTABLE so Postgres rejects it in an index predicate;
        # the audit hotfix (d26cbf5e) dropped it and the scheduler filters by
        # time at query time instead. Pin that the predicate stays now()-free.
        r"WHERE\s+brief_generated_at IS NULL\s*;",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    ), "partial index on meeting_start (brief pending) must exist with WHERE clause"
