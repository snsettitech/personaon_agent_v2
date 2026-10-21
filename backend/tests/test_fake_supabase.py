"""Tests for the schema-aware FakeSupabase test helper.

These tests prove that the helper catches the exact bug class that hit
production: a unit test that mocks a column name which does not exist on
the real schema. With this helper, that test would fail at setup time.
"""
from __future__ import annotations

import pytest

from tests._fake_supabase import (
    FakeSupabase,
    FakeSupabaseSchemaError,
    Postgres42703Error,
    PRODUCTION_SCHEMA,
)


# ---------------------------------------------------------------------------
# The original bug: would the helper have caught it?
# ---------------------------------------------------------------------------


def test_set_row_with_user_id_on_twins_raises() -> None:
    """Regression: the original test_quota.py mocked twins with a user_id
    field. That column does not exist on production. The helper must reject
    this at setup time so the test never gets to lie about column shape."""
    sb = FakeSupabase()

    with pytest.raises(FakeSupabaseSchemaError) as excinfo:
        sb.table("twins").set_row(id="t1", user_id="u1")

    assert "user_id" in str(excinfo.value)
    assert "twins" in str(excinfo.value)


def test_select_user_id_from_twins_raises_42703() -> None:
    """Regression: the production code did ``select('user_id')`` against a
    schema that has no such column, and Supabase raised 42703. The helper
    must mimic that behavior so the same SQL fails in tests too."""
    sb = FakeSupabase()
    sb.table("twins").set_row(id="t1", settings={"owner_user_id": "u1"})

    with pytest.raises(Postgres42703Error) as excinfo:
        sb.table("twins").select("user_id").eq("id", "t1").single().execute()

    assert "twins.user_id does not exist" in str(excinfo.value)


def test_eq_filter_on_unknown_column_raises_42703() -> None:
    """Filtering on a non-existent column should also raise — that matches
    real Supabase behavior and catches typos in WHERE clauses."""
    sb = FakeSupabase()
    sb.table("users").set_row(id="u1", email="a@b.com", plan="pro")

    with pytest.raises(Postgres42703Error):
        # 'username' isn't a real column on users
        sb.table("users").select("id").eq("username", "alice").execute()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_select_with_valid_columns_returns_projected_row() -> None:
    sb = FakeSupabase()
    sb.table("twins").set_row(
        id="t1",
        name="Test",
        settings={"owner_user_id": "u1"},
        status="active",
    )

    result = sb.table("twins").select("id,settings").eq("id", "t1").single().execute()

    assert result.data == {"id": "t1", "settings": {"owner_user_id": "u1"}}


def test_select_star_returns_all_fields() -> None:
    sb = FakeSupabase()
    sb.table("users").set_row(id="u1", email="a@b.com", plan="pro")

    result = sb.table("users").select("*").eq("id", "u1").single().execute()

    assert result.data == {"id": "u1", "email": "a@b.com", "plan": "pro"}


def test_maybe_single_missing_row_returns_none() -> None:
    """maybe_single() on no-match returns ``data=None`` (matches real client)."""
    sb = FakeSupabase()
    # No rows added

    result = sb.table("users").select("id").eq("id", "ghost").maybe_single().execute()

    assert result.data is None


def test_eq_filter_filters_rows() -> None:
    sb = FakeSupabase()
    sb.table("users").set_row(id="u1", email="a@b.com", plan="free")
    sb.table("users").set_row(id="u2", email="c@d.com", plan="pro")

    result = sb.table("users").select("id,plan").eq("plan", "pro").execute()

    assert result.data == [{"id": "u2", "plan": "pro"}]


def test_neq_and_in_filters_compose() -> None:
    sb = FakeSupabase()
    sb.table("users").set_row(id="u1", plan="free")
    sb.table("users").set_row(id="u2", plan="pro")
    sb.table("users").set_row(id="u3", plan="believer")

    result = (
        sb.table("users")
        .select("id,plan")
        .neq("plan", "free")
        .in_("plan", ["pro", "believer"])
        .execute()
    )

    ids = sorted(r["id"] for r in result.data)
    assert ids == ["u2", "u3"]


# ---------------------------------------------------------------------------
# Updates / inserts (accepted silently — tests that check writes can use a
# spy fixture instead of relying on this helper)
# ---------------------------------------------------------------------------


def test_update_does_not_raise_for_valid_table() -> None:
    sb = FakeSupabase()
    # Updates should be accepted without raising; this fake doesn't enforce
    # write validation (yet) — that's a separate effort.
    sb.table("users").update({"plan": "pro"}).eq("id", "u1").execute()


# ---------------------------------------------------------------------------
# Tables outside the schema snapshot fall back to no-validation mode
# ---------------------------------------------------------------------------


def test_unknown_table_skips_validation() -> None:
    """Tables not in PRODUCTION_SCHEMA should not raise — adoption is gradual.

    A test using a yet-to-be-cataloged table can still use the fake; it just
    doesn't get column-shape validation until that table is added to
    PRODUCTION_SCHEMA.
    """
    sb = FakeSupabase()
    # 'fictional_table' is not in PRODUCTION_SCHEMA
    sb.table("fictional_table").set_row(id="x", anything_goes="here")
    result = sb.table("fictional_table").select("anything_goes").eq("id", "x").single().execute()
    assert result.data == {"anything_goes": "here"}


# ---------------------------------------------------------------------------
# Schema integrity
# ---------------------------------------------------------------------------


def test_production_schema_includes_known_tables() -> None:
    """Sanity check on the schema snapshot itself."""
    assert "twins" in PRODUCTION_SCHEMA
    assert "users" in PRODUCTION_SCHEMA


def test_twins_schema_has_settings_not_user_id() -> None:
    """The exact assertion that would have prevented the original bug if it
    had been written against the real schema."""
    assert "settings" in PRODUCTION_SCHEMA["twins"]
    assert "user_id" not in PRODUCTION_SCHEMA["twins"]


def test_users_schema_has_messages_this_period() -> None:
    """The dashboard quota counter reads from this column."""
    assert "messages_this_period" in PRODUCTION_SCHEMA["users"]
    assert "voice_minutes_this_period" in PRODUCTION_SCHEMA["users"]
    assert "plan" in PRODUCTION_SCHEMA["users"]
