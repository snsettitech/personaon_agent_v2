"""Tests for the public handle SEO endpoints + the indexability gate (T0-1)."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import handles_public
from services.seo_indexability import (
    MIN_BIO_LENGTH,
    compute_is_indexable,
    indexability_signals_from_settings,
    is_twin_indexable,
)
from tests._supabase_mock import fluent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _twin(
    handle: str,
    *,
    bio_len: int = 300,
    expertise: int = 3,
    seeds: int = 3,
    share_token: str | None = None,
    created: str = "2026-01-01T00:00:00+00:00",
    updated: str = "2026-02-02T00:00:00+00:00",
) -> dict:
    settings: dict = {
        "handle": handle,
        "public_profile": {
            "bio": "x" * bio_len,
            "areas_of_expertise": [f"area-{i}" for i in range(expertise)],
            "public_response_seeds": [
                {"question": f"q{i}", "answer": "a"} for i in range(seeds)
            ],
        },
    }
    if share_token is not None:
        settings["widget_settings"] = {"share_token": share_token}
    return {
        "id": f"twin-{handle}",
        "name": handle.title(),
        "status": "active",
        "created_at": created,
        "updated_at": updated,
        "settings": settings,
    }


def _client(rows: list[dict]) -> tuple[TestClient, object]:
    app = FastAPI()
    app.include_router(handles_public.router)
    return TestClient(app, raise_server_exceptions=True), fluent(rows)


_ALL_PUBLIC = lambda twin: True  # noqa: E731 — test stub for the visibility helper


# ---------------------------------------------------------------------------
# Pure indexability gate
# ---------------------------------------------------------------------------


def test_compute_is_indexable_truth_table():
    # The gate keys on a substantive bio. Expertise/seeds are NOT required
    # (rarely populated in real data; their absence must not block indexing).
    assert compute_is_indexable({"bio": "x" * MIN_BIO_LENGTH}) is True
    assert compute_is_indexable({"bio": "x" * (MIN_BIO_LENGTH - 1)}) is False
    assert compute_is_indexable({"bio": "short"}) is False
    assert compute_is_indexable({}) is False
    # A long bio alone qualifies even with no expertise/seeds.
    assert (
        compute_is_indexable(
            {"bio": "x" * 400, "areas_of_expertise": [], "public_response_seeds": []}
        )
        is True
    )


def test_signals_fall_back_to_persona_profile():
    settings = {
        "persona_profile": {"bio": "y" * 250, "areas_of_expertise": ["a", "b", "c"]},
        "public_profile": {"public_response_seeds": [1, 2, 3]},
    }
    sig = indexability_signals_from_settings(settings)
    assert len(sig["bio"]) == 250
    assert sig["areas_of_expertise"] == ["a", "b", "c"]
    assert is_twin_indexable({"settings": settings}) is True


def test_persona_profile_json_string_is_parsed():
    settings = {"persona_profile": '{"bio": "z", "areas_of_expertise": []}'}
    sig = indexability_signals_from_settings(settings)
    assert sig["bio"] == "z"


def test_short_public_profile_bio_does_not_shadow_long_persona_bio():
    # Regression (P0.1): the exact false-negative from the task. A short
    # public_profile.bio tagline used to win first-non-empty and force noindex
    # even though a long persona_profile.bio exists (and is what the page
    # renders). The gate now keys on the LONGEST renderable candidate, so the
    # substantive bio wins and the page is (correctly) indexable.
    long_bio = "x" * 300
    settings = {
        "public_profile": {"bio": "Founder & AI advisor."},  # short tagline
        "persona_profile": {"bio": long_bio},                 # substantive bio
    }
    sig = indexability_signals_from_settings(settings)
    assert len(sig["bio"]) == 300
    assert compute_is_indexable(sig) is True
    assert is_twin_indexable({"settings": settings}) is True


def test_short_tagline_field_does_not_shadow_long_bio():
    # Regression (P0.1): a short tagline in an earlier-priority field
    # (public_intro / short_description) must not shadow a long bio the page
    # actually renders. Effective bio >= MIN_BIO_LENGTH => is_indexable True,
    # even though shorter tagline fields exist.
    long_bio = "PersonaOn builds AI-native company websites for B2B teams. " * 6
    assert len(long_bio) >= MIN_BIO_LENGTH
    settings = {
        "public_profile": {"short_description": "AI website OS."},  # short tagline
        "public_intro": "We build websites.",                       # short tagline
        "persona_profile": {"bio": long_bio},                       # rendered bio
    }
    sig = indexability_signals_from_settings(settings)
    assert sig["bio"] == long_bio.strip()
    assert is_twin_indexable({"settings": settings}) is True


def test_gate_still_noindex_when_all_bio_fields_thin():
    # Anti-thin posture preserved: MAX-length across candidates does not lower
    # the bar — if every renderable bio field is short, the page stays noindex.
    settings = {
        "public_profile": {"bio": "Founder.", "short_description": "AI advisor."},
        "public_intro": "Hi there.",
    }
    sig = indexability_signals_from_settings(settings)
    assert len(sig["bio"]) < MIN_BIO_LENGTH
    assert is_twin_indexable({"settings": settings}) is False


# ---------------------------------------------------------------------------
# GET /handles/public  +  /handles/public/count
# (pagination is Python-side over the sorted in-memory list, not DB-side)
# ---------------------------------------------------------------------------


def test_list_returns_indexable_only_sorted():
    rows = [_twin("zed"), _twin("alice"), _twin("thin", bio_len=10)]
    client, sb = _client(rows)
    with patch.object(handles_public, "supabase", sb), patch.object(
        handles_public, "is_publicly_accessible_twin_record", _ALL_PUBLIC
    ):
        resp = client.get("/handles/public")
    assert resp.status_code == 200
    body = resp.json()
    assert [i["handle"] for i in body["items"]] == ["alice", "zed"]  # sorted, thin dropped
    assert all(i["is_indexable"] for i in body["items"])
    assert body["next_offset"] is None


def test_list_uses_updated_at_for_last_modified():
    rows = [_twin("rich", updated="2026-05-05T00:00:00+00:00")]
    client, sb = _client(rows)
    with patch.object(handles_public, "supabase", sb), patch.object(
        handles_public, "is_publicly_accessible_twin_record", _ALL_PUBLIC
    ):
        resp = client.get("/handles/public")
    assert resp.json()["items"][0]["last_modified"] == "2026-05-05T00:00:00+00:00"


def test_list_pagination_reports_next_offset():
    rows = [_twin(f"h{i:02d}") for i in range(5)]
    client, sb = _client(rows)
    with patch.object(handles_public, "supabase", sb), patch.object(
        handles_public, "is_publicly_accessible_twin_record", _ALL_PUBLIC
    ):
        resp = client.get("/handles/public", params={"offset": 0, "limit": 2})
    body = resp.json()
    assert body["returned"] == 2
    assert body["next_offset"] == 2


def test_list_excludes_non_public_twins():
    rows = [_twin("pub"), _twin("priv")]
    client, sb = _client(rows)
    with patch.object(handles_public, "supabase", sb), patch.object(
        handles_public,
        "is_publicly_accessible_twin_record",
        lambda t: t.get("settings", {}).get("handle") == "pub",
    ):
        resp = client.get("/handles/public")
    assert [i["handle"] for i in resp.json()["items"]] == ["pub"]


def test_count_indexable_only():
    rows = [_twin("a"), _twin("b"), _twin("thin", bio_len=5)]
    client, sb = _client(rows)
    with patch.object(handles_public, "supabase", sb), patch.object(
        handles_public, "is_publicly_accessible_twin_record", _ALL_PUBLIC
    ):
        resp = client.get("/handles/public/count")
    assert resp.json() == {"count": 2}


# ---------------------------------------------------------------------------
# GET /handles/{handle}/profile
# ---------------------------------------------------------------------------


def test_handle_profile_returns_pack_token_and_gate():
    rows = [_twin("rich", share_token="tok-rich")]
    client, sb = _client(rows)
    fake_pack = {"display_name": "Rich", "bio": "x" * 300}
    with patch.object(handles_public, "supabase", sb), patch.object(
        handles_public, "is_publicly_accessible_twin_record", _ALL_PUBLIC
    ), patch.object(
        handles_public, "build_public_profile_pack", lambda t: fake_pack
    ), patch.object(
        handles_public,
        "redact_public_profile_pack_for_public_response",
        lambda pack, settings: pack,
    ):
        resp = client.get("/handles/rich/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["twin_id"] == "twin-rich"
    assert body["handle"] == "rich"
    assert body["share_token"] == "tok-rich"  # read from settings, not minted
    assert body["is_indexable"] is True
    assert body["profile"]["display_name"] == "Rich"


def test_handle_profile_share_token_none_when_missing():
    rows = [_twin("rich")]  # no widget_settings.share_token
    client, sb = _client(rows)
    with patch.object(handles_public, "supabase", sb), patch.object(
        handles_public, "is_publicly_accessible_twin_record", _ALL_PUBLIC
    ), patch.object(
        handles_public, "build_public_profile_pack", lambda t: {"display_name": "Rich"}
    ), patch.object(
        handles_public,
        "redact_public_profile_pack_for_public_response",
        lambda pack, settings: pack,
    ):
        resp = client.get("/handles/rich/profile")
    assert resp.status_code == 200
    assert resp.json()["share_token"] is None


def test_handle_profile_404_for_unknown_handle():
    rows = [_twin("rich")]
    client, sb = _client(rows)
    with patch.object(handles_public, "supabase", sb), patch.object(
        handles_public, "is_publicly_accessible_twin_record", _ALL_PUBLIC
    ):
        resp = client.get("/handles/ghost/profile")
    assert resp.status_code == 404


def test_handle_profile_404_when_not_publicly_accessible():
    rows = [_twin("rich")]
    client, sb = _client(rows)
    with patch.object(handles_public, "supabase", sb), patch.object(
        handles_public, "is_publicly_accessible_twin_record", lambda t: False
    ):
        resp = client.get("/handles/rich/profile")
    assert resp.status_code == 404
