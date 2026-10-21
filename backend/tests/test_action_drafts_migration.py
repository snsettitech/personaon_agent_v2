"""Contract tests for the action_drafts tenant-scope migration."""
from __future__ import annotations

from pathlib import Path

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260619000000_action_drafts_tenant_scope.sql"
)


def _sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_migration_exists() -> None:
    assert MIGRATION_PATH.exists(), (
        f"action_drafts tenant-scope migration must exist at {MIGRATION_PATH}"
    )


def test_migration_targets_action_drafts() -> None:
    assert "public.action_drafts" in _sql()


def test_migration_creates_table_when_absent() -> None:
    """The legacy phase8 table never reached every environment (e.g. staging),
    so the migration must CREATE action_drafts where it is absent and remain a
    no-op (CREATE/ADD ... IF NOT EXISTS) where it already exists."""
    sql = _sql()
    assert "CREATE TABLE IF NOT EXISTS public.action_drafts" in sql


def test_migration_adds_tenant_id() -> None:
    assert "ADD COLUMN IF NOT EXISTS tenant_id uuid" in _sql()


def test_migration_backfills_tenant_from_twins() -> None:
    sql = _sql()
    assert "UPDATE public.action_drafts" in sql
    assert "public.twins" in sql


def test_migration_sets_tenant_not_null() -> None:
    assert "ALTER COLUMN tenant_id SET NOT NULL" in _sql()


def test_migration_drops_open_policy() -> None:
    assert "DROP POLICY IF EXISTS drafts_all_access" in _sql()


def test_migration_adds_owner_rls() -> None:
    """Owner read + update policies scoped to tenant_id."""
    sql = _sql()
    assert "(SELECT auth.uid()) = tenant_id" in sql
    assert "adraft_owner_read" in sql
    assert "adraft_owner_update" in sql


def test_migration_adds_service_role_policy() -> None:
    sql = _sql()
    assert "auth.role() = 'service_role'" in sql
    assert "adraft_service_all" in sql


def test_migration_non_destructive() -> None:
    sql = _sql()
    assert "DROP TABLE" not in sql, "migration must not drop tables"
    assert "DROP COLUMN" not in sql, "migration must not drop columns"
