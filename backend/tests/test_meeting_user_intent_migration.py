from __future__ import annotations
import re
from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "supabase" / "migrations"
    / "20260519000100_meeting_user_intent.sql"
)

def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")

def test_migration_exists() -> None:
    assert MIGRATION_PATH.exists()

def test_migration_adds_user_goal_and_user_context_idempotent() -> None:
    sql = _sql()
    assert "ALTER TABLE public.meetings" in sql
    assert re.search(r"ADD COLUMN IF NOT EXISTS user_goal\s+TEXT", sql, re.IGNORECASE)
    assert re.search(r"ADD COLUMN IF NOT EXISTS user_context\s+TEXT", sql, re.IGNORECASE)

def test_migration_is_additive() -> None:
    sql = _sql()
    assert "DROP COLUMN" not in sql
    assert "DROP TABLE" not in sql
    assert "CREATE TABLE" not in sql
