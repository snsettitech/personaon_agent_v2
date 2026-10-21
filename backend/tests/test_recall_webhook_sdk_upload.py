"""Tests for the sdk_upload.* branch of /v2/meetings/webhook/recall + the
process_desktop_sdk_recording worker handler.

Covers:
- sdk_upload.uploading sets status='uploading' on the matching meeting
- sdk_upload.complete sets status='processing' AND enqueues the worker
- sdk_upload.failed sets status='failed'
- Missing meeting row by sdk_upload_id: handler returns ok, no crash
- Invalid signature -> 401
- Worker handler: video/transcript/speaker_timeline URLs + duration are
  written from the Recall recording payload
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("MEETING_INTELLIGENCE_ENABLED", "true")

from routers.meetings import router as meetings_router  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _result(data: Any) -> SimpleNamespace:
    return SimpleNamespace(data=data)


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(meetings_router)
    return app


def _post_webhook(client: TestClient, body: dict[str, Any]) -> Any:
    return client.post(
        "/v2/meetings/webhook/recall",
        content=json.dumps(body),
        headers={
            "content-type": "application/json",
            "webhook-id": "msg_test",
            "webhook-timestamp": "1716816000",
            "webhook-signature": "v1,test",
        },
    )


# ---------------------------------------------------------------------------
# Webhook dispatch tests (signature verification is patched)
# ---------------------------------------------------------------------------

def test_webhook_sdk_upload_uploading_sets_status() -> None:
    captured: list[dict[str, Any]] = []
    captured_eq: list[tuple[str, Any]] = []

    chain = MagicMock()
    chain.select.return_value = chain
    chain.limit.return_value = chain
    chain.eq.side_effect = lambda col, val: (
        captured_eq.append((col, val)) or chain
    )
    chain.execute.return_value = _result(
        [{"id": "meet-1", "tenant_id": "t-1", "twin_id": None}]
    )
    chain.update.side_effect = lambda payload: (
        captured.append(payload) or chain
    )

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain

    body = {
        "event": "sdk_upload.uploading",
        "data": {"sdk_upload": {"id": "upl-1"}, "recording": {"id": "rec-1"}},
    }

    with patch("routers.meetings.supabase", mock_sb), \
         patch("routers.meetings.verify_recall_webhook", return_value=True):
        client = TestClient(_make_app())
        resp = _post_webhook(client, body)

    assert resp.status_code == 200, resp.text
    assert any(payload.get("status") == "uploading" for payload in captured), captured
    # Audit C1: status UPDATE must be dual-scoped (id, tenant_id). HMAC gates
    # the endpoint but a misrouted webhook MUST NOT be able to flip another
    # tenant's meeting row.
    assert ("tenant_id", "t-1") in captured_eq, \
        f"sdk_upload.uploading UPDATE must include .eq('tenant_id', ...): {captured_eq}"


def test_webhook_sdk_upload_failed_is_tenant_scoped() -> None:
    """Audit C1: sdk_upload.failed UPDATE must include tenant_id."""
    captured: list[dict[str, Any]] = []
    captured_eq: list[tuple[str, Any]] = []

    chain = MagicMock()
    chain.select.return_value = chain
    chain.limit.return_value = chain
    chain.eq.side_effect = lambda col, val: (
        captured_eq.append((col, val)) or chain
    )
    chain.execute.return_value = _result(
        [{"id": "meet-1", "tenant_id": "t-1", "twin_id": None}]
    )
    chain.update.side_effect = lambda payload: (
        captured.append(payload) or chain
    )

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain

    body = {
        "event": "sdk_upload.failed",
        "data": {
            "sdk_upload": {"id": "upl-1", "status": {"code": "upload_timeout"}},
            "recording": {"id": "rec-1"},
        },
    }

    with patch("routers.meetings.supabase", mock_sb), \
         patch("routers.meetings.verify_recall_webhook", return_value=True):
        client = TestClient(_make_app())
        resp = _post_webhook(client, body)

    assert resp.status_code == 200, resp.text
    assert any(payload.get("status") == "failed" for payload in captured), captured
    assert ("tenant_id", "t-1") in captured_eq, \
        f"sdk_upload.failed UPDATE must include .eq('tenant_id', ...): {captured_eq}"


def test_webhook_sdk_upload_complete_is_tenant_scoped() -> None:
    """Audit 2026-05-31 second pass: sdk_upload.complete UPDATE was missing
    .eq('tenant_id', ...) -- the original PR #181 fixed .uploading and
    .failed but missed .complete (the most important branch since it kicks
    off downstream processing). This regression test pins the fix.
    """
    captured_updates: list[dict[str, Any]] = []
    captured_eq: list[tuple[str, Any]] = []

    chain = MagicMock()
    chain.select.return_value = chain
    chain.limit.return_value = chain
    chain.eq.side_effect = lambda col, val: (
        captured_eq.append((col, val)) or chain
    )
    chain.execute.return_value = _result(
        [{"id": "meet-1", "tenant_id": "t-1", "twin_id": "tw-1"}]
    )
    chain.update.side_effect = lambda payload: (
        captured_updates.append(payload) or chain
    )

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain

    mock_outbox = MagicMock()
    mock_outbox.submit.return_value = "job-id-1"

    body = {
        "event": "sdk_upload.complete",
        "data": {"sdk_upload": {"id": "upl-1"}, "recording": {"id": "rec-1"}},
    }

    with patch("routers.meetings.supabase", mock_sb), \
         patch("routers.meetings.verify_recall_webhook", return_value=True), \
         patch("routers.meetings.get_graph_outbox", return_value=mock_outbox):
        client = TestClient(_make_app())
        resp = _post_webhook(client, body)

    assert resp.status_code == 200, resp.text
    # The status='processing' UPDATE must be present AND must include tenant_id.
    assert any(p.get("status") == "processing" for p in captured_updates), \
        f"expected status='processing' UPDATE: {captured_updates}"
    assert ("tenant_id", "t-1") in captured_eq, \
        f"sdk_upload.complete UPDATE must include .eq('tenant_id', ...): {captured_eq}"


def test_webhook_sdk_upload_complete_enqueues_worker() -> None:
    captured_updates: list[dict[str, Any]] = []
    submitted: list[dict[str, Any]] = []

    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = _result(
        [{"id": "meet-1", "tenant_id": "t-1", "twin_id": None}]
    )
    chain.update.side_effect = lambda payload: (
        captured_updates.append(payload) or chain
    )

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain

    mock_outbox = MagicMock()
    mock_outbox.submit.side_effect = lambda **kw: (
        submitted.append(kw) or "job-id-1"
    )

    body = {
        "event": "sdk_upload.complete",
        "data": {
            "sdk_upload": {"id": "upl-1"},
            "recording": {"id": "rec-1"},
        },
    }

    with patch("routers.meetings.supabase", mock_sb), \
         patch("routers.meetings.verify_recall_webhook", return_value=True), \
         patch("routers.meetings.get_graph_outbox", return_value=mock_outbox):
        client = TestClient(_make_app())
        resp = _post_webhook(client, body)

    assert resp.status_code == 200, resp.text
    assert any(p.get("status") == "processing" for p in captured_updates), captured_updates
    assert len(submitted) == 1
    job = submitted[0]
    assert job["tenant_id"] == "t-1"
    assert job["payload"]["recall_recording_id"] == "rec-1"
    assert job["payload"]["meeting_id"] == "meet-1"
    # tenant_id must be in payload so the worker can filter UPDATE by tenant.
    assert job["payload"]["tenant_id"] == "t-1"
    assert job["idempotency_key"] == "desktop_sdk_recording:rec-1"


def test_webhook_sdk_upload_complete_does_not_set_processing_when_enqueue_fails() -> None:
    """If get_graph_outbox().submit() raises, status must NOT advance to
    'processing' (otherwise the row gets stuck — Recall's webhook retry can
    still re-attempt). Status stays at whatever it was (no UPDATE)."""
    captured_updates: list[dict[str, Any]] = []

    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = _result(
        [{"id": "meet-1", "tenant_id": "t-1", "twin_id": None}]
    )
    chain.update.side_effect = lambda payload: (
        captured_updates.append(payload) or chain
    )

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain

    mock_outbox = MagicMock()
    mock_outbox.submit.side_effect = RuntimeError("redis down")

    body = {
        "event": "sdk_upload.complete",
        "data": {"sdk_upload": {"id": "upl-1"}, "recording": {"id": "rec-1"}},
    }

    with patch("routers.meetings.supabase", mock_sb), \
         patch("routers.meetings.verify_recall_webhook", return_value=True), \
         patch("routers.meetings.get_graph_outbox", return_value=mock_outbox):
        client = TestClient(_make_app())
        resp = _post_webhook(client, body)

    assert resp.status_code == 200, resp.text
    # status should NOT have been bumped to 'processing'
    assert not any(p.get("status") == "processing" for p in captured_updates), \
        f"status should not advance to processing when enqueue fails: {captured_updates}"


def test_webhook_sdk_upload_failed_sets_status() -> None:
    captured: list[dict[str, Any]] = []

    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = _result(
        [{"id": "meet-1", "tenant_id": "t-1", "twin_id": None}]
    )
    chain.update.side_effect = lambda payload: (
        captured.append(payload) or chain
    )

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain

    body = {
        "event": "sdk_upload.failed",
        "data": {
            "sdk_upload": {"id": "upl-1", "status": {"code": "failed"}},
            "recording": {"id": "rec-1"},
            "error": "chunk_upload_timeout",
        },
    }

    with patch("routers.meetings.supabase", mock_sb), \
         patch("routers.meetings.verify_recall_webhook", return_value=True):
        client = TestClient(_make_app())
        resp = _post_webhook(client, body)

    assert resp.status_code == 200, resp.text
    assert any(p.get("status") == "failed" for p in captured), captured


def test_webhook_sdk_upload_no_row_does_not_crash() -> None:
    """If the meeting row hasn't been persisted yet (race condition), the
    webhook should log a warning and return 200, not 500."""
    chain = MagicMock()
    chain.select.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = _result([])  # no row found

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain

    body = {
        "event": "sdk_upload.complete",
        "data": {"sdk_upload": {"id": "upl-ghost"}, "recording": {"id": "rec-ghost"}},
    }

    with patch("routers.meetings.supabase", mock_sb), \
         patch("routers.meetings.verify_recall_webhook", return_value=True):
        client = TestClient(_make_app())
        resp = _post_webhook(client, body)

    assert resp.status_code == 200, resp.text


def test_webhook_invalid_signature_returns_401() -> None:
    body = {"event": "sdk_upload.complete", "data": {}}

    with patch("routers.meetings.verify_recall_webhook", return_value=False):
        client = TestClient(_make_app())
        resp = _post_webhook(client, body)

    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Worker handler test
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_process_desktop_sdk_recording_writes_urls_and_duration() -> None:
    from modules.graph_outbox_worker import _process_desktop_sdk_recording
    from modules.graph_outbox import GraphOperationType

    recording_payload = {
        "id": "rec-1",
        "started_at": "2026-05-27T10:00:00Z",
        "completed_at": "2026-05-27T10:01:30Z",  # 90s
        "media_shortcuts": {
            "video_mixed": {"data": {"download_url": "https://s3.example/video.mp4"}},
            "transcript": {"data": {"download_url": "https://s3.example/tx.json"}},
            "participant_events": {
                "data": {"speaker_timeline_download_url": "https://s3.example/spk.json"}
            },
        },
    }
    transcript_entries = [
        {
            "participant": {"name": "Alice"},
            "words": [
                {"text": "We", "start": 0.0, "end": 0.2},
                {"text": "will", "start": 0.2, "end": 0.4},
                {"text": "ship", "start": 0.4, "end": 0.6},
            ],
        },
        {
            "participant": {"name": "Bob"},
            "words": [{"text": "Friday", "start": 1.0, "end": 1.4}],
        },
    ]

    captured_updates: list[dict[str, Any]] = []
    chain = MagicMock()
    chain.update.side_effect = lambda payload: (
        captured_updates.append(payload) or chain
    )
    chain.eq.return_value = chain
    chain.execute.return_value = _result(
        [{"id": "meet-1", "tenant_id": "t-1", "twin_id": "tw-1"}]
    )

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain
    mock_outbox = MagicMock()

    async def _fake_get_recording(recording_id: str) -> dict[str, Any]:
        assert recording_id == "rec-1"
        return recording_payload

    async def _fake_download_transcript_json(url: str) -> list[dict[str, Any]]:
        assert url == "https://s3.example/tx.json"
        return transcript_entries

    async def _fake_run_db(fn: Any) -> Any:
        return fn()

    async def _fake_extract_recap_extras(*_a: Any, **_kw: Any) -> None:
        return None  # no LLM call; extras path is covered by its own test

    with patch("modules.graph_outbox_worker.supabase", mock_sb), \
         patch("services.recall_service.get_recording", _fake_get_recording), \
         patch("services.recall_service.download_transcript_json", _fake_download_transcript_json), \
         patch("services.recap_extras_service.extract_recap_extras", _fake_extract_recap_extras), \
         patch("modules.graph_outbox_worker.get_graph_outbox", return_value=mock_outbox), \
         patch("modules.graph_outbox_worker._run_db", _fake_run_db):
        ok = await _process_desktop_sdk_recording({
            "id": "job-1",
            "payload": {"recall_recording_id": "rec-1", "meeting_id": "meet-1"},
        })

    assert ok is True
    assert captured_updates, "expected at least one .update() call"
    update_payload = captured_updates[0]
    assert update_payload["status"] == "completed"
    assert update_payload["video_url"] == "https://s3.example/video.mp4"
    assert update_payload["transcript_url"] == "https://s3.example/tx.json"
    assert update_payload["speaker_timeline_url"] == "https://s3.example/spk.json"
    assert update_payload["duration_seconds"] == 90
    assert update_payload["meeting_end"] == "2026-05-27T10:01:30Z"
    assert update_payload["transcript_raw"] == transcript_entries
    assert update_payload["transcript_text"] == "Alice: We will ship\nBob: Friday"

    # Two jobs are enqueued on completion: the summary, and identity linking
    # (LINK_MEETING_CONTACTS, wired in d292834a).
    assert mock_outbox.submit.call_count == 2
    by_op = {c.kwargs["operation"]: c.kwargs for c in mock_outbox.submit.call_args_list}
    assert set(by_op) == {
        GraphOperationType.GENERATE_MEETING_SUMMARY,
        GraphOperationType.LINK_MEETING_CONTACTS,
    }
    summary = by_op[GraphOperationType.GENERATE_MEETING_SUMMARY]
    assert summary["tenant_id"] == "t-1"
    assert summary["twin_id"] == "tw-1"
    assert summary["idempotency_key"] == "meeting_summary:meet-1"
    assert summary["payload"] == {"meeting_id": "meet-1"}
    link = by_op[GraphOperationType.LINK_MEETING_CONTACTS]
    assert link["idempotency_key"] == "link_meeting_contacts:meet-1"


@pytest.mark.asyncio
async def test_process_desktop_sdk_recording_missing_payload_returns_true() -> None:
    """Missing recall_recording_id should mark the job done (not retry)."""
    from modules.graph_outbox_worker import _process_desktop_sdk_recording

    ok = await _process_desktop_sdk_recording({"id": "job-2", "payload": {}})
    assert ok is True


@pytest.mark.asyncio
async def test_process_desktop_sdk_recording_no_transcript_when_provider_unset() -> None:
    """When Recall didn't run an ASR provider, media_shortcuts.transcript is
    null. The worker must NOT write transcript_url=null — only omit the key
    so the column keeps its prior value (and downstream UI can detect 'no
    transcript' by absence rather than a sentinel)."""
    from modules.graph_outbox_worker import _process_desktop_sdk_recording

    recording_payload = {
        "id": "rec-2",
        "started_at": "2026-05-27T10:00:00Z",
        "completed_at": "2026-05-27T10:00:30Z",
        "media_shortcuts": {
            "video_mixed": {"data": {"download_url": "https://s3.example/video.mp4"}},
            "transcript": None,  # <-- provider was not configured
            "participant_events": {"data": {}},
        },
    }

    captured_updates: list[dict[str, Any]] = []
    chain = MagicMock()
    chain.update.side_effect = lambda payload: (
        captured_updates.append(payload) or chain
    )
    chain.eq.return_value = chain
    chain.execute.return_value = _result([{"id": "meet-1"}])

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain

    async def _fake_get_recording(_recording_id: str) -> dict[str, Any]:
        return recording_payload

    async def _fake_run_db(fn: Any) -> Any:
        return fn()

    with patch("modules.graph_outbox_worker.supabase", mock_sb), \
         patch("services.recall_service.get_recording", _fake_get_recording), \
         patch("modules.graph_outbox_worker._run_db", _fake_run_db):
        ok = await _process_desktop_sdk_recording({
            "id": "job-3",
            "payload": {"recall_recording_id": "rec-2", "tenant_id": "t-1"},
        })

    assert ok is True
    assert captured_updates
    update = captured_updates[0]
    assert update["video_url"] == "https://s3.example/video.mp4"
    # transcript_url must NOT be in the update at all
    assert "transcript_url" not in update, f"unexpected transcript_url in {update}"
    assert "transcript_raw" not in update
    assert "transcript_text" not in update


@pytest.mark.asyncio
async def test_process_desktop_sdk_recording_download_failure_does_not_retry() -> None:
    """Signed transcript URLs can expire. The media URLs should still persist,
    but summary generation should not enqueue without transcript_raw."""
    from modules.graph_outbox_worker import _process_desktop_sdk_recording

    recording_payload = {
        "id": "rec-download-fails",
        "started_at": "2026-05-27T10:00:00Z",
        "completed_at": "2026-05-27T10:05:00Z",
        "media_shortcuts": {
            "video_mixed": {"data": {"download_url": "https://s3.example/video.mp4"}},
            "transcript": {"data": {"download_url": "https://s3.example/expired.json"}},
            "participant_events": {"data": {}},
        },
    }

    captured_updates: list[dict[str, Any]] = []
    chain = MagicMock()
    chain.update.side_effect = lambda payload: (
        captured_updates.append(payload) or chain
    )
    chain.eq.return_value = chain
    chain.execute.return_value = _result([{"id": "meet-1", "tenant_id": "t-1", "twin_id": "tw-1"}])

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain
    mock_outbox = MagicMock()

    async def _fake_get_recording(_recording_id: str) -> dict[str, Any]:
        return recording_payload

    async def _fake_download_transcript_json(_url: str) -> list[dict[str, Any]]:
        raise RuntimeError("expired")

    async def _fake_run_db(fn: Any) -> Any:
        return fn()

    with patch("modules.graph_outbox_worker.supabase", mock_sb), \
         patch("services.recall_service.get_recording", _fake_get_recording), \
         patch("services.recall_service.download_transcript_json", _fake_download_transcript_json), \
         patch("modules.graph_outbox_worker.get_graph_outbox", return_value=mock_outbox), \
         patch("modules.graph_outbox_worker._run_db", _fake_run_db):
        ok = await _process_desktop_sdk_recording({
            "id": "job-download-fails",
            "payload": {"recall_recording_id": "rec-download-fails", "meeting_id": "meet-1"},
        })

    assert ok is True
    assert captured_updates
    assert captured_updates[0]["status"] == "completed"
    assert "transcript_raw" not in captured_updates[0]
    assert "transcript_text" not in captured_updates[0]
    # No transcript -> no summary job. (Identity linking is still enqueued.)
    from modules.graph_outbox import GraphOperationType

    submitted_ops = [c.kwargs["operation"] for c in mock_outbox.submit.call_args_list]
    assert GraphOperationType.GENERATE_MEETING_SUMMARY not in submitted_ops


@pytest.mark.asyncio
async def test_process_desktop_sdk_recording_writes_recap_extras_when_gemini_succeeds() -> None:
    from modules.graph_outbox_worker import _process_desktop_sdk_recording

    recording_payload = {
        "id": "rec-extras",
        "started_at": "2026-05-27T10:00:00Z",
        "completed_at": "2026-05-27T10:05:00Z",
        "media_shortcuts": {
            "video_mixed": {"data": {"download_url": "https://s3.example/video.mp4"}},
            "transcript": {"data": {"download_url": "https://s3.example/tx.json"}},
            "participant_events": {"data": {}},
        },
    }
    transcript_entries = [
        {
            "participant": {"name": "Alice"},
            "words": [{"text": "Launch", "start": 0.0, "end": 0.5}],
        }
    ]
    extras = {
        "intent": "Align launch scope",
        "what_happened": "The team chose the beta path.",
        "commitments": ["Alice will send pricing by Friday"],
    }

    captured_updates: list[dict[str, Any]] = []
    chain = MagicMock()
    chain.update.side_effect = lambda payload: (
        captured_updates.append(payload) or chain
    )
    chain.eq.return_value = chain
    chain.execute.return_value = _result([{"id": "meet-1", "tenant_id": "t-1", "twin_id": "tw-1"}])

    # Skip-guard SELECT (recap_extras_json not yet populated) must not hit the UPDATE chain.
    select_chain = MagicMock()
    select_chain.eq.return_value = select_chain
    select_chain.maybe_single.return_value = select_chain
    select_chain.execute.return_value = _result({"recap_extras_json": None})
    chain.select.return_value = select_chain

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain

    async def _fake_get_recording(_recording_id: str) -> dict[str, Any]:
        return recording_payload

    async def _fake_download_transcript_json(_url: str) -> list[dict[str, Any]]:
        return transcript_entries

    async def _fake_extract_recap_extras(
        transcript_text: str, title: str | None = None, tenant_id: str | None = None
    ) -> dict[str, Any]:
        assert transcript_text == "Alice: Launch"
        assert title is None
        assert tenant_id == "t-1"  # handler passes the resolved tenant for LLM budgeting
        return extras

    async def _fake_run_db(fn: Any) -> Any:
        return fn()

    with patch("modules.graph_outbox_worker.supabase", mock_sb), \
         patch("services.recall_service.get_recording", _fake_get_recording), \
         patch("services.recall_service.download_transcript_json", _fake_download_transcript_json), \
         patch("services.recap_extras_service.extract_recap_extras", _fake_extract_recap_extras), \
         patch("modules.graph_outbox_worker.get_graph_outbox", return_value=MagicMock()), \
         patch("modules.graph_outbox_worker._run_db", _fake_run_db):
        ok = await _process_desktop_sdk_recording({
            "id": "job-extras",
            "payload": {"recall_recording_id": "rec-extras", "meeting_id": "meet-1"},
        })

    assert ok is True
    assert any(update.get("recap_extras_json") == extras for update in captured_updates)


@pytest.mark.asyncio
async def test_process_desktop_sdk_recording_rejects_non_https_urls() -> None:
    """Defense-in-depth: only https:// URLs are persisted."""
    from modules.graph_outbox_worker import _process_desktop_sdk_recording

    recording_payload = {
        "id": "rec-3",
        "started_at": "2026-05-27T10:00:00Z",
        "completed_at": "2026-05-27T10:00:30Z",
        "media_shortcuts": {
            "video_mixed": {"data": {"download_url": "javascript:alert(1)"}},
            "transcript": {"data": {"download_url": "http://evil.example/tx"}},
            "participant_events": {"data": {}},
        },
    }

    captured_updates: list[dict[str, Any]] = []
    chain = MagicMock()
    chain.update.side_effect = lambda payload: (
        captured_updates.append(payload) or chain
    )
    chain.eq.return_value = chain
    chain.execute.return_value = _result([{"id": "meet-1"}])

    mock_sb = MagicMock()
    mock_sb.table.return_value = chain

    async def _fake_get_recording(_id: str) -> dict[str, Any]:
        return recording_payload

    async def _fake_run_db(fn: Any) -> Any:
        return fn()

    with patch("modules.graph_outbox_worker.supabase", mock_sb), \
         patch("services.recall_service.get_recording", _fake_get_recording), \
         patch("modules.graph_outbox_worker._run_db", _fake_run_db):
        ok = await _process_desktop_sdk_recording({
            "id": "job-4",
            "payload": {"recall_recording_id": "rec-3", "tenant_id": "t-1"},
        })

    assert ok is True
    assert captured_updates
    update = captured_updates[0]
    # Both the javascript: video URL and the http: transcript URL must be dropped
    assert "video_url" not in update
    assert "transcript_url" not in update


# ---------------------------------------------------------------------------
# verify_recall_webhook — direct tests for signature + timestamp tolerance
# ---------------------------------------------------------------------------

def _make_valid_webhook(secret_b64: str, msg_id: str, body: bytes, ts: int | None = None) -> dict[str, str]:
    import base64
    import hashlib
    import hmac
    import time
    ts_value = int(time.time()) if ts is None else ts
    signing = f"{msg_id}.{ts_value}.{body.decode('utf-8')}"
    sig = base64.b64encode(
        hmac.new(
            base64.b64decode(secret_b64), signing.encode("utf-8"), hashlib.sha256,
        ).digest()
    ).decode("utf-8")
    return {
        "webhook_id": msg_id,
        "webhook_timestamp": str(ts_value),
        "webhook_signature": f"v1,{sig}",
    }


def test_verify_recall_webhook_rejects_stale_timestamp() -> None:
    """A captured webhook from >5 minutes ago must be rejected even with a
    valid signature (replay protection)."""
    import base64
    from services import recall_auth

    # secret_b64 is a base64-encoded 32-byte secret
    secret_b64 = base64.b64encode(b"\x00" * 32).decode()
    body = b'{"event":"sdk_upload.complete","data":{}}'

    # Build a webhook 1 hour in the past
    stale = _make_valid_webhook(secret_b64, "msg_old", body, ts=int(__import__("time").time()) - 3600)

    with patch.object(recall_auth, "RECALL_WEBHOOK_SECRET", f"whsec_{secret_b64}"):
        ok = recall_auth.verify_recall_webhook(
            payload=body,
            webhook_id=stale["webhook_id"],
            webhook_timestamp=stale["webhook_timestamp"],
            webhook_signature=stale["webhook_signature"],
        )
    assert ok is False, "stale webhook timestamp must be rejected"


def test_verify_recall_webhook_accepts_fresh_timestamp() -> None:
    """A webhook with a current timestamp and valid signature must pass."""
    import base64
    from services import recall_auth

    secret_b64 = base64.b64encode(b"\x01" * 32).decode()
    body = b'{"event":"sdk_upload.complete","data":{}}'
    fresh = _make_valid_webhook(secret_b64, "msg_now", body)

    with patch.object(recall_auth, "RECALL_WEBHOOK_SECRET", f"whsec_{secret_b64}"):
        ok = recall_auth.verify_recall_webhook(
            payload=body,
            webhook_id=fresh["webhook_id"],
            webhook_timestamp=fresh["webhook_timestamp"],
            webhook_signature=fresh["webhook_signature"],
        )
    assert ok is True


def test_verify_recall_webhook_rejects_non_integer_timestamp() -> None:
    """Malformed timestamp must fail-closed (return False, not crash)."""
    from services import recall_auth
    with patch.object(recall_auth, "RECALL_WEBHOOK_SECRET", "whsec_AAAAAA=="):
        ok = recall_auth.verify_recall_webhook(
            payload=b"{}",
            webhook_id="x",
            webhook_timestamp="not-a-number",
            webhook_signature="v1,abc",
        )
    assert ok is False
