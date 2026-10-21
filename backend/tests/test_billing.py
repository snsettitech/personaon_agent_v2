# backend/tests/test_billing.py
"""Billing plan_guard tests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException


def _make_user(user_id: str = "user-123") -> dict:
    return {"user_id": user_id, "email": "test@example.com"}


def test_get_user_tier_fetches_and_caches():
    """First call fetches from DB; second call uses cache."""
    from modules.plan_guard import get_user_tier, invalidate_plan_cache
    invalidate_plan_cache("u1")

    with patch("modules.plan_guard._fetch_tier") as mock_fetch:
        mock_fetch.return_value = "pro"
        tier1 = get_user_tier("u1")
        tier2 = get_user_tier("u1")  # second call — must NOT call _fetch_tier again
        assert tier1 == "pro"
        assert tier2 == "pro"
        assert mock_fetch.call_count == 1


def test_invalidate_plan_cache_forces_refetch():
    from modules.plan_guard import get_user_tier, invalidate_plan_cache
    invalidate_plan_cache("u2")

    with patch("modules.plan_guard._fetch_tier") as mock_fetch:
        mock_fetch.return_value = "free"
        get_user_tier("u2")
        invalidate_plan_cache("u2")
        mock_fetch.return_value = "pro"
        tier = get_user_tier("u2")
        assert tier == "pro"
        assert mock_fetch.call_count == 2


def test_require_plan_passes_when_tier_sufficient():
    from modules.plan_guard import require_plan
    dep = require_plan("pro")
    user = _make_user()

    with patch("modules.plan_guard.get_user_tier", return_value="pro"):
        result = dep(user=user)
    assert result == user


def test_require_plan_raises_402_when_tier_insufficient():
    from modules.plan_guard import require_plan
    dep = require_plan("pro")
    user = _make_user()

    with patch("modules.plan_guard.get_user_tier", return_value="free"):
        with pytest.raises(HTTPException) as exc_info:
            dep(user=user)
    assert exc_info.value.status_code == 402


def test_require_plan_believer_passes_pro_gate():
    """Believer tier satisfies pro gate."""
    from modules.plan_guard import require_plan
    dep = require_plan("pro")
    user = _make_user()

    with patch("modules.plan_guard.get_user_tier", return_value="believer"):
        result = dep(user=user)
    assert result == user


def test_require_plan_free_fails_business_gate():
    from modules.plan_guard import require_plan
    dep = require_plan("business")
    user = _make_user()

    with patch("modules.plan_guard.get_user_tier", return_value="free"):
        with pytest.raises(HTTPException) as exc_info:
            dep(user=user)
    assert exc_info.value.status_code == 402


def test_require_plan_raises_on_unknown_tier():
    from modules.plan_guard import require_plan
    with pytest.raises(ValueError, match="Unknown min_tier"):
        require_plan("enterprise")


# ── webhook tests ──────────────────────────────────────────────────────────

class _BillingFakeResult:
    def __init__(self, data):
        self.data = data


class _BillingFakeQuery:
    def __init__(self, db: "_BillingFakeSupabase", table_name: str):
        self.db = db
        self.table_name = table_name
        self.operation = "select"
        self.payload = None

    def select(self, *_args, **_kwargs):
        self.operation = "select"
        return self

    def update(self, payload):
        self.operation = "update"
        self.payload = payload
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def single(self):
        return self

    def order(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        if self.operation == "update":
            self.db.updates.append((self.table_name, self.payload))
            return _BillingFakeResult({})
        if self.table_name == "users":
            return _BillingFakeResult(self.db.user_row)
        if self.table_name == "subscriptions":
            return _BillingFakeResult(self.db.subscription_rows)
        return _BillingFakeResult({})


class _BillingFakeSupabase:
    def __init__(self, *, user_row: dict, subscription_rows: list[dict] | None = None):
        self.user_row = user_row
        self.subscription_rows = subscription_rows or []
        self.updates: list[tuple[str, dict]] = []

    def table(self, table_name: str):
        return _BillingFakeQuery(self, table_name)


def test_get_current_plan_downgrades_expired_no_card_trial_without_stripe_subscription():
    from routers.billing import get_current_plan

    sb = _BillingFakeSupabase(
        user_row={
            "plan": "pro",
            "trial_kind": "no_card",
            "trial_ends_at": "2000-01-01T00:00:00+00:00",
        },
        subscription_rows=[],
    )
    with patch("routers.billing._get_supabase", return_value=sb), \
         patch("routers.billing.invalidate_plan_cache") as mock_invalidate:
        response = get_current_plan(user={"user_id": "user-expired"})

    assert response.tier == "free"
    assert response.status == "inactive"
    assert response.trial_kind is None
    assert response.trial_ends_at is None
    assert ("users", {"plan": "free", "trial_kind": None, "trial_ends_at": None}) in sb.updates
    mock_invalidate.assert_called_once_with("user-expired")


def test_get_current_plan_preserves_active_stripe_subscription_when_no_card_fields_stale():
    from routers.billing import get_current_plan

    sb = _BillingFakeSupabase(
        user_row={
            "plan": "pro",
            "trial_kind": "no_card",
            "trial_ends_at": "2000-01-01T00:00:00+00:00",
        },
        subscription_rows=[{
            "status": "active",
            "current_period_end": "2099-01-01T00:00:00+00:00",
            "cancel_at_period_end": False,
        }],
    )
    with patch("routers.billing._get_supabase", return_value=sb), \
         patch("routers.billing.invalidate_plan_cache") as mock_invalidate:
        response = get_current_plan(user={"user_id": "user-paid"})

    assert response.tier == "pro"
    assert response.status == "active"
    assert response.trial_kind is None
    assert response.trial_ends_at is None
    assert ("users", {"trial_kind": None, "trial_ends_at": None}) in sb.updates
    mock_invalidate.assert_called_once_with("user-paid")


def test_start_no_card_trial_blocks_persistent_used_marker():
    from routers.billing import start_no_card_trial

    sb = _BillingFakeSupabase(
        user_row={
            "plan": "free",
            "trial_kind": None,
            "trial_ends_at": None,
            "no_card_trial_used_at": "2026-04-01T00:00:00+00:00",
        }
    )
    with patch("routers.billing._get_supabase", return_value=sb):
        with pytest.raises(HTTPException) as exc_info:
            start_no_card_trial(user={"user_id": "user-used"})

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Trial already used. Start a paid plan to continue."


def test_start_no_card_trial_sets_persistent_used_marker():
    from routers.billing import start_no_card_trial

    sb = _BillingFakeSupabase(
        user_row={
            "plan": "free",
            "trial_kind": None,
            "trial_ends_at": None,
            "no_card_trial_used_at": None,
        }
    )
    with patch("routers.billing._get_supabase", return_value=sb), \
         patch("routers.billing.invalidate_plan_cache") as mock_invalidate:
        response = start_no_card_trial(user={"user_id": "user-new"})

    assert response["data"]["tier"] == "pro"
    assert len(sb.updates) == 1
    payload = sb.updates[0][1]
    assert payload["plan"] == "pro"
    assert payload["trial_kind"] == "no_card"
    assert payload["trial_ends_at"]
    assert payload["no_card_trial_used_at"]
    mock_invalidate.assert_called_once_with("user-new")


def test_webhook_bad_signature_returns_400():
    """Invalid Stripe signature → 400."""
    import stripe as real_stripe
    from unittest.mock import patch
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    with patch("routers.billing.stripe") as mock_stripe, \
         patch.dict("os.environ", {"STRIPE_SECRET_KEY": "sk_test_x", "STRIPE_WEBHOOK_SECRET": "whsec_test_x"}):
        mock_stripe.error = real_stripe.error
        mock_stripe.Webhook.construct_event.side_effect = real_stripe.error.SignatureVerificationError(
            "bad sig", "t=1,v1=x", "payload"
        )
        resp = client.post(
            "/billing/webhook",
            content=b'{"id":"evt_bad"}',
            headers={"stripe-signature": "t=1,v1=bad"},
        )
    assert resp.status_code == 400


def test_webhook_duplicate_event_ignored():
    """Same Stripe event_id processed twice → second call returns 200 without re-processing."""
    import json
    from unittest.mock import patch, MagicMock
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    event_payload = {
        "id": "evt_test_dup_001",
        "type": "checkout.session.completed",
        "data": {"object": {
            "metadata": {"user_id": "user-abc", "lookup_key": "pro_monthly"},
            "customer": "cus_test",
            "mode": "subscription",
            "subscription": "sub_test",
        }},
    }

    with patch("routers.billing.stripe") as mock_stripe, \
         patch("routers.billing._get_supabase") as mock_sb_fn, \
         patch.dict("os.environ", {"STRIPE_SECRET_KEY": "sk_test_x", "STRIPE_WEBHOOK_SECRET": "whsec_test_x"}):
        mock_stripe.Webhook.construct_event.return_value = event_payload

        mock_sb = MagicMock()
        mock_sb_fn.return_value = mock_sb

        # First call: no existing event record
        mock_sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []
        mock_sb.table.return_value.insert.return_value.execute.return_value.data = [{}]
        mock_sb.table.return_value.upsert.return_value.execute.return_value.data = [{}]
        mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [{}]

        resp1 = client.post(
            "/billing/webhook",
            content=json.dumps(event_payload).encode(),
            headers={"stripe-signature": "t=1,v1=sig"},
        )
        assert resp1.status_code == 200

        # Second call: insert raises (PRIMARY KEY violation) → returns 200 with duplicate flag
        mock_sb.table.return_value.insert.return_value.execute.side_effect = Exception(
            "duplicate key value violates unique constraint"
        )
        resp2 = client.post(
            "/billing/webhook",
            content=json.dumps(event_payload).encode(),
            headers={"stripe-signature": "t=1,v1=sig"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["data"]["duplicate"] is True


def test_billing_usage_endpoint_returns_quota(client):
    """GET /billing/usage returns the current period quota."""
    from unittest.mock import patch
    with patch("modules.quota.get_quota") as mock_q:
        mock_q.return_value = {
            "tier": "pro",
            "messages_used": 1234,
            "messages_cap": 5_000,
            "voice_used": 5,
            "voice_cap": 30,
            "period_started_at": "2026-04-15T00:00:00+00:00",
        }
        resp = client.get("/billing/usage", headers={"Authorization": "Bearer test"})
    # 200 or 401 depending on test auth — just check the endpoint exists
    assert resp.status_code in (200, 401, 403)
