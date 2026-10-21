from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from routers import twins as twins_router
from routers import twins_lifecycle as lifecycle_router
from tests._supabase_mock import fluent


@pytest.mark.asyncio
async def test_list_twins_requires_authenticated_user():
    with pytest.raises(HTTPException) as exc:
        await twins_router.list_twins(user=None)
    assert exc.value.status_code == 401
    assert "Not authenticated" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_create_twin_requires_authenticated_user():
    request = twins_router.TwinCreateRequest(name="Test Twin")
    with pytest.raises(HTTPException) as exc:
        await twins_router.create_twin(request=request, user=None)
    assert exc.value.status_code == 401
    assert "Not authenticated" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_publish_draft_requires_authenticated_user():
    with pytest.raises(HTTPException) as exc:
        await lifecycle_router.publish_draft_twin(twin_id="twin-1", user=None)
    assert exc.value.status_code == 401
    assert "Not authenticated" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_unpublish_requires_authenticated_user():
    with pytest.raises(HTTPException) as exc:
        await lifecycle_router.unpublish_twin(twin_id="twin-1", user=None)
    assert exc.value.status_code == 401
    assert "Not authenticated" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_publish_draft_rejects_visitor_role():
    fake_visitor = {"user_id": "visitor-1", "tenant_id": "tenant-1", "role": "visitor"}
    with pytest.raises(HTTPException) as exc:
        await lifecycle_router.publish_draft_twin(twin_id="twin-1", user=fake_visitor)
    assert exc.value.status_code == 403
    assert "Visitor" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_unpublish_rejects_visitor_role():
    fake_visitor = {"user_id": "visitor-1", "tenant_id": "tenant-1", "role": "visitor"}
    with pytest.raises(HTTPException) as exc:
        await lifecycle_router.unpublish_twin(twin_id="twin-1", user=fake_visitor)
    assert exc.value.status_code == 403
    assert "Visitor" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_publish_draft_raises_404_when_twin_missing(monkeypatch):
    """publish-draft should 404 if the twin doesn't exist, not silently pass."""
    from types import SimpleNamespace

    fake_user = {"user_id": "user-1", "tenant_id": "tenant-1"}

    monkeypatch.setattr(lifecycle_router, "verify_twin_ownership", lambda twin_id, user: None)

    class FakeSupabase:
        def table(self, name):
            return self

        def select(self, *args):
            return self

        def eq(self, *args):
            return self

        def single(self):
            return self

        def execute(self):
            return SimpleNamespace(data=None)

    monkeypatch.setattr(lifecycle_router, "supabase", FakeSupabase())

    with pytest.raises(HTTPException) as exc:
        await lifecycle_router.publish_draft_twin(twin_id="twin-missing", user=fake_user)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_publish_draft_rejects_meaningless_bio_no_populated_section(monkeypatch):
    """Execution-board 0.1 (PRD R1) verification scenario: a fresh account
    with headline "qa" and bio "nill", no work_experience/education, must
    NOT become publishable — publish-draft must reject (400), and must
    never flip status=active or public_share_enabled=True on this profile.
    """
    fake_user = {"user_id": "user-1", "tenant_id": "tenant-1"}
    monkeypatch.setattr(lifecycle_router, "verify_twin_ownership", lambda twin_id, user: None)

    twin_row = {
        "status": "draft",
        "settings": {
            "persona_profile": {},
            "public_profile": {
                "display_name": "QA Persona",
                "occupation": "qa",
                "short_description": "qa",
                "headline": "qa",
                "bio": "nill",
            },
        },
    }
    sb = fluent(twin_row)
    monkeypatch.setattr(lifecycle_router, "supabase", sb)

    with pytest.raises(HTTPException) as exc:
        await lifecycle_router.publish_draft_twin(twin_id="twin-qa", user=fake_user)
    assert exc.value.status_code == 400
    # The update chain must never have been reached — no status flip.
    sb.update.assert_not_called()


@pytest.mark.asyncio
async def test_publish_draft_succeeds_once_bio_meaningful_and_section_populated(monkeypatch):
    """Same starting twin as the rejection test, but with a real bio AND a
    populated work_experience entry — now publishable. Both AND'd
    conditions (bio meaningfulness AND a populated section) are required;
    adding only the work_experience entry while leaving bio="nill" would
    still fail the gate (see the rejection test above for that half)."""
    fake_user = {"user_id": "user-1", "tenant_id": "tenant-1"}
    monkeypatch.setattr(lifecycle_router, "verify_twin_ownership", lambda twin_id, user: None)

    twin_row = {
        "status": "draft",
        "settings": {
            "persona_profile": {},
            "public_profile": {
                "display_name": "QA Persona",
                "occupation": "QA Engineer",
                "short_description": "QA engineer with test automation experience.",
                "headline": "QA Engineer",
                "bio": (
                    "QA engineer with five years of experience building "
                    "automated test suites for fintech products."
                ),
                "work_experience": [
                    {"company": "Acme", "role": "QA Engineer", "description": "Built test automation."}
                ],
            },
        },
    }
    select_chain = fluent(twin_row)
    update_chain = fluent([{"id": "twin-qa", "status": "active"}])
    sb = MagicMock()
    sb.table.side_effect = [select_chain, update_chain]
    monkeypatch.setattr(lifecycle_router, "supabase", sb)

    out = await lifecycle_router.publish_draft_twin(twin_id="twin-qa", user=fake_user)
    assert out["status"] == "active"


@pytest.mark.asyncio
async def test_unpublish_raises_404_when_twin_missing(monkeypatch):
    """unpublish should 404 if the twin doesn't exist."""
    from types import SimpleNamespace

    fake_user = {"user_id": "user-1", "tenant_id": "tenant-1"}

    monkeypatch.setattr(lifecycle_router, "verify_twin_ownership", lambda twin_id, user: None)

    class FakeSupabase:
        def table(self, name):
            return self

        def select(self, *args):
            return self

        def eq(self, *args):
            return self

        def single(self):
            return self

        def execute(self):
            return SimpleNamespace(data=None)

    monkeypatch.setattr(lifecycle_router, "supabase", FakeSupabase())

    with pytest.raises(HTTPException) as exc:
        await lifecycle_router.unpublish_twin(twin_id="twin-missing", user=fake_user)
    assert exc.value.status_code == 404
