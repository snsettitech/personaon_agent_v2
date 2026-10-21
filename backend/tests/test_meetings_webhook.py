"""Tests for Recall.ai webhook endpoint."""

import base64
import hashlib
import hmac
import json
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


def _make_signature(secret: str, webhook_id: str, timestamp: str, body: bytes) -> str:
    """Helper to generate a valid Svix HMAC signature."""
    raw_secret = secret
    if raw_secret.startswith("whsec_"):
        raw_secret = raw_secret[6:]
    secret_bytes = base64.b64decode(raw_secret)
    signing_string = f"{webhook_id}.{timestamp}.{body.decode('utf-8')}"
    sig = base64.b64encode(
        hmac.new(secret_bytes, signing_string.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")
    return f"v1,{sig}"


TEST_SECRET = "whsec_" + base64.b64encode(b"test-secret-32-bytes-long-padding").decode()


@pytest.fixture
def client():
    with patch("services.recall_auth.RECALL_WEBHOOK_SECRET", TEST_SECRET):
        from main import app
        with TestClient(app) as c:
            yield c


def _post_webhook(client, body: dict, extra_headers: dict | None = None):
    import time as _time
    body_bytes = json.dumps(body).encode()
    webhook_id = "msg-123"
    # Use a current timestamp so the Svix 5-min tolerance check passes.
    timestamp = str(int(_time.time()))
    sig = _make_signature(TEST_SECRET, webhook_id, timestamp, body_bytes)
    headers = {
        "webhook-id": webhook_id,
        "webhook-timestamp": timestamp,
        "webhook-signature": sig,
        "content-type": "application/json",
    }
    if extra_headers:
        headers.update(extra_headers)
    return client.post("/v2/meetings/webhook/recall", content=body_bytes, headers=headers)


def test_valid_signature_accepted(client):
    with patch("routers.meetings.supabase") as mock_sb:
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        resp = _post_webhook(client, {"event": "bot.joining_call", "data": {"bot": {"id": "bot-x"}}})
    assert resp.status_code == 200


def test_invalid_signature_rejected(client):
    import time as _time
    body = json.dumps({"event": "bot.done", "data": {}}).encode()
    resp = client.post(
        "/v2/meetings/webhook/recall",
        content=body,
        headers={
            "webhook-id": "msg-1",
            "webhook-timestamp": str(int(_time.time())),
            "webhook-signature": "v1,invalidsignature==",
            "content-type": "application/json",
        },
    )
    assert resp.status_code == 401


def test_missing_signature_header_rejected(client):
    body = json.dumps({"event": "bot.done"}).encode()
    resp = client.post(
        "/v2/meetings/webhook/recall",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 401


def test_bot_done_enqueues_transcript_job(client):
    meeting_row = {"id": "mtg-1", "twin_id": "twin-1", "tenant_id": "tenant-1"}
    mock_outbox = MagicMock()

    with patch("routers.meetings.supabase") as mock_sb, \
         patch("routers.meetings.get_graph_outbox", return_value=mock_outbox):
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [meeting_row]
        resp = _post_webhook(client, {"event": "bot.done", "data": {"bot": {"id": "bot-abc"}}})

    assert resp.status_code == 200
    # Phase 30-K: bot.done now enqueues TWO jobs — transcript + speaker resolution.
    assert mock_outbox.submit.call_count == 2, (
        f"expected 2 submit calls (transcript + speakers), got {mock_outbox.submit.call_count}"
    )

    by_idempotency = {
        call.kwargs["idempotency_key"]: call.kwargs
        for call in mock_outbox.submit.call_args_list
    }
    # Transcript job
    assert "meeting_transcript:bot-abc" in by_idempotency, (
        f"transcript job missing; got keys={list(by_idempotency.keys())}"
    )
    transcript_kwargs = by_idempotency["meeting_transcript:bot-abc"]
    assert transcript_kwargs["payload"]["bot_id"] == "bot-abc"
    # Speaker resolution job (P1.3.A)
    assert "resolve_speakers:bot-abc" in by_idempotency, (
        f"resolve_speakers job missing; got keys={list(by_idempotency.keys())}"
    )
    resolve_kwargs = by_idempotency["resolve_speakers:bot-abc"]
    assert resolve_kwargs["payload"]["bot_id"] == "bot-abc"
    assert resolve_kwargs["payload"]["meeting_id"] == "mtg-1"
    assert resolve_kwargs["payload"]["twin_id"] == "twin-1"
    assert resolve_kwargs["payload"]["tenant_id"] == "tenant-1"


def test_status_update_on_joining_call(client):
    mock_outbox = MagicMock()
    with patch("routers.meetings.supabase") as mock_sb, \
         patch("routers.meetings.get_graph_outbox", return_value=mock_outbox):
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
        # No meeting found → context prep job is skipped
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        resp = _post_webhook(client, {"event": "bot.joining_call", "data": {"bot": {"id": "bot-y"}}})

    assert resp.status_code == 200
    mock_sb.table.return_value.update.assert_called_with({"status": "bot_joining"})


def test_bot_fatal_marks_failed(client):
    with patch("routers.meetings.supabase") as mock_sb:
        mock_update = MagicMock()
        mock_sb.table.return_value.update.return_value.eq.return_value.execute = mock_update
        resp = _post_webhook(client, {"event": "bot.fatal", "data": {"bot": {"id": "bot-z"}}})

    assert resp.status_code == 200
    mock_sb.table.return_value.update.assert_called_with({"status": "failed"})


def test_unknown_bot_id_returns_ok(client):
    """bot.done with unknown bot_id should not crash — just log and return 200."""
    with patch("routers.meetings.supabase") as mock_sb:
        mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
        resp = _post_webhook(client, {"event": "bot.done", "data": {"bot": {"id": "unknown-bot"}}})
    assert resp.status_code == 200
