import pytest
from unittest.mock import patch, MagicMock


@pytest.mark.unit
def test_list_leads_calls_correct_table():
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
        {"id": "lead-1", "visitor_name": "Sarah", "visitor_email": "s@example.com",
         "source_domain": "example.com", "created_at": "2026-04-23T12:00:00Z",
         "turn_count": 3, "conversation_id": "conv-1", "offer_state": "offered"}
    ]

    mock_user = {"user_id": "u-1", "tenant_id": "t-1"}

    with patch("routers.widget.get_supabase_client", return_value=mock_sb), \
         patch("routers.widget.verify_twin_ownership", return_value=True):
        from routers.widget import list_widget_leads
        import asyncio
        result = asyncio.run(list_widget_leads(twin_id="twin-1", user=mock_user, limit=50))

    assert len(result) == 1
    assert result[0]["visitor_email"] == "s@example.com"


@pytest.mark.unit
def test_list_leads_returns_empty_list_on_no_data():
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = None

    mock_user = {"user_id": "u-1", "tenant_id": "t-1"}

    with patch("routers.widget.get_supabase_client", return_value=mock_sb), \
         patch("routers.widget.verify_twin_ownership", return_value=True):
        from routers.widget import list_widget_leads
        import asyncio
        result = asyncio.run(list_widget_leads(twin_id="twin-1", user=mock_user))

    assert result == []
