"""Shared-secret verification for the GCP ops-alert webhook.

Follows the same *shape* as ``services/recall_auth.py`` (module-level secret
loaded from env, constant-time comparison, defensive "reject if missing"
checks, warn-level logging on rejection) but the wire mechanism is
intentionally simpler.

Why this differs from ``recall_auth.verify_recall_webhook``:
Recall.ai signs webhook bodies Svix-style (``webhook-id`` /
``webhook-timestamp`` / ``webhook-signature`` headers + HMAC-SHA256 over the
raw body). GCP Cloud Monitoring's webhook notification channel does **not**
offer that -- as far as could be confirmed without live access to the GCP
console/docs in this task, a Monitoring webhook notification channel only
supports a static configured URL, optionally paired with HTTP Basic Auth
(channel type ``webhook_basicauth``: a username + password baked into the
channel config). There is no custom-header or HMAC-signing option exposed to
the channel author the way Recall's Svix integration provides.

Given that uncertainty, this accepts the shared secret from any of three
places so the endpoint works whether the channel ends up configured with
Basic Auth, a custom relay (e.g. a Cloud Function fronting a Pub/Sub-based
billing-budget notification) that can set a header, or a static query-string
token baked into the notification channel URL:

  1. HTTP Basic Auth password (``Authorization: Basic base64(user:pass)``)
  2. ``X-Ops-Webhook-Secret`` header
  3. ``secret`` query parameter

**Flag for follow-up:** once the real GCP notification channel(s) are
provisioned, re-verify which of these mechanisms GCP actually sends and trim
the others. Do not treat this list as confirmed GCP behavior.
"""

from __future__ import annotations

import base64
import binascii
import hmac
import logging
import os

logger = logging.getLogger(__name__)

GCP_ALERT_WEBHOOK_SECRET = os.getenv("GCP_ALERT_WEBHOOK_SECRET", "")

if not GCP_ALERT_WEBHOOK_SECRET:
    # Fail-closed behavior in verify_gcp_alert_webhook() already rejects every
    # request when this is unset (see test_gcp_alert_auth_rejects_when_secret_not_configured),
    # so there is no auth bypass here. The gap this closes is *observability*:
    # without a startup-time signal, a missing secret is only discoverable by
    # noticing a stream of per-request 401s (or their absence, if GCP silently
    # gives up retrying) in the ops-alert-webhook logs. Logging once at import
    # time surfaces the misconfiguration immediately in deploy/startup logs.
    logger.warning(
        "[GcpAlertAuth] GCP_ALERT_WEBHOOK_SECRET is not configured -- the "
        "ops-alerts webhook endpoint will reject all inbound requests until "
        "this secret is set"
    )


def _extract_authorization_secret(authorization_header: str) -> str | None:
    """Pull a candidate secret out of the ``Authorization`` header.

    Handles both shapes GCP's ``webhook_tokenauth`` notification channel type
    could plausibly send (the channel's own docs are ambiguous about which):
    ``Basic base64(user:pass)`` (password half) or ``Bearer <token>``.
    """
    if not authorization_header:
        return None
    if authorization_header.startswith("Bearer "):
        return authorization_header[len("Bearer "):].strip() or None
    if authorization_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(authorization_header[len("Basic "):]).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return None
        if ":" not in decoded:
            return None
        return decoded.split(":", 1)[1]
    return None


def verify_gcp_alert_webhook(
    *,
    authorization_header: str = "",
    secret_header: str = "",
    secret_query_param: str = "",
) -> bool:
    """Verify an inbound ops-alert webhook against ``GCP_ALERT_WEBHOOK_SECRET``.

    Returns False (and logs a warning) if the secret is not configured, if none
    of the three carriers above supplied a value, or if the supplied value does
    not match. Uses ``hmac.compare_digest`` for constant-time comparison, same
    as ``recall_auth.verify_recall_webhook``.
    """
    secret = GCP_ALERT_WEBHOOK_SECRET
    if not secret:
        logger.error("[GcpAlertAuth] GCP_ALERT_WEBHOOK_SECRET not configured")
        return False

    candidate = (
        _extract_authorization_secret(authorization_header)
        or secret_header
        or secret_query_param
        or ""
    )
    if not candidate:
        logger.warning("[GcpAlertAuth] no shared secret supplied on inbound alert webhook")
        return False

    return hmac.compare_digest(candidate, secret)
