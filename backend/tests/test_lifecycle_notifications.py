from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_lifecycle_daily_cron_enqueues_due_candidates():
    mock_outbox = MagicMock()
    candidates = [
        {
            "user_id": "user-1",
            "tenant_id": "tenant-1",
            "twin_id": "twin-1",
            "email_type": "welcome_first_persona",
            "category": "product_education",
            "period_key": "once",
            "recipient_email": "user@example.com",
            "candidate_reason": "first_persona_created",
            "payload": {"source": "test", "candidate_reason": "first_persona_created"},
        }
    ]

    with (
        patch.dict("os.environ", {"CLOUD_RUN_SERVICE_URL": "", "CRON_SECRET": "secret-123", "LIFECYCLE_EMAIL_DRY_RUN": "false"}),
        patch("services.lifecycle_digest_service.collect_daily_lifecycle_candidates", return_value=candidates),
    ):
        import importlib
        import routers.lifecycle_notifications as module
        importlib.reload(module)

        app = FastAPI()
        app.include_router(module.router)
        client = TestClient(app)

        with patch.object(module, "get_graph_outbox", return_value=mock_outbox):
            response = client.post("/v2/cron/lifecycle/daily", headers={"X-Cron-Secret": "secret-123"})

    assert response.status_code == 200
    assert response.json()["data"]["enqueued"] == 1
    assert response.json()["data"]["reasons"] == {"first_persona_created": 1}
    submit_kwargs = mock_outbox.submit.call_args.kwargs
    assert submit_kwargs["idempotency_key"] == "lifecycle:user-1:welcome_first_persona:user:user-1:once"
    assert submit_kwargs["payload"]["email_type"] == "welcome_first_persona"
    assert submit_kwargs["payload"]["candidate_reason"] == "first_persona_created"


def test_resend_webhook_rejects_invalid_signature():
    with patch.dict("os.environ", {"RESEND_WEBHOOK_SECRET": "whsec_test"}):
        import importlib
        import routers.lifecycle_notifications as module
        importlib.reload(module)

        app = FastAPI()
        app.include_router(module.router)
        client = TestClient(app)

        response = client.post(
            "/v2/webhooks/resend",
            content=b'{"type":"email.delivered"}',
            headers={
                "svix-id": "msg_1",
                "svix-timestamp": "1",
                "svix-signature": "v1,bad",
            },
        )

    assert response.status_code == 401
