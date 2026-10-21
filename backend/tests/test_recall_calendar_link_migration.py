"""Contract tests for the recall_calendar_id migration on tool_connectors.

Task P1.1.B introduces a column linking Google/Outlook calendar connectors to
their Recall.ai Calendar V2 registration, so we can disconnect them cleanly
when the user revokes calendar access.

The migration must be:
  - additive (no DROP/CREATE TABLE)
  - idempotent (ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS)
  - schema-qualified (public.tool_connectors)
  - paired with a partial index so lookups by recall_calendar_id stay cheap
"""

from __future__ import annotations

import re
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260519000200_recall_calendar_link.sql"
)


def _migration_sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_exists() -> None:
    assert MIGRATION_PATH.exists(), (
        f"recall_calendar_link migration must exist at {MIGRATION_PATH}"
    )


def test_migration_adds_recall_calendar_id_idempotent() -> None:
    sql = _migration_sql()
    assert "ALTER TABLE public.tool_connectors" in sql, (
        "migration must use schema-qualified public.tool_connectors"
    )
    assert re.search(
        r"ADD COLUMN IF NOT EXISTS recall_calendar_id\s+TEXT",
        sql,
        re.IGNORECASE,
    ), "recall_calendar_id TEXT column must be added idempotently"


def test_migration_adds_partial_index() -> None:
    sql = _migration_sql()
    assert re.search(
        r"CREATE INDEX IF NOT EXISTS idx_tool_connectors_recall_cal\s+"
        r"ON\s+(public\.)?tool_connectors\(\s*recall_calendar_id\s*\)\s+"
        r"WHERE\s+recall_calendar_id IS NOT NULL",
        sql,
        re.IGNORECASE | re.DOTALL,
    ), "partial index on recall_calendar_id must exist with WHERE clause"


def test_migration_is_additive() -> None:
    sql = _migration_sql()
    assert "DROP COLUMN" not in sql, "migration must not drop columns"
    assert "DROP TABLE" not in sql, "migration must not drop tables"
    assert "CREATE TABLE" not in sql, "migration must not recreate the table"
