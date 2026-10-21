import os
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_lifecycle_worker_sends_and_marks_event_sent():
    job = {
        "id": "job-1",
        "tenant_id": "tenant-1",
        "twin_id": "twin-1",
        "payload": {
            "event_id": "event-1",
            "user_id": "user-1",
            "tenant_id": "tenant-1",
            "twin_id": "twin-1",
            "recipient_email": "user@example.com",
            "email_type": "welcome_first_persona",
            "category": "product_education",
            "idempotency_key": "lifecycle:user-1:welcome_first_persona:user:user-1:once",
            "payload": {},
        },
    }

    with (
        patch("services.lifecycle_email_service.load_lifecycle_preferences", return_value={"product_education_enabled": True}),
        patch("services.lifecycle_email_service.is_email_suppressed", return_value=False),
        patch("services.lifecycle_email_service.build_lifecycle_email", return_value={
            "subject": "Welcome",
            "html": "<p>Welcome</p>",
            "text": "Welcome",
            "tags": [{"name": "category", "value": "product_education"}],
            "headers": {"List-Unsubscribe": "<https://app.personaon.com/unsubscribe/tok>"},
        }),
        patch("services.lifecycle_email_service.mark_lifecycle_event_sent") as mock_mark_sent,
        patch("services.lifecycle_email_service.mark_lifecycle_event_failed") as mock_mark_failed,
        patch("services.email_service.send_email", new_callable=AsyncMock, return_value="msg_123") as mock_send,
    ):
        from modules.graph_outbox_worker import _process_send_lifecycle_email

        result = await _process_send_lifecycle_email(job)

    assert result is True
    mock_send.assert_awaited_once()
    assert mock_send.call_args.kwargs["idempotency_key"] == job["payload"]["idempotency_key"]
    mock_mark_sent.assert_called_once_with(event_id="event-1", resend_message_id="msg_123")
    mock_mark_failed.assert_not_called()


@pytest.mark.asyncio
async def test_lifecycle_worker_uses_public_site_for_unsubscribe_url():
    job = {
        "id": "job-1",
        "tenant_id": "tenant-1",
        "twin_id": "twin-1",
        "payload": {
            "event_id": "event-1",
            "user_id": "user-1",
            "tenant_id": "tenant-1",
            "twin_id": "twin-1",
            "recipient_email": "user@example.com",
            "email_type": "welcome_first_persona",
            "category": "product_education",
            "idempotency_key": "lifecycle:user-1:welcome_first_persona:user:user-1:once",
            "payload": {},
        },
    }
    backend_url = "https://personaon-api-t7lw2bldqa-uc.a.run.app"

    with (
        patch.dict(
            os.environ,
            {
                "NEXT_PUBLIC_FRONTEND_URL": "https://www.personaon.com",
                "PUBLIC_API_URL": backend_url,
                "CLOUD_RUN_SERVICE_URL": backend_url,
                "LIFECYCLE_PUBLIC_API_URL": "https://www.personaon.com",
            },
            clear=False,
        ),
        patch("services.lifecycle_email_service.load_lifecycle_preferences", return_value={"product_education_enabled": True}),
        patch("services.lifecycle_email_service.is_email_suppressed", return_value=False),
        patch("services.lifecycle_email_service.generate_unsubscribe_token", return_value="token-1"),
        patch("services.lifecycle_email_service.build_lifecycle_email", return_value={
            "subject": "Welcome",
            "html": "<p>Welcome</p>",
            "text": "Welcome",
            "tags": [{"name": "category", "value": "product_education"}],
            "headers": {"List-Unsubscribe": "<https://www.personaon.com/unsubscribe/token-1>"},
        }) as mock_build,
        patch("services.lifecycle_email_service.mark_lifecycle_event_sent"),
        patch("services.lifecycle_email_service.mark_lifecycle_event_failed"),
        patch("services.email_service.send_email", new_callable=AsyncMock, return_value="msg_123"),
    ):
        from modules.graph_outbox_worker import _process_send_lifecycle_email

        result = await _process_send_lifecycle_email(job)

    assert result is True
    assert mock_build.call_args.kwargs["preferences_url"] == "https://www.personaon.com/dashboard/settings?tab=notifications"
    unsubscribe_url = mock_build.call_args.kwargs["unsubscribe_url"]
    assert unsubscribe_url == "https://www.personaon.com/v2/notifications/unsubscribe/token-1"
    assert ".run.app" not in unsubscribe_url
