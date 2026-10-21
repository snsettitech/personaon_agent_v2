from datetime import date
from unittest.mock import MagicMock, patch


def test_claim_weekly_digest_slot_writes_week_of():
    """Weekly digest dedupe must include week_of so NULL meeting_id cannot duplicate sends."""
    mock_resp = MagicMock()
    mock_resp.data = [{"id": "notif-weekly"}]

    with patch("modules.observability.supabase") as mock_supabase:
        mock_supabase.table.return_value.upsert.return_value.execute.return_value = mock_resp

        from services.notification_service import claim_notification_slot

        result = claim_notification_slot(
            "twin-abc",
            None,
            "weekly_digest",
            "tenant-xyz",
            week_of=date(2026, 4, 27),
        )

    assert result is True
    payload = mock_supabase.table.return_value.upsert.call_args.args[0]
    assert payload["week_of"] == "2026-04-27"
    assert mock_supabase.table.return_value.upsert.call_args.kwargs["on_conflict"] == "twin_id,notification_type,week_of"
