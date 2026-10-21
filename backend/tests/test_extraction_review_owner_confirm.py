"""Owner-confirm extraction-review backend tests.

Covers the consumer side of the profile-extraction review flag
(``settings.persona_profile.extraction_review``):

  (a) auto_create persists extraction_review when present, omits when absent
  (b) public-profile redactor strips extraction_review (leak guard)
  (c) GET /twins/{id}/profile-insights returns extraction_review
  (d) POST /twins/{id}/profile-insights/dismiss-review clears it; non-owner -> 403

The flag itself is produced by extract_profile's work-experience audit (PR #221);
these tests exercise the consumer side which stays dormant until a profile
carries the flag.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import routers.auto_create as auto_create
import modules.public_profile_pack as profile_pack
from modules.auth_guard import get_current_user
from routers.twins_metrics import router as metrics_router

FAKE_USER = {"user_id": "u-1", "tenant_id": "t-1"}
SAMPLE_REVIEW = {"work_experience_issues": ["Two roles collapsed into one entry."]}


# ---------------------------------------------------------------------------
# (a) auto_create persistence
# ---------------------------------------------------------------------------

class _CapturingSupabase:
    """Minimal fluent Supabase stub that captures twins UPDATE payloads."""

    def __init__(self) -> None:
        self.captured_updates: list[dict] = []

    # fluent no-ops -----------------------------------------------------
    def table(self, _name):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def delete(self, *_a, **_k):
        return self

    def insert(self, *_a, **_k):
        return self

    def single(self):
        return self

    def update(self, payload):
        self.captured_updates.append(payload)
        return self

    def execute(self):
        # `select(settings)` path returns an (empty) existing-settings row.
        return SimpleNamespace(data={"settings": {}})


def _run_extraction_capture(profile: dict) -> _CapturingSupabase:
    sb = _CapturingSupabase()
    with (
        patch.object(auto_create, "get_supabase_client", return_value=sb),
        patch.object(auto_create, "extract_profile", return_value=profile),
        # Empty profile_text short-circuits the vector-upsert path.
        patch.object(auto_create, "profile_to_text", return_value=""),
    ):
        asyncio.run(
            auto_create._run_extraction(
                twin_id="twin-1",
                name="Jane Doe",
                context=None,
                linkedin_url=None,
                linkedin_snapshot=None,
                tenant_id="t-1",
            )
        )
    return sb


def _persisted_persona_profile(sb: _CapturingSupabase) -> dict:
    for payload in sb.captured_updates:
        settings = payload.get("settings")
        if isinstance(settings, dict) and "persona_profile" in settings:
            return settings["persona_profile"]
    raise AssertionError("no settings update with persona_profile was captured")


def test_auto_create_persists_extraction_review_when_present():
    profile = {
        "name": "Jane Doe",
        "occupation": "Engineer",
        "extraction_review": SAMPLE_REVIEW,
    }
    sb = _run_extraction_capture(profile)
    persona_profile = _persisted_persona_profile(sb)
    assert persona_profile.get("extraction_review") == SAMPLE_REVIEW


def test_auto_create_omits_extraction_review_when_absent():
    profile = {"name": "Jane Doe", "occupation": "Engineer"}
    sb = _run_extraction_capture(profile)
    persona_profile = _persisted_persona_profile(sb)
    assert "extraction_review" not in persona_profile


# ---------------------------------------------------------------------------
# (b) public-profile redactor leak guard
# ---------------------------------------------------------------------------

def test_redactor_strips_extraction_review():
    # Simulate a pack that (defensively) carried the owner-only flag through.
    profile_response = {
        "areas_of_expertise": ["AI"],
        "key_achievements": [],
        "personality_traits": [],
        "contributions": [],
        "pinned_questions": [],
        "featured_content": [],
        "social_links": {},
        "social_link_visibility": {},
        "extraction_review": SAMPLE_REVIEW,
        "settings": {"subscription_tier": "free", "section_visibility": {}},
    }
    twin_settings = {
        "subscription_tier": "free",
        "section_visibility": {},
        "persona_profile": {"extraction_review": SAMPLE_REVIEW},
    }

    redacted = profile_pack.redact_public_profile_pack_for_public_response(
        profile_response, twin_settings
    )

    assert "extraction_review" not in redacted
    # Defense-in-depth: no nested copy leaks either.
    assert "extraction_review" not in (redacted.get("settings") or {})


def test_build_public_profile_pack_never_emits_extraction_review(monkeypatch):
    for fn, val in (
        ("_fetch_answerability_score", 0.0),
        ("_fetch_verified_claim_count", 0),
        ("_fetch_public_topics", []),
        ("_fetch_public_claims", []),
        ("_fetch_timeline_events", []),
        ("_fetch_style_profile", {}),
    ):
        monkeypatch.setattr(profile_pack, fn, lambda *_a, _v=val, **_k: _v)

    twin = {
        "id": "twin-1",
        "name": "Jane Doe",
        "settings": {
            "persona_profile": {
                "name": "Jane Doe",
                "extraction_review": SAMPLE_REVIEW,
            }
        },
    }

    pack = profile_pack.build_public_profile_pack(twin)
    assert "extraction_review" not in pack

    # And the public-response redactor keeps it out too.
    redacted = profile_pack.redact_public_profile_pack_for_public_response(
        pack, twin["settings"]
    )
    assert "extraction_review" not in redacted


# ---------------------------------------------------------------------------
# (c) + (d) profile-insights endpoints
# ---------------------------------------------------------------------------

def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(metrics_router)
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    return app


class _InsightsSb:
    """Fluent stub returning a single twin row for the insights/dismiss reads."""

    def __init__(self, twin_data: dict):
        self._twin_data = twin_data
        self.captured_update: dict | None = None

    def table(self, _n):
        return self

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def single(self):
        return self

    def update(self, payload):
        self.captured_update = payload
        return self

    def execute(self):
        return SimpleNamespace(data=self._twin_data)


def test_profile_insights_returns_extraction_review():
    app = _make_app()
    sb = _InsightsSb(
        {
            "id": "twin-1",
            "name": "Jane Doe",
            "settings": {"persona_profile": {"extraction_review": SAMPLE_REVIEW}},
        }
    )

    with (
        patch("routers.twins_metrics.verify_twin_ownership", return_value=True),
        patch("routers.twins_metrics.supabase", sb),
        patch("routers.twins_metrics.build_public_profile_pack", return_value={}),
    ):
        client = TestClient(app)
        resp = client.get("/twins/twin-1/profile-insights")

    assert resp.status_code == 200
    assert resp.json()["extraction_review"] == SAMPLE_REVIEW


def test_profile_insights_extraction_review_null_when_absent():
    app = _make_app()
    sb = _InsightsSb(
        {"id": "twin-1", "name": "Jane Doe", "settings": {"persona_profile": {}}}
    )

    with (
        patch("routers.twins_metrics.verify_twin_ownership", return_value=True),
        patch("routers.twins_metrics.supabase", sb),
        patch("routers.twins_metrics.build_public_profile_pack", return_value={}),
    ):
        client = TestClient(app)
        resp = client.get("/twins/twin-1/profile-insights")

    assert resp.status_code == 200
    assert resp.json()["extraction_review"] is None


def test_dismiss_review_clears_flag():
    app = _make_app()
    sb = _InsightsSb(
        {
            "id": "twin-1",
            "settings": {
                "persona_profile": {
                    "name": "Jane Doe",
                    "extraction_review": SAMPLE_REVIEW,
                },
                "other_key": "kept",
            },
        }
    )

    with (
        patch("routers.twins_metrics.verify_twin_ownership", return_value=True),
        patch("routers.twins_metrics.supabase", sb),
    ):
        client = TestClient(app)
        resp = client.post("/twins/twin-1/profile-insights/dismiss-review")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "data": {"extraction_review": None}}
    # Merge-safe: extraction_review dropped, siblings preserved.
    new_settings = sb.captured_update["settings"]
    assert "extraction_review" not in new_settings["persona_profile"]
    assert new_settings["persona_profile"]["name"] == "Jane Doe"
    assert new_settings["other_key"] == "kept"


def test_dismiss_review_rejects_non_owner():
    app = _make_app()

    def _deny(*_a, **_k):
        raise HTTPException(status_code=403, detail="Access denied to this profile")

    with patch("routers.twins_metrics.verify_twin_ownership", side_effect=_deny):
        client = TestClient(app)
        resp = client.post("/twins/twin-1/profile-insights/dismiss-review")

    assert resp.status_code == 403


def test_profile_insights_rejects_non_owner():
    app = _make_app()

    def _deny(*_a, **_k):
        raise HTTPException(status_code=403, detail="Access denied to this profile")

    with patch("routers.twins_metrics.verify_twin_ownership", side_effect=_deny):
        client = TestClient(app)
        resp = client.get("/twins/twin-1/profile-insights")

    assert resp.status_code == 403
