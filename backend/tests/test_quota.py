"""Quota module tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


def test_get_quota_for_free_user():
    from modules.quota import get_quota

    with patch("modules.quota._get_supabase") as mock_sb:
        sb = MagicMock()
        mock_sb.return_value = sb
        sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
            "plan": "free",
            "messages_this_period": 120,
            "voice_minutes_this_period": 0,
            "period_started_at": "2026-04-01T00:00:00+00:00",
        }
        result = get_quota("user-1")
    assert result["tier"] == "free"
    assert result["messages_used"] == 120
    assert result["messages_cap"] == 500
    assert result["voice_cap"] == 0


def test_get_quota_for_pro_user_returns_correct_caps():
    from modules.quota import get_quota

    with patch("modules.quota._get_supabase") as mock_sb:
        sb = MagicMock()
        mock_sb.return_value = sb
        sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
            "plan": "pro",
            "messages_this_period": 500,
            "voice_minutes_this_period": 10,
            "period_started_at": "2026-04-15T00:00:00+00:00",
        }
        result = get_quota("user-2")
    assert result["tier"] == "pro"
    assert result["messages_cap"] == 5_000
    assert result["voice_cap"] == 30


def test_get_quota_fallback_on_db_error():
    """DB error returns free-tier defaults — fail-open safe."""
    from modules.quota import get_quota

    with patch("modules.quota._get_supabase", side_effect=Exception("db down")):
        result = get_quota("user-x")
    assert result["tier"] == "free"
    assert result["messages_used"] == 0
    assert result["messages_cap"] == 500


def test_check_and_increment_messages_under_cap_returns_allowed():
    from modules.quota import check_and_increment_messages

    with patch("modules.quota.get_quota") as mock_q, \
         patch("modules.quota._atomic_increment_messages", return_value=101):
        mock_q.return_value = {
            "tier": "free",
            "messages_used": 100, "messages_cap": 500,
            "voice_used": 0, "voice_cap": 0,
            "period_started_at": None,
        }
        allowed, used, cap = check_and_increment_messages("user-1")
    assert allowed is True
    assert used == 101
    assert cap == 500


def test_check_and_increment_messages_at_cap_free_blocks():
    from modules.quota import check_and_increment_messages

    with patch("modules.quota.get_quota") as mock_q:
        mock_q.return_value = {
            "tier": "free",
            "messages_used": 500, "messages_cap": 500,
            "voice_used": 0, "voice_cap": 0,
            "period_started_at": None,
        }
        allowed, used, cap = check_and_increment_messages("user-1")
    assert allowed is False
    assert used == 500
    assert cap == 500


def test_check_and_increment_messages_over_cap_pro_allows_and_reports_meter():
    """Pro user over cap: allowed=True, meter event enqueued for overage."""
    from modules.quota import check_and_increment_messages

    with patch("modules.quota.get_quota") as mock_q, \
         patch("modules.quota._atomic_increment_messages", return_value=5_001), \
         patch("modules.quota._enqueue_meter_event") as mock_meter:
        mock_q.return_value = {
            "tier": "pro",
            "messages_used": 5_000, "messages_cap": 5_000,
            "voice_used": 0, "voice_cap": 30,
            "period_started_at": "2026-04-15T00:00:00+00:00",
        }
        allowed, used, cap = check_and_increment_messages("user-1")
    assert allowed is True
    assert used == 5_001
    mock_meter.assert_called_once()
    kwargs = mock_meter.call_args[1]
    assert kwargs["event_name"] == "personaon_messages"
    assert kwargs["value"] == 1


def test_check_and_increment_voice_zero_cap_blocks_free():
    from modules.quota import check_and_increment_voice

    with patch("modules.quota.get_quota") as mock_q:
        mock_q.return_value = {
            "tier": "free",
            "messages_used": 0, "messages_cap": 500,
            "voice_used": 0, "voice_cap": 0,
            "period_started_at": None,
        }
        allowed, used, cap = check_and_increment_voice("user-1", seconds=60)
    assert allowed is False
    assert cap == 0


def test_check_and_increment_voice_increments_minutes():
    from modules.quota import check_and_increment_voice

    with patch("modules.quota.get_quota") as mock_q, \
         patch("modules.quota._atomic_increment_voice", return_value=5):
        mock_q.return_value = {
            "tier": "pro",
            "messages_used": 0, "messages_cap": 5_000,
            "voice_used": 3, "voice_cap": 30,
            "period_started_at": None,
        }
        # 120 seconds = 2 minutes
        allowed, used, cap = check_and_increment_voice("user-1", seconds=120)
    assert allowed is True
    assert used == 5


def test_reset_period_counters_updates_both_tables():
    from modules.quota import reset_period_counters

    with patch("modules.quota._get_supabase") as mock_sb:
        sb = MagicMock()
        mock_sb.return_value = sb
        reset_period_counters("user-1", period_started_at="2026-05-01T00:00:00+00:00")
    # Both users and subscriptions tables updated
    assert sb.table.call_count == 2
    calls = [call.args[0] for call in sb.table.call_args_list]
    assert "users" in calls
    assert "subscriptions" in calls


def test_get_quota_missing_user_returns_free_defaults():
    """maybe_single returns None when no row — get_quota should return free defaults."""
    from modules.quota import get_quota
    from unittest.mock import MagicMock, patch

    with patch("modules.quota._get_supabase") as mock_sb:
        sb = MagicMock()
        mock_sb.return_value = sb
        result_mock = MagicMock()
        result_mock.data = None
        sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = result_mock

        q = get_quota("no-such-user")

    assert q["tier"] == "free"
    assert q["messages_used"] == 0
    assert q["messages_cap"] == 500


def test_atomic_increment_messages_missing_user_logs_and_returns():
    """If users row is missing, increment should log a warning and return delta."""
    from modules.quota import _atomic_increment_messages
    from unittest.mock import MagicMock, patch

    with patch("modules.quota._get_supabase") as mock_sb, \
         patch("modules.quota.logger") as mock_logger:
        sb = MagicMock()
        mock_sb.return_value = sb
        result_mock = MagicMock()
        result_mock.data = None
        sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = result_mock

        result = _atomic_increment_messages("no-such-user", delta=1)

    assert result == 1
    mock_logger.warning.assert_called_once()
    assert "users row missing" in mock_logger.warning.call_args[0][0]


def test_atomic_increment_voice_missing_user_logs_and_returns():
    """If users row is missing, voice increment should log a warning and return minutes."""
    from modules.quota import _atomic_increment_voice
    from unittest.mock import MagicMock, patch

    with patch("modules.quota._get_supabase") as mock_sb, \
         patch("modules.quota.logger") as mock_logger:
        sb = MagicMock()
        mock_sb.return_value = sb
        result_mock = MagicMock()
        result_mock.data = None
        sb.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value = result_mock

        result = _atomic_increment_voice("no-such-user", minutes=5)

    assert result == 5
    mock_logger.warning.assert_called_once()
    assert "users row missing" in mock_logger.warning.call_args[0][0]


def test_get_twin_owner_id_returns_user_id_from_settings():
    """get_twin_owner_id must return owner_user_id from settings JSONB, not from
    a bare twins.user_id column (which doesn't exist in the schema). Reading
    settings.owner_user_id is the canonical pattern matching auth_guard,
    profile_selection, and the onboarding router."""
    from modules.twin_namespace import _owner_cache, get_twin_owner_id

    _owner_cache.clear()

    with patch("modules.observability.get_supabase_client") as mock_sb_fn:
        sb = MagicMock()
        mock_sb_fn.return_value = sb
        row_mock = MagicMock()
        row_mock.data = {"settings": {"owner_user_id": "user-uuid-123"}}
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = row_mock

        result = get_twin_owner_id("twin-1")

    assert result == "user-uuid-123", (
        "get_twin_owner_id must return settings.owner_user_id "
        "(the canonical owner field), not a non-existent twins.user_id column"
    )


def test_get_twin_owner_id_returns_none_when_settings_missing():
    """If settings is missing or doesn't contain owner_user_id, return None
    instead of crashing — the function fails open so chat keeps working."""
    from modules.twin_namespace import _owner_cache, get_twin_owner_id

    _owner_cache.clear()

    with patch("modules.observability.get_supabase_client") as mock_sb_fn:
        sb = MagicMock()
        mock_sb_fn.return_value = sb
        row_mock = MagicMock()
        row_mock.data = {"settings": {}}
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = row_mock

        result = get_twin_owner_id("twin-no-owner")

    assert result is None


def test_get_twin_owner_id_passes_settings_in_select():
    """Regression guard: the SELECT must request 'settings', not 'user_id'.
    Reading 'user_id' raises 42703 'column twins.user_id does not exist' in
    production."""
    from modules.twin_namespace import _owner_cache, get_twin_owner_id

    _owner_cache.clear()

    with patch("modules.observability.get_supabase_client") as mock_sb_fn:
        sb = MagicMock()
        mock_sb_fn.return_value = sb
        row_mock = MagicMock()
        row_mock.data = {"settings": {"owner_user_id": "u1"}}
        sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = row_mock

        get_twin_owner_id("twin-1")

    select_call = sb.table.return_value.select.call_args
    assert select_call is not None, "select() was never called"
    selected_columns = select_call.args[0] if select_call.args else select_call.kwargs.get("columns", "")
    assert "settings" in selected_columns, (
        f"SELECT must include 'settings'; got {selected_columns!r}. "
        "Reading bare 'user_id' will throw 42703 in production."
    )
    assert "user_id" not in selected_columns.split(","), (
        f"SELECT must not request a bare user_id column; got {selected_columns!r}"
    )


# ---------------------------------------------------------------------------
# Schema-aware tests using FakeSupabase
#
# These tests would have caught the original ``twins.user_id`` 42703 bug at
# CI time. The MagicMock-based tests above gave false confidence by happily
# returning whatever shape the code asked for; FakeSupabase validates SELECTs
# and mock data against the real production schema and raises 42703 if either
# references a column that doesn't exist.
# ---------------------------------------------------------------------------


def test_get_twin_owner_id_with_fake_supabase_happy_path():
    """Same assertion as the test above, but using FakeSupabase. If a future
    refactor reverts to ``select('user_id')``, this test fails at the SELECT
    call — not by silently returning None."""
    from modules.twin_namespace import _owner_cache, get_twin_owner_id
    from tests._fake_supabase import FakeSupabase

    _owner_cache.clear()

    sb = FakeSupabase()
    sb.table("twins").set_row(id="twin-1", settings={"owner_user_id": "user-uuid-123"})

    with patch("modules.observability.get_supabase_client", return_value=sb):
        result = get_twin_owner_id("twin-1")

    assert result == "user-uuid-123"


def test_get_twin_owner_id_with_fake_supabase_missing_settings():
    """fail-open: missing settings → returns None, not exception."""
    from modules.twin_namespace import _owner_cache, get_twin_owner_id
    from tests._fake_supabase import FakeSupabase

    _owner_cache.clear()

    sb = FakeSupabase()
    sb.table("twins").set_row(id="twin-no-owner", settings={})

    with patch("modules.observability.get_supabase_client", return_value=sb):
        result = get_twin_owner_id("twin-no-owner")

    assert result is None


def test_fake_supabase_blocks_the_original_buggy_mock():
    """Direct demonstration that the original test_quota.py mock — which
    set ``data={'user_id': '...'}`` on twins — is now structurally impossible.

    This test would have prevented the production outage if it had existed
    when the metering code was first written. Without FakeSupabase, the bug
    sat in production for ~2 weeks because the mock cheerfully returned a
    fake user_id field that the real database had never heard of."""
    from tests._fake_supabase import FakeSupabase, FakeSupabaseSchemaError

    sb = FakeSupabase()

    # The buggy original test did this. The fake refuses.
    with pytest.raises(FakeSupabaseSchemaError, match="user_id"):
        sb.table("twins").set_row(id="t1", user_id="user-uuid-123", tenant_id="tenant_abc")
