"""Bio/headline meaningfulness validation (execution-board 0.2, PRD R1).

Root cause: a live persona page shipped with headline "software engineer"
and bio literally "nill" because nothing on the write path checked whether
bio/headline text was meaningful — only HTML/prompt-injection sanitization
existed. This pins the fix at three levels:

  1. modules.text_quality — the shared check itself (also reused by the
     execution-board 0.1 publish gate; do not duplicate this logic there).
  2. routers.onboarding.CreatePersonaRequest — onboarding's bio/headline.
  3. routers.profile.UpdateProfileRequest — the dashboard "Publish" tab's
     bio/headline (PATCH /profile).
  4. routers.twins.patch_twin — the *other* dashboard profile-edit path
     (PATCH /twins/{id} with a raw settings dict), which the actual
     dashboard profile page (app/dashboard/profile/page.tsx) uses.

The four required rejections, per the doc's test scenario: too short
("nill"), single word ("a"), all-whitespace, and repeated-character/
low-entropy filler ("asdf asdf asdf").
"""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import routers.twins as twins_mod
from modules.schemas import TwinSettingsUpdate
from modules.text_quality import (
    BIO_MIN_LENGTH,
    is_meaningful_text,
    meaningful_text_error,
    validate_headline_text,
    validate_meaningful_text,
)
from routers.onboarding import CreatePersonaRequest
from routers.profile import UpdateProfileRequest
from tests._supabase_mock import fluent, result

BAD_BIO_INPUTS = ["nill", "a", "   ", "asdf asdf asdf"]

VALID_BIO = "I help early-stage founders design pricing and packaging that converts into revenue."


# ---------------------------------------------------------------------------
# 1. modules.text_quality — the shared, reusable check itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_input", BAD_BIO_INPUTS)
def test_meaningful_text_error_rejects_all_four_bad_cases(bad_input):
    assert meaningful_text_error(bad_input) is not None
    assert is_meaningful_text(bad_input) is False
    with pytest.raises(ValueError):
        validate_meaningful_text(bad_input)


def test_meaningful_text_error_accepts_real_bio():
    assert meaningful_text_error(VALID_BIO) is None
    assert is_meaningful_text(VALID_BIO) is True
    assert validate_meaningful_text(VALID_BIO) == VALID_BIO


def test_meaningful_text_error_rejects_repeated_chunk_even_past_length_floor():
    """"asdf asdf asdf" repeated enough times clears the 40-char floor — the
    repetition/low-entropy check must catch it independently of length."""
    long_repetitive = "asdf asdf asdf asdf asdf asdf asdf asdf asdf asdf"
    assert len(long_repetitive) >= 40
    assert meaningful_text_error(long_repetitive) is not None


def test_meaningful_text_error_rejects_invisible_char_padding():
    """A near-empty bio padded with zero-width/format (Unicode Cf category)
    characters renders as just "Hi there" but must not clear the length/word
    floor by counting invisible padding as real content. Uses a mix of
    *distinct* Cf characters (zero-width space, joiners, bidi marks, BOM,
    etc.) rather than one repeated character, since a single repeated
    invisible char is independently caught by the low-entropy repeat check —
    the padding itself must be stripped before any check runs, not merely
    happen to be repetitive."""
    invisible_chars = [
        "​", "‌", "‍", "‎", "‏", "﻿",
        "⁠", "⁡", "⁢", "⁣", "⁤",
        "‪", "‫", "‬", "‭", "‮",
        "⁦", "⁧", "⁨", "⁩",
        "⁪", "⁫", "⁬", "⁭", "⁮", "⁯",
        "­", "؀", "؁", "؂", "؃", "؄",
        "؅", "؜", "۝", "܏", "࢐", "࢑",
        "࣢", "᠎", "￹",
    ]
    padded = "Hi there" + "".join(invisible_chars)
    assert len(padded) >= BIO_MIN_LENGTH  # clears the raw-length floor
    assert meaningful_text_error(padded) is not None
    assert is_meaningful_text(padded) is False
    with pytest.raises(ValueError):
        validate_meaningful_text(padded)


def test_headline_allows_legitimate_single_word_titles():
    """Headlines are legitimately short/single-word ("CEO", "Founder") —
    they don't get bio's 40-char/2-word bar, just anti-garbage checks."""
    assert validate_headline_text("CEO") == "CEO"
    assert validate_headline_text("Founder") == "Founder"
    assert validate_headline_text("software engineer") == "software engineer"


@pytest.mark.parametrize("bad_input", ["aa", "  ", "aaaaaaaaaa"])
def test_headline_still_rejects_garbage(bad_input):
    with pytest.raises(ValueError):
        validate_headline_text(bad_input)


# ---------------------------------------------------------------------------
# 2. onboarding.CreatePersonaRequest — short_intro (bio) + headline
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_input", BAD_BIO_INPUTS)
def test_create_persona_request_rejects_bad_short_intro(bad_input):
    with pytest.raises(ValidationError):
        CreatePersonaRequest(full_name="Jane Doe", headline="Product Leader", short_intro=bad_input)


def test_create_persona_request_accepts_valid_short_intro():
    req = CreatePersonaRequest(full_name="Jane Doe", headline="Product Leader", short_intro=VALID_BIO)
    assert req.short_intro == VALID_BIO


def test_create_persona_request_allows_omitted_short_intro():
    req = CreatePersonaRequest(full_name="Jane Doe", headline="Product Leader")
    assert req.short_intro is None


def test_create_persona_request_rejects_garbage_headline():
    with pytest.raises(ValidationError):
        CreatePersonaRequest(full_name="Jane Doe", headline="aaaa")


def test_create_persona_request_allows_single_word_headline():
    req = CreatePersonaRequest(full_name="Jane Doe", headline="CEO")
    assert req.headline == "CEO"


# ---------------------------------------------------------------------------
# 3. profile.UpdateProfileRequest — bio + headline (dashboard "Publish" tab)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_input", BAD_BIO_INPUTS)
def test_update_profile_request_rejects_bad_bio(bad_input):
    with pytest.raises(ValidationError):
        UpdateProfileRequest(bio=bad_input)


def test_update_profile_request_accepts_valid_bio():
    assert UpdateProfileRequest(bio=VALID_BIO).bio == VALID_BIO


def test_update_profile_request_allows_omitted_bio():
    assert UpdateProfileRequest().bio is None


def test_update_profile_request_rejects_garbage_headline():
    with pytest.raises(ValidationError):
        UpdateProfileRequest(headline="aaaa")


# ---------------------------------------------------------------------------
# 4. twins.patch_twin — the raw settings dict path the dashboard profile
#    page (app/dashboard/profile/page.tsx) actually PATCHes through.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_patch_twin_rejects_garbage_bio_in_public_profile(monkeypatch):
    monkeypatch.setattr(twins_mod, "_require_authenticated_user", lambda u: u)
    monkeypatch.setattr(twins_mod, "verify_twin_ownership", lambda twin_id, user: None)
    m = fluent(None)
    m.execute.side_effect = [result({"settings": {"public_profile": {"bio": "old bio"}}})]
    monkeypatch.setattr(twins_mod, "supabase", m)

    with pytest.raises(HTTPException) as exc:
        await twins_mod.patch_twin(
            "twin-1",
            TwinSettingsUpdate(settings={"public_profile": {"bio": "nill"}}),
            user={"user_id": "u1", "tenant_id": "t1"},
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_patch_twin_rejects_whitespace_bio_in_persona_profile(monkeypatch):
    monkeypatch.setattr(twins_mod, "_require_authenticated_user", lambda u: u)
    monkeypatch.setattr(twins_mod, "verify_twin_ownership", lambda twin_id, user: None)
    m = fluent(None)
    m.execute.side_effect = [result({"settings": {"persona_profile": {}}})]
    monkeypatch.setattr(twins_mod, "supabase", m)

    with pytest.raises(HTTPException) as exc:
        await twins_mod.patch_twin(
            "twin-1",
            TwinSettingsUpdate(settings={"persona_profile": {"bio": "   "}}),
            user={"user_id": "u1", "tenant_id": "t1"},
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_patch_twin_allows_empty_bio_as_never_set(monkeypatch):
    """An exactly-empty string means "no bio yet" (pre-existing data / a
    persona that never had one) — must not block unrelated settings saves.
    Only a *non-empty* value that fails the meaningfulness bar is rejected."""
    monkeypatch.setattr(twins_mod, "_require_authenticated_user", lambda u: u)
    monkeypatch.setattr(twins_mod, "verify_twin_ownership", lambda twin_id, user: None)
    monkeypatch.setattr(twins_mod, "invalidate_agent", lambda twin_id: None)
    m = fluent(None)
    m.execute.side_effect = [
        result({"settings": {"public_profile": {}}}),
        result([{"id": "twin-1"}]),
    ]
    monkeypatch.setattr(twins_mod, "supabase", m)

    out = await twins_mod.patch_twin(
        "twin-1",
        TwinSettingsUpdate(settings={"public_profile": {"bio": ""}}),
        user={"user_id": "u1", "tenant_id": "t1"},
    )
    assert out


@pytest.mark.asyncio
async def test_patch_twin_accepts_meaningful_bio(monkeypatch):
    monkeypatch.setattr(twins_mod, "_require_authenticated_user", lambda u: u)
    monkeypatch.setattr(twins_mod, "verify_twin_ownership", lambda twin_id, user: None)
    monkeypatch.setattr(twins_mod, "invalidate_agent", lambda twin_id: None)
    m = fluent(None)
    m.execute.side_effect = [
        result({"settings": {"public_profile": {}}}),
        result([{"id": "twin-1"}]),
    ]
    monkeypatch.setattr(twins_mod, "supabase", m)

    out = await twins_mod.patch_twin(
        "twin-1",
        TwinSettingsUpdate(settings={"public_profile": {"bio": VALID_BIO}}),
        user={"user_id": "u1", "tenant_id": "t1"},
    )
    assert out
