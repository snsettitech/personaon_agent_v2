from unittest.mock import MagicMock, patch


def _chain(response):
    query = MagicMock()
    query.table.return_value = query
    query.select.return_value = query
    query.eq.return_value = query
    query.is_.return_value = query
    query.lt.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.single.return_value = query
    query.maybe_single.return_value = query
    query.upsert.return_value = query
    query.update.return_value = query
    query.insert.return_value = query
    query.execute.return_value = response
    return query


class _HotLeadQuery:
    def __init__(self, table_name: str):
        self.table_name = table_name
        self.filters: list[tuple[str, str]] = []

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, field, value):
        self.filters.append((field, value))
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self.table_name == "widget_leads":
            return MagicMock(
                data={
                    "id": "lead-1",
                    "twin_id": "twin-1",
                    "visitor_email": "visitor@example.com",
                    "source_domain": "example.com",
                    "conversation_id": "conversation-1",
                }
            )
        if self.table_name == "twins":
            return MagicMock(data={"id": "twin-1", "tenant_id": "tenant-1", "name": "Owner Persona"})
        if self.table_name == "users" and ("tenant_id", "tenant-1") in self.filters:
            return MagicMock(data=[{"id": "owner-1", "email": "owner@example.com"}])
        return MagicMock(data=None)


class _HotLeadSupabase:
    def table(self, table_name: str):
        return _HotLeadQuery(table_name)


def test_load_lifecycle_preferences_defaults_to_enabled_categories():
    with patch("modules.observability.supabase") as mock_supabase:
        mock_supabase.table.return_value = _chain(MagicMock(data=None))

        from services.lifecycle_email_service import load_lifecycle_preferences

        prefs = load_lifecycle_preferences(user_id="user-1", tenant_id="tenant-1")

    assert prefs["product_education_enabled"] is True
    assert prefs["daily_activity_enabled"] is True
    assert prefs["weekly_report_enabled"] is True
    assert prefs["hot_lead_alerts_enabled"] is True
    assert prefs["timezone"] == "UTC"


def test_claim_lifecycle_email_event_uses_stable_unique_key():
    inserted = {"id": "event-1", "status": "sending"}
    response = MagicMock(data=[inserted])

    with patch("modules.observability.supabase") as mock_supabase:
        query = _chain(response)
        mock_supabase.table.return_value = query

        from services.lifecycle_email_service import claim_lifecycle_email_event

        row = claim_lifecycle_email_event(
            user_id="user-1",
            tenant_id="tenant-1",
            email_type="daily_persona_activity",
            category="daily_activity",
            scope_type="user",
            scope_id="user-1",
            period_key="2026-05-02",
            recipient_email="user@example.com",
            payload={"conversation_count": 2},
        )

    assert row == inserted
    upsert_payload = query.upsert.call_args.args[0]
    assert upsert_payload["status"] == "sending"
    assert upsert_payload["idempotency_key"] == "lifecycle:user-1:daily_persona_activity:user:user-1:2026-05-02"
    assert query.upsert.call_args.kwargs["on_conflict"] == "email_type,scope_type,scope_id,period_key"


def test_stale_sending_detection():
    from datetime import datetime, timezone

    stale = {
        "id": "event-stale",
        "status": "sending",
        "resend_message_id": None,
        "created_at": "2026-06-27T14:00:00+00:00",
    }
    query = _chain(MagicMock(data=[stale]))

    from services.lifecycle_email_monitoring import find_stale_sending_lifecycle_email_events

    events = find_stale_sending_lifecycle_email_events(
        query,
        stale_after_minutes=30,
        now=datetime(2026, 6, 27, 15, 0, tzinfo=timezone.utc),
    )

    assert events == [stale]
    query.eq.assert_called_with("status", "sending")
    query.is_.assert_called_with("resend_message_id", "null")
    query.lt.assert_called_with("created_at", "2026-06-27T14:30:00+00:00")


def test_unsubscribe_user_upserts_preferences_before_settings_exist():
    users_query = _chain(MagicMock(data={"tenant_id": "tenant-1"}))
    prefs_query = _chain(MagicMock(data=[{"user_id": "user-1"}]))

    def table(name):
        return {"users": users_query, "notification_preferences": prefs_query}[name]

    with patch("modules.observability.supabase") as mock_supabase:
        mock_supabase.table.side_effect = table

        from services.lifecycle_email_service import unsubscribe_user

        unsubscribe_user("user-1", category="daily_activity")

    upsert_payload = prefs_query.upsert.call_args.args[0]
    assert prefs_query.upsert.call_args.kwargs["on_conflict"] == "user_id"
    assert upsert_payload["user_id"] == "user-1"
    assert upsert_payload["tenant_id"] == "tenant-1"
    assert upsert_payload["daily_activity_enabled"] is False


def test_enqueue_hot_lead_alert_resolves_owner_by_tenant_id():
    mock_outbox = MagicMock()
    mock_outbox.submit.return_value = "job-1"

    with (
        patch("modules.observability.get_supabase_client", return_value=_HotLeadSupabase()),
        patch("modules.graph_outbox.get_graph_outbox", return_value=mock_outbox),
    ):
        from services.lifecycle_email_service import enqueue_hot_lead_alert

        job_id = enqueue_hot_lead_alert(twin_id="twin-1", lead_id="lead-1")

    assert job_id == "job-1"
    payload = mock_outbox.submit.call_args.kwargs["payload"]
    assert payload["user_id"] == "owner-1"
    assert payload["tenant_id"] == "tenant-1"
    assert payload["recipient_email"] == "owner@example.com"


def test_build_lifecycle_email_includes_preferences_and_unsubscribe_links():
    from services.lifecycle_email_service import build_lifecycle_email

    email = build_lifecycle_email(
        email_type="welcome_first_persona",
        frontend_url="https://app.personaon.com",
        preferences_url="https://app.personaon.com/dashboard/settings?tab=notifications",
        unsubscribe_url="https://app.personaon.com/v2/notifications/unsubscribe/token",
        context={},
    )

    assert email["subject"]
    assert "https://app.personaon.com/help/start-with-your-persona" in email["html"]
    assert "Manage preferences" in email["html"]
    assert "unsubscribe" in email["text"].lower()


def test_build_lifecycle_email_uses_home_page_wordmark_lockup():
    from services.lifecycle_email_service import build_lifecycle_email

    email = build_lifecycle_email(
        email_type="welcome_first_persona",
        frontend_url="https://app.personaon.com",
        preferences_url="https://app.personaon.com/dashboard/settings?tab=notifications",
        unsubscribe_url="https://app.personaon.com/v2/notifications/unsubscribe/token",
        context={},
    )

    assert 'aria-label="PersonaOn wordmark"' in email["html"]
    assert "font-family:'Instrument Serif',Georgia,'Times New Roman',serif" in email["html"]
    assert "background:#0066CC" in email["html"]
    assert "rgba(0,102,204,0.18)" in email["html"]
    assert "PersonaOn" in email["text"]


def test_build_lifecycle_email_requires_postal_address_in_production():
    from services.lifecycle_email_service import build_lifecycle_email

    with patch.dict("os.environ", {"ENVIRONMENT": "production"}, clear=False):
        try:
            build_lifecycle_email(
                email_type="welcome_first_persona",
                frontend_url="https://app.personaon.com",
                preferences_url="https://app.personaon.com/dashboard/settings?tab=notifications",
                unsubscribe_url="https://app.personaon.com/v2/notifications/unsubscribe/token",
                context={},
            )
        except RuntimeError as exc:
            assert "EMAIL_FOOTER_POSTAL_ADDRESS" in str(exc)
        else:
            raise AssertionError("Expected missing production postal address to fail")


def test_build_lifecycle_email_accepts_generated_content_without_template_definition():
    from services.lifecycle_email_service import build_lifecycle_email

    email = build_lifecycle_email(
        email_type="agent_generated_notification",
        frontend_url="https://app.personaon.com",
        preferences_url="https://app.personaon.com/dashboard/settings?tab=notifications",
        unsubscribe_url="https://app.personaon.com/v2/notifications/unsubscribe/token",
        context={
            "generated_email": True,
            "subject": "Your PersonaOn access is ready",
            "body": "Your workspace has been unlocked.",
            "category": "account",
            "cta_label": "Open PersonaOn",
            "cta_path": "/dashboard",
            "help_path": "/help/get-started",
        },
    )

    assert email["subject"] == "Your PersonaOn access is ready"
    assert "Your workspace has been unlocked." in email["text"]
    assert "Open PersonaOn: https://app.personaon.com/dashboard" in email["text"]
    assert {"name": "category", "value": "account"} in email["tags"]


def test_build_lifecycle_email_generated_mailto_cta_is_not_rebased():
    from services.lifecycle_email_service import build_lifecycle_email

    email = build_lifecycle_email(
        email_type="agent_generated_notification",
        frontend_url="https://app.personaon.com",
        preferences_url="https://app.personaon.com/dashboard/settings?tab=notifications",
        unsubscribe_url="https://app.personaon.com/v2/notifications/unsubscribe/token",
        context={
            "generated_email": True,
            "subject": "Account access changed",
            "body": "Contact support if this looks wrong.",
            "category": "account",
            "cta_label": "Contact Support",
            "cta_path": "mailto:support@personaon.com",
        },
    )

    assert "Contact Support: mailto:support@personaon.com" in email["text"]
    assert "https://app.personaon.com/mailto:" not in email["html"]


def test_build_lifecycle_email_rejects_placeholder_postal_address_in_production():
    from services.lifecycle_email_service import build_lifecycle_email

    with patch.dict(
        "os.environ",
        {
            "ENVIRONMENT": "production",
            "EMAIL_FOOTER_POSTAL_ADDRESS": "PersonaOn",
        },
        clear=False,
    ):
        try:
            build_lifecycle_email(
                email_type="welcome_first_persona",
                frontend_url="https://app.personaon.com",
                preferences_url="https://app.personaon.com/dashboard/settings?tab=notifications",
                unsubscribe_url="https://app.personaon.com/v2/notifications/unsubscribe/token",
                context={},
            )
        except RuntimeError as exc:
            assert "real company mailing address" in str(exc)
        else:
            raise AssertionError("Expected placeholder production postal address to fail")


def test_build_lifecycle_email_includes_real_postal_address_in_production():
    from services.lifecycle_email_service import build_lifecycle_email

    with patch.dict(
        "os.environ",
        {
            "ENVIRONMENT": "production",
            "EMAIL_FOOTER_POSTAL_ADDRESS": "123 Market St, San Francisco, CA 94105",
        },
        clear=False,
    ):
        email = build_lifecycle_email(
            email_type="welcome_first_persona",
            frontend_url="https://app.personaon.com",
            preferences_url="https://app.personaon.com/dashboard/settings?tab=notifications",
            unsubscribe_url="https://app.personaon.com/v2/notifications/unsubscribe/token",
            context={},
        )

    assert "123 Market St, San Francisco, CA 94105" in email["html"]
    assert "123 Market St, San Francisco, CA 94105" in email["text"]


def test_rollout_start_at_blocks_old_product_education_users():
    from services.lifecycle_digest_service import _is_rollout_eligible

    old_user = {"id": "user-old", "created_at": "2026-04-01T00:00:00+00:00"}

    with patch.dict("os.environ", {"LIFECYCLE_EMAIL_START_AT": "2026-05-01T00:00:00+00:00"}, clear=False):
        assert _is_rollout_eligible(old_user, category="product_education") is False
        assert _is_rollout_eligible(old_user, category="daily_activity") is False


def test_rollout_allowed_user_ids_override_start_date_for_internal_testing():
    from services.lifecycle_digest_service import _is_rollout_eligible

    old_user = {"id": "user-internal", "created_at": "2026-04-01T00:00:00+00:00"}

    with patch.dict(
        "os.environ",
        {
            "LIFECYCLE_EMAIL_START_AT": "2026-05-01T00:00:00+00:00",
            "LIFECYCLE_EMAIL_ALLOWED_USER_IDS": "user-internal,user-other",
        },
        clear=False,
    ):
        assert _is_rollout_eligible(old_user, category="product_education") is True


def test_weekly_next_best_actions_require_meaningful_next_step():
    from services.lifecycle_digest_service import _weekly_candidate_context

    assert _weekly_candidate_context(
        conversation_count=0,
        lead_count=0,
        queued_question_count=0,
        source_count=2,
        is_public=True,
        has_widget_activity=True,
    ) is None

    context = _weekly_candidate_context(
        conversation_count=3,
        lead_count=1,
        queued_question_count=2,
        source_count=0,
        is_public=False,
        has_widget_activity=False,
    )

    assert context is not None
    assert context["candidate_reason"] == "no_sources"
    assert "Add your first source" in context["metrics"]
    assert "Answer 2 queued questions" in context["metrics"]
    assert context["cta_path"] == "/dashboard/knowledge"
