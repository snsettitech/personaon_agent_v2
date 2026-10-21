"""Tests for verify_recall_webhook signature + header validation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from unittest.mock import patch


def _build_valid_signature(
    secret_b64: str, webhook_id: str, webhook_ts: str, body: bytes
) -> str:
    """Helper: produce a valid Svix v1 signature for the given inputs."""
    secret_bytes = base64.b64decode(secret_b64)
    signing_string = f"{webhook_id}.{webhook_ts}.{body.decode('utf-8')}"
    digest = hmac.new(
        secret_bytes, signing_string.encode("utf-8"), hashlib.sha256
    ).digest()
    return "v1," + base64.b64encode(digest).decode("utf-8")


def test_rejects_empty_webhook_id() -> None:
    """Empty webhook-id header must be rejected even with a valid signature."""
    from services import recall_auth

    secret_b64 = base64.b64encode(b"a" * 32).decode("utf-8")
    body = b'{"event":"calendar.update"}'
    ts = str(int(time.time()))
    # Build signature for an EMPTY webhook_id so the attacker controls the
    # signing string -- this verifies we reject before signature checking.
    sig = _build_valid_signature(secret_b64, "", ts, body)

    with patch.object(recall_auth, "RECALL_WEBHOOK_SECRET", "whsec_" + secret_b64):
        ok = recall_auth.verify_recall_webhook(body, "", ts, sig)
    assert ok is False, "empty webhook_id must be rejected"


def test_rejects_empty_webhook_timestamp() -> None:
    from services import recall_auth

    secret_b64 = base64.b64encode(b"a" * 32).decode("utf-8")
    body = b'{"event":"calendar.update"}'
    sig = _build_valid_signature(secret_b64, "wh_1", "", body)

    with patch.object(recall_auth, "RECALL_WEBHOOK_SECRET", "whsec_" + secret_b64):
        ok = recall_auth.verify_recall_webhook(body, "wh_1", "", sig)
    assert ok is False, "empty webhook_timestamp must be rejected"


def test_rejects_empty_webhook_signature() -> None:
    from services import recall_auth

    secret_b64 = base64.b64encode(b"a" * 32).decode("utf-8")
    body = b'{"event":"calendar.update"}'
    ts = str(int(time.time()))

    with patch.object(recall_auth, "RECALL_WEBHOOK_SECRET", "whsec_" + secret_b64):
        ok = recall_auth.verify_recall_webhook(body, "wh_1", ts, "")
    assert ok is False, "empty webhook_signature must be rejected"


def test_happy_path_with_valid_signature() -> None:
    """Sanity check: existing valid-signature path still accepts."""
    from services import recall_auth

    secret_b64 = base64.b64encode(b"a" * 32).decode("utf-8")
    body = b'{"event":"calendar.update"}'
    ts = str(int(time.time()))
    sig = _build_valid_signature(secret_b64, "wh_1", ts, body)

    with patch.object(recall_auth, "RECALL_WEBHOOK_SECRET", "whsec_" + secret_b64):
        ok = recall_auth.verify_recall_webhook(body, "wh_1", ts, sig)
    assert ok is True


def test_rejects_invalid_signature_with_valid_headers() -> None:
    """Sanity check: a wrong signature is still rejected (regression guard)."""
    from services import recall_auth

    secret_b64 = base64.b64encode(b"a" * 32).decode("utf-8")
    body = b'{"event":"calendar.update"}'
    ts = str(int(time.time()))

    with patch.object(recall_auth, "RECALL_WEBHOOK_SECRET", "whsec_" + secret_b64):
        ok = recall_auth.verify_recall_webhook(
            body, "wh_1", ts, "v1,definitely-not-a-real-sig"
        )
    assert ok is False
