from __future__ import annotations

import re
from pathlib import Path


MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "supabase"
    / "migrations"
    / "20260505010000_phase30_meeting_os_foundation.sql"
)


def _migration_sql() -> str:
    return MIGRATION_PATH.read_text(encoding="utf-8")


def test_meeting_os_migration_extends_existing_meetings_table() -> None:
    sql = _migration_sql()
    assert "CREATE TABLE IF NOT EXISTS public.meetings" not in sql
    assert "CREATE TABLE IF NOT EXISTS meetings" not in sql
    assert "ALTER TABLE public.meetings" in sql

    for column in (
        "mode",
        "capture_method",
        "provider_event_id",
        "privacy_level",
        "share_with_persona",
        "estimated_cost_cents",
    ):
        assert re.search(
            rf"ADD COLUMN IF NOT EXISTS {column}\b",
            sql,
            flags=re.IGNORECASE,
        ), f"missing idempotent meetings column: {column}"


def test_meeting_os_defaults_are_off_and_private() -> None:
    sql = _migration_sql()
    assert "ALTER COLUMN mode SET DEFAULT 'off'" in sql
    assert "ALTER COLUMN capture_method SET DEFAULT 'none'" in sql
    assert "ALTER COLUMN privacy_level SET DEFAULT 'private'" in sql
    assert "ALTER COLUMN share_with_persona SET DEFAULT false" in sql


def test_meeting_os_check_constraints_pin_modes_and_capture_methods() -> None:
    sql = _migration_sql()
    assert "meeting_os_meetings_mode_check" in sql
    assert "'off'" in sql
    assert "'note_taker'" in sql
    assert "'augmented'" in sql
    assert "'delegated'" in sql

    assert "meeting_os_meetings_capture_method_check" in sql
    assert "'google_meet_artifact'" in sql
    assert "'google_meet_media_api'" in sql
    assert "'recall_bot'" in sql


def test_meeting_os_schema_adds_first_class_rollup_tables() -> None:
    sql = _migration_sql()
    for table_name in ("contacts", "meeting_tasks", "meeting_costs_daily"):
        assert f"CREATE TABLE IF NOT EXISTS public.{table_name}" in sql
        assert f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY" in sql
        assert f"{table_name}_service_all" in sql


def test_meeting_os_owner_rls_uses_resolved_tenant() -> None:
    sql = _migration_sql()
    assert "tenant_id = auth.uid()" not in sql
    assert sql.count("SELECT tenant_id FROM public.users WHERE id = auth.uid()") >= 6

    for policy_name in (
        "contacts_owner_all",
        "meeting_tasks_owner_all",
        "meeting_costs_daily_owner_all",
    ):
        assert policy_name in sql


def test_meeting_os_replaces_legacy_meeting_owner_rls() -> None:
    sql = _migration_sql()
    assert "DROP POLICY IF EXISTS meetings_tenant_policy ON public.meetings" in sql
    assert "CREATE POLICY meetings_tenant_policy ON public.meetings" in sql
    assert (
        "DROP POLICY IF EXISTS meeting_participants_tenant_policy "
        "ON public.meeting_participants"
    ) in sql
    assert (
        "CREATE POLICY meeting_participants_tenant_policy "
        "ON public.meeting_participants"
    ) in sql
    assert "m.tenant_id = (SELECT tenant_id FROM public.users WHERE id = auth.uid())" in sql
    assert "WITH CHECK" in sql


def test_meeting_os_validates_new_table_twin_scope() -> None:
    sql = _migration_sql()
    assert "CREATE OR REPLACE FUNCTION public.validate_meeting_os_twin_scope()" in sql
    assert "SECURITY DEFINER" in sql
    assert "SET search_path = pg_catalog" in sql
    assert "t.id = NEW.twin_id" in sql
    assert "t.tenant_id = NEW.tenant_id" in sql

    for table_name, trigger_name in (
        ("contacts", "validate_contacts_twin_scope"),
        ("meeting_tasks", "validate_meeting_tasks_twin_scope"),
        ("meeting_costs_daily", "validate_meeting_costs_daily_twin_scope"),
    ):
        assert f"DROP TRIGGER IF EXISTS {trigger_name} ON public.{table_name}" in sql
        assert f"CREATE TRIGGER {trigger_name}" in sql
        assert f"ON public.{table_name}" in sql
        assert "BEFORE INSERT OR UPDATE OF tenant_id, twin_id" in sql
        assert "EXECUTE FUNCTION public.validate_meeting_os_twin_scope()" in sql


def test_meeting_os_provider_event_index_is_unique_and_null_safe() -> None:
    sql = _migration_sql()
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_meetings_provider_event_unique" in sql
    assert "COALESCE(provider_calendar_id, '')" in sql
    assert "COALESCE(provider_event_instance_id, '')" in sql
    assert "provider_event_id" in sql
    assert "WHERE provider IS NOT NULL AND provider_event_id IS NOT NULL" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_meetings_provider_event" not in sql


def test_meeting_tasks_scope_trigger_enforces_same_tenant_and_twin() -> None:
    sql = _migration_sql()
    assert "CREATE OR REPLACE FUNCTION public.validate_meeting_task_scope()" in sql
    assert "CREATE TRIGGER validate_meeting_tasks_scope" in sql
    assert "BEFORE INSERT OR UPDATE OF tenant_id, twin_id, meeting_id, contact_id" in sql
    assert "NEW.meeting_id" in sql
    assert "NEW.contact_id" in sql
    assert "m.tenant_id = NEW.tenant_id" in sql
    assert "m.twin_id = NEW.twin_id" in sql
    assert "c.tenant_id = NEW.tenant_id" in sql
    assert "c.twin_id = NEW.twin_id" in sql
    assert "RAISE EXCEPTION" in sql


def test_meeting_os_constants_match_database_contract() -> None:
    from modules import meeting_os

    assert meeting_os.DEFAULT_MEETING_MODE == "off"
    assert meeting_os.DEFAULT_MEETING_PRIVACY_LEVEL == "private"
    assert meeting_os.MEETING_MODES == (
        "off",
        "note_taker",
        "augmented",
        "delegated",
    )
    assert meeting_os.CAPTURE_METHODS == (
        "none",
        "google_meet_artifact",
        "google_meet_media_api",
        "recall_bot",
    )
    assert meeting_os.BOTLESS_CAPTURE_METHODS == frozenset(
        {"google_meet_artifact", "google_meet_media_api"}
    )
    assert meeting_os.BOT_BASED_MEETING_MODES == frozenset(
        {"augmented", "delegated"}
    )
