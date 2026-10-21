"""Shared Recall.ai webhook HMAC-SHA256 verification (Svix format)."""

import base64
import hashlib
import hmac
import logging
import os
import time

logger = logging.getLogger(__name__)

RECALL_WEBHOOK_SECRET = os.getenv("RECALL_WEBHOOK_SECRET", "")

# Svix default: reject any webhook whose timestamp is more than 5 minutes old.
# Protects against replay attacks where a captured request is resent indefinitely.
WEBHOOK_TIMESTAMP_TOLERANCE_S = 300


def verify_recall_webhook(
    payload: bytes,
    webhook_id: str,
    webhook_timestamp: str,
    webhook_signature: str,
) -> bool:
    """Verify Recall.ai webhook signature using Svix HMAC-SHA256.

    Also enforces a 5-minute timestamp tolerance to prevent indefinite replay
    of captured-but-valid requests. Tolerance can be widened/disabled in tests
    by patching WEBHOOK_TIMESTAMP_TOLERANCE_S.
    """
    secret = RECALL_WEBHOOK_SECRET
    if not secret:
        logger.error("[RecallAuth] RECALL_WEBHOOK_SECRET not configured")
        return False

    # Reject missing/empty Svix headers explicitly. Without this, an attacker
    # who learns the secret could forge a signature against a signing string
    # built with empty webhook_id/webhook_timestamp components. The signature
    # check itself would still need the secret to succeed, but defense-in-depth
    # closes the surface where an attacker exploits a leaked secret.
    if not webhook_id or not webhook_timestamp or not webhook_signature:
        logger.warning(
            "[RecallAuth] missing webhook header(s) id=%s ts=%s sig=%s",
            bool(webhook_id), bool(webhook_timestamp), bool(webhook_signature),
        )
        return False

    # Timestamp tolerance check — rejects replays older than the tolerance window.
    try:
        ts = int(webhook_timestamp)
    except (TypeError, ValueError):
        logger.warning("[RecallAuth] webhook timestamp not an integer: %r", webhook_timestamp)
        return False
    if abs(time.time() - ts) > WEBHOOK_TIMESTAMP_TOLERANCE_S:
        logger.warning(
            "[RecallAuth] webhook timestamp outside tolerance ts=%s now=%s",
            ts, int(time.time()),
        )
        return False

    if secret.startswith("whsec_"):
        secret = secret[6:]
    try:
        secret_bytes = base64.b64decode(secret)
    except Exception:
        logger.error("[RecallAuth] RECALL_WEBHOOK_SECRET is not valid base64")
        return False

    signing_string = f"{webhook_id}.{webhook_timestamp}.{payload.decode('utf-8')}"
    expected = base64.b64encode(
        hmac.new(secret_bytes, signing_string.encode("utf-8"), hashlib.sha256).digest()
    ).decode("utf-8")

    for sig in webhook_signature.split(" "):
        if sig.startswith("v1,") and hmac.compare_digest(expected, sig[3:]):
            return True
    return False
