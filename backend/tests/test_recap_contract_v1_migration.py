from __future__ import annotations

import re
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260519000000_recap_contract_v1.sql"
)


_RECAP_CONTRACT_COLUMNS: tuple[str, ...] = (
    "recap",
    "intent_vs_outcome",
    "action_items",
    "commitments",
    "decisions",
    "topics",
    "unanswered_questions",
    "people_observed",
    "my_positions",
    "style_sample",
    "recap_version",
    "recap_corrected_at",
)


_JSONB_ARRAY_COLUMNS: tuple[str, ...] = (
    "action_items",
    "commitments",
    "decisions",
    "topics",
    "unanswered_questions",
    "people_observed",
    "my_positions",
)


def _migration_sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_file_exists() -> None:
    assert MIGRATION_PATH.exists(), (
        f"recap contract migration must exist at {MIGRATION_PATH}"
    )


def test_migration_extends_meetings_with_recap_contract_columns() -> None:
    sql = _migration_sql()
    assert "CREATE TABLE IF NOT EXISTS public.meetings" not in sql, "migration must not recreate meetings"
    assert "CREATE TABLE IF NOT EXISTS meetings" not in sql, "migration must not recreate meetings"
    assert "DROP COLUMN" not in sql, "migration must not be destructive"
    assert "DROP TABLE" not in sql, "migration must not drop tables"
    assert "ALTER TABLE public.meetings" in sql, (
        "migration must use schema-qualified public.meetings to match Phase 30 convention"
    )

    for column in _RECAP_CONTRACT_COLUMNS:
        assert re.search(
            rf"ADD COLUMN IF NOT EXISTS {column}\b",
            sql,
            flags=re.IGNORECASE,
        ), f"missing idempotent recap column: {column}"


def test_jsonb_arrays_default_to_empty_array() -> None:
    sql = _migration_sql()
    for column in _JSONB_ARRAY_COLUMNS:
        assert re.search(
            rf"{column}\s+JSONB\s+DEFAULT\s+'\[\]'::jsonb",
            sql,
            flags=re.IGNORECASE,
        ), f"{column} should default to empty JSONB array"


def test_recap_version_defaults_to_one() -> None:
    sql = _migration_sql()
    assert re.search(
        r"recap_version\s+INT\s+DEFAULT\s+1",
        sql,
        flags=re.IGNORECASE,
    ), "recap_version must default to 1"


def test_partial_index_on_recap_corrected_at() -> None:
    sql = _migration_sql()
    assert re.search(
        r"CREATE INDEX IF NOT EXISTS idx_meetings_recap_corrected\s+"
        r"ON\s+(public\.)?meetings\s*\(\s*recap_corrected_at\s*\)\s+"
        r"WHERE\s+recap_corrected_at IS NOT NULL",
        sql,
        flags=re.IGNORECASE | re.DOTALL,
    ), "partial index on recap_corrected_at must exist with WHERE clause"


def test_intent_vs_outcome_is_nullable_jsonb_without_default() -> None:
    sql = _migration_sql()
    # JSONB column WITHOUT a DEFAULT — nullable until recap engine writes
    assert re.search(
        r"intent_vs_outcome\s+JSONB,", sql, re.IGNORECASE
    ), "intent_vs_outcome must be plain JSONB (no default; nullable)"


def test_text_columns_declared_as_text() -> None:
    sql = _migration_sql()
    for col in ("recap", "style_sample"):
        assert re.search(
            rf"{col}\s+TEXT\b", sql, re.IGNORECASE
        ), f"{col} must be declared as TEXT"
