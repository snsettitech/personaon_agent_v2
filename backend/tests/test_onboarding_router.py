import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from routers import onboarding


def test_status_requires_consent_before_onboarding(monkeypatch):
    # Force the env-level consent gate ON for this assertion.
    monkeypatch.setattr(onboarding, "_consent_gate_enabled", lambda: True)
    monkeypatch.setattr(onboarding, "_consent_state", lambda _user_id: onboarding.ConsentState(accepted=False))
    monkeypatch.setattr(onboarding, "_fetch_profile_twin", lambda _user: None)

    response = asyncio.run(
        onboarding.get_onboarding_status(user={"user_id": "user-1", "tenant_id": "tenant-1"})
    )

    assert response.consent_required is True
    assert response.has_persona is False
    assert response.next_route == "/legal/accept"


def test_status_skips_consent_when_gate_disabled(monkeypatch):
    """When PENDING_CONSENT_ENABLED is off, status reports consent_required=False
    even if the user has no agreement row, and routes to onboarding."""
    monkeypatch.setattr(onboarding, "_consent_gate_enabled", lambda: False)
    monkeypatch.setattr(onboarding, "_consent_state", lambda _user_id: onboarding.ConsentState(accepted=False))
    monkeypatch.setattr(onboarding, "_fetch_profile_twin", lambda _user: None)

    response = asyncio.run(
        onboarding.get_onboarding_status(user={"user_id": "user-1", "tenant_id": "tenant-1"})
    )

    assert response.consent_required is False
    assert response.has_persona is False
    assert response.next_route == "/onboarding"


def test_status_sends_existing_persona_to_dashboard(monkeypatch):
    monkeypatch.setattr(onboarding, "_consent_state", lambda _user_id: onboarding.ConsentState(accepted=True))
    monkeypatch.setattr(
        onboarding,
        "_fetch_profile_twin",
        lambda _user: {
            "id": "twin-1",
            "settings": {
                "handle": "sainath-setti",
                "persona_quality": "basic",
                "enrichment_status": "not_queued",
            },
        },
    )

    response = asyncio.run(
        onboarding.get_onboarding_status(user={"user_id": "user-1", "tenant_id": "tenant-1"})
    )

    assert response.consent_required is False
    assert response.has_persona is True
    assert response.next_route == "/dashboard"
    assert response.persona.handle == "sainath-setti"
    assert response.persona.public_url == "/p/sainath-setti"


def test_create_persona_requires_pending_consent(monkeypatch):
    # Force the consent gate ON so the 403 path is exercised.
    monkeypatch.setattr(onboarding, "_consent_gate_enabled", lambda: True)
    monkeypatch.setattr(onboarding, "_get_pending_consent", lambda _user_id: None)

    payload = onboarding.CreatePersonaRequest(
        full_name="Sainath Setti",
        headline="Founder",
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            onboarding.create_onboarding_persona(
                payload,
                user={"user_id": "user-1", "tenant_id": "tenant-1", "email": "user@example.com"},
            )
        )

    assert exc.value.status_code == 403


def test_create_persona_reuses_backend_persona_contract(monkeypatch):
    # create_onboarding_persona now looks up an existing profile twin first;
    # stub it (no existing persona) so no real Supabase call is made.
    monkeypatch.setattr(onboarding, "_fetch_profile_twin", lambda _user: None)
    monkeypatch.setattr(onboarding, "_get_pending_consent", lambda _user_id: {"id": "agreement-1"})
    monkeypatch.setattr(onboarding, "_extract_linkedin_snapshot", lambda _user_id, _user: ({}, None))
    monkeypatch.setattr(
        onboarding,
        "_create_or_update_persona",
        lambda **_kwargs: (
            {
                "id": "twin-1",
                "settings": {
                    "handle": "sainath-setti",
                    "public_profile": {"display_name": "Sainath Setti"},
                    "persona_quality": "basic",
                    "enrichment_status": "not_queued",
                },
            },
            "",
            "",
        ),
    )
    monkeypatch.setattr(onboarding, "_queue_enrichment", lambda *_args, **_kwargs: "not_queued")
    monkeypatch.setattr(onboarding, "ensure_share_token", lambda *_args, **_kwargs: "share-token")

    payload = onboarding.CreatePersonaRequest(
        full_name="Sainath Setti",
        headline="Founder",
    )
    response = asyncio.run(
        onboarding.create_onboarding_persona(
            payload,
            user={"user_id": "user-1", "tenant_id": "tenant-1", "email": "user@example.com"},
        )
    )

    assert response.twin_id == "twin-1"
    assert response.handle == "sainath-setti"
    assert response.public_url == "/p/sainath-setti"
    assert response.persona_quality == "basic"
    assert response.enrichment_status == "not_queued"


class _PersonaInsertRecorder:
    """Chainable Supabase mock: table("twins").insert(payload).execute() -> the
    inserted row (with a fake id) as if the DB round-tripped it unchanged."""

    def table(self, _name):
        return self

    def insert(self, payload):
        self._payload = payload
        return self

    def execute(self):
        return SimpleNamespace(data=[{**self._payload, "id": "twin-new"}])


def test_create_or_update_persona_sets_default_theme_id_for_new_twin(monkeypatch):
    """Phase 0 review follow-up: _build_profiles never included theme_id, so a
    brand-new twin created via the LIVE /onboarding/persona path (not
    auto_create_twin, which the frontend doesn't call) got no theme_id at all
    -- and the frontend's ThemePicker falls back to 'classic' whenever
    theme_id isn't a valid theme, silently reproducing the exact bug
    execution-board 0.3 was supposed to close everywhere."""
    monkeypatch.setattr(onboarding, "get_supabase_client", lambda: _PersonaInsertRecorder())
    monkeypatch.setattr(onboarding, "derive_creator_ids", lambda _user: ["tenant_x"])
    monkeypatch.setattr(onboarding, "_resolve_handle", lambda *_a, **_kw: "jane-doe")
    monkeypatch.setattr(onboarding, "_update_twin_settings", lambda *_a, **_kw: None)

    request = onboarding.CreatePersonaRequest(
        full_name="Jane Doe",
        headline="Founder & CEO",
        short_intro="Building a company that helps people find real work faster.",
    )
    twin, _linkedin, _website = onboarding._create_or_update_persona(
        request=request,
        user={"user_id": "user-1", "tenant_id": "tenant-1", "email": "jane@example.com"},
        linkedin_snapshot={},
        provider_user_id=None,
        prefetched_twin={},  # forces the brand-new-twin insert branch
    )

    assert twin["settings"]["public_profile"]["theme_id"] == "founder-site"


def test_create_or_update_persona_preserves_existing_theme_id(monkeypatch):
    """A prior manual (or previously-defaulted) theme choice must survive a
    re-submission of the onboarding form -- _build_profiles' public_profile
    fully replaces the stored one, so without this the owner's chosen theme
    would silently revert to a freshly-inferred default on every save."""
    captured: dict = {}
    monkeypatch.setattr(
        onboarding,
        "_update_twin_settings",
        lambda _twin_id, _tenant_id, settings, *_a, **_kw: captured.update(settings=settings),
    )
    # _create_or_update_persona calls get_supabase_client() unconditionally
    # (before branching on new-vs-existing twin), even though the existing-twin
    # path never uses the client directly -- mock it so this test doesn't
    # depend on ambient SUPABASE_URL/.env configuration being present.
    monkeypatch.setattr(onboarding, "get_supabase_client", lambda: SimpleNamespace())

    existing_twin = {
        "id": "twin-1",
        "settings": {
            "owner_user_id": "user-1",
            "handle": "jane-doe",
            "public_profile": {"theme_id": "editorial"},
            "widget_settings": {},
        },
    }
    request = onboarding.CreatePersonaRequest(
        full_name="Jane Doe",
        headline="Founder & CEO",  # would infer "founder-site" if not preserved
        short_intro="Building a company that helps people find real work faster.",
    )
    onboarding._create_or_update_persona(
        request=request,
        user={"user_id": "user-1", "tenant_id": "tenant-1", "email": "jane@example.com"},
        linkedin_snapshot={},
        provider_user_id=None,
        prefetched_twin=existing_twin,
    )

    assert captured["settings"]["public_profile"]["theme_id"] == "editorial"


class _InsertRecorder:
    def __init__(self):
        self.payload = None

    def table(self, _name):
        return self

    def insert(self, payload):
        self.payload = payload
        return self

    def execute(self):
        return SimpleNamespace(data=[self.payload])


def test_accept_consent_records_audit_metadata(monkeypatch):
    recorder = _InsertRecorder()
    calls = iter([
        None,
        {
            "id": "agreement-1",
            "terms_version": onboarding.PENDING_LEGAL_VERSION,
            "privacy_version": onboarding.PENDING_LEGAL_VERSION,
            "accepted_at": "2026-04-27T00:00:00+00:00",
        },
    ])
    monkeypatch.setattr(onboarding, "_get_pending_consent", lambda _user_id: next(calls))
    monkeypatch.setattr(onboarding, "get_supabase_client", lambda: recorder)

    request = SimpleNamespace(
        headers={"x-forwarded-for": "203.0.113.5, 10.0.0.1", "user-agent": "pytest"},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    response = asyncio.run(
        onboarding.accept_onboarding_consent(
            onboarding.ConsentAcceptRequest(accepted=True),
            request,
            user={
                "user_id": "user-1",
                "tenant_id": "tenant-1",
                "app_metadata": {"provider": "google"},
            },
        )
    )

    assert response.accepted is True
    assert recorder.payload["user_id"] == "user-1"
    assert recorder.payload["terms_version"] == onboarding.PENDING_LEGAL_VERSION
    assert recorder.payload["privacy_version"] == onboarding.PENDING_LEGAL_VERSION
    assert recorder.payload["ip_address"] == "203.0.113.5"
    assert recorder.payload["user_agent"] == "pytest"
    assert recorder.payload["auth_provider"] == "google"


class _MissingAgreementTable:
    def table(self, _name):
        return self

    def insert(self, _payload):
        return self

    def execute(self):
        raise RuntimeError("PGRST205 Could not find the table 'public.user_agreements'")


def test_accept_consent_reports_missing_storage(monkeypatch):
    monkeypatch.setattr(onboarding, "_get_pending_consent", lambda _user_id: None)
    monkeypatch.setattr(onboarding, "get_supabase_client", lambda: _MissingAgreementTable())

    request = SimpleNamespace(headers={}, client=None)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            onboarding.accept_onboarding_consent(
                onboarding.ConsentAcceptRequest(accepted=True),
                request,
                user={"user_id": "user-1", "tenant_id": "tenant-1"},
            )
        )

    assert exc.value.status_code == 503
    assert "Consent storage is not ready" in exc.value.detail
