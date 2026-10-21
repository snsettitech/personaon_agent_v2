import sys
import os
import pytest
from unittest.mock import MagicMock, patch
import json

# Add backend to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from modules.actions_engine import ActionExecutor

@pytest.fixture
def mock_connector_data():
    return {
        "id": "conn-123",
        "connector_type": "google_calendar",
        "credentials_encrypted": json.dumps({
            "token": "mock_token",
            "refresh_token": "mock_refresh",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_id": "mock_client",
            "client_secret": "mock_secret",
            "scopes": ["https://www.googleapis.com/auth/calendar"]
        })
    }

# Patching the imports in modules.actions_engine directly
@patch("modules.actions_engine.Credentials")
@patch("modules.actions_engine.build")
@patch("modules.actions_engine.supabase")
def test_execute_draft_calendar_event(mock_supabase, mock_build, mock_creds, mock_connector_data):
    # Setup mocks
    # Note: we use the global mock_supabase_client we injected
    mock_query = MagicMock()
    mock_supabase.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = mock_query
    mock_query.data = mock_connector_data

    mock_service = MagicMock()
    mock_build.return_value = mock_service

    mock_events = MagicMock()
    mock_service.events.return_value = mock_events

    mock_events.insert.return_value.execute.return_value = {
        "id": "event-123",
        "htmlLink": "https://calendar.google.com/event?eid=123",
        "status": "confirmed"
    }

    # Inputs
    inputs = {
        "title": "Test Meeting",
        "start_time": "2023-10-27T10:00:00+00:00",
        "duration_minutes": 60,
        "description": "Discuss project status",
        "attendees": ["alice@example.com", "bob@example.com"]
    }

    # Execute
    result = ActionExecutor._execute_draft_calendar_event("conn-123", inputs)

    # Verify
    assert result["status"] == "event_created"
    assert result["event_link"] == "https://calendar.google.com/event?eid=123"
    assert result["event_id"] == "event-123"

    # Verify API call
    mock_events.insert.assert_called_once()
    call_kwargs = mock_events.insert.call_args[1]
    assert call_kwargs["calendarId"] == "primary"
    body = call_kwargs["body"]
    assert body["summary"] == "Test Meeting"
    assert body["description"] == "Discuss project status"
    assert body["start"]["dateTime"] == "2023-10-27T10:00:00+00:00"

    # Check end time is correct (start + 60 mins)
    assert "dateTime" in body["end"]

    # Check attendees
    assert len(body["attendees"]) == 2
    assert {"email": "alice@example.com"} in body["attendees"]
