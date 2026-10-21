"""PR4 tests — capture conversion telemetry (lead_email_captured) is emitted and is
non-fatal if analytics fails."""
import pytest
from unittest.mock import MagicMock, patch


def _capture_sb():
    sb = MagicMock()
    sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "lead-1"}])
    return sb


@pytest.mark.asyncio
async def test_capture_lead_contact_emits_conversion_event():
    sb = _capture_sb()
    with (
        patch("adk_core.tools.capture_tools.get_supabase_client", return_value=sb),
        patch("services.lifecycle_email_service.enqueue_hot_lead_alert"),
        patch("modules.posthog_analytics.ph_capture") as mock_ph,
    ):
        from adk_core.tools.capture_tools import _make_capture_lead_tool
        tool = _make_capture_lead_tool(twin_id="t1", lead_id="lead-1")
        result = await tool.func(email="jo@fund.vc", inferred_visitor_type="investor", inferred_intent="seed")
    assert result["status"] == "captured"
    mock_ph.assert_called_once()
    assert mock_ph.call_args.kwargs["event"] == "lead_email_captured"
    props = mock_ph.call_args.kwargs["properties"]
    assert props["twin_id"] == "t1"
    assert props["inferred_intent"] == "seed"


@pytest.mark.asyncio
async def test_capture_lead_contact_telemetry_failure_non_fatal():
    sb = _capture_sb()
    with (
        patch("adk_core.tools.capture_tools.get_supabase_client", return_value=sb),
        patch("services.lifecycle_email_service.enqueue_hot_lead_alert"),
        patch("modules.posthog_analytics.ph_capture", side_effect=RuntimeError("posthog down")),
    ):
        from adk_core.tools.capture_tools import _make_capture_lead_tool
        tool = _make_capture_lead_tool(twin_id="t1", lead_id="lead-1")
        result = await tool.func(email="jo@fund.vc")
    # Telemetry failure must never break a successful capture.
    assert result["status"] == "captured"
