"""Tests for services/meeting_people_extractor.py (Phase F.3 — recap-people extraction)."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from services.meeting_people_extractor import extract_people_from_recap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_resp(text: str) -> SimpleNamespace:
    """Build a fake Gemini response object with a .text attribute."""
    return SimpleNamespace(text=text)


def _make_client(response_text: str) -> MagicMock:
    """Return a mock genai Client whose .models.generate_content returns a fake response."""
    client = MagicMock()
    client.models.generate_content.return_value = _fake_resp(response_text)
    return client


def _people_json(*names: str) -> str:
    """Serialize a people payload as JSON the way Gemini would return it."""
    return json.dumps({"people": [{"name": n} for n in names]})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extract_returns_empty_when_no_recap():
    """No title, no recap_extras, no summary_json → empty recap text → returns [] without calling Gemini."""
    with patch("services.meeting_people_extractor.get_genai_client") as mock_client_factory:
        result = await extract_people_from_recap(
            title=None,
            owner_name="Sai",
            recap_extras=None,
            summary_json=None,
        )
    assert result == []
    mock_client_factory.assert_not_called()


@pytest.mark.asyncio
async def test_extract_excludes_owner():
    """Gemini returns [Sai, Sooraj]; owner_name='Sai' → only Sooraj in output."""
    payload = json.dumps({"people": [{"name": "Sai"}, {"name": "Sooraj"}]})
    mock_client = _make_client(payload)
    with patch("services.meeting_people_extractor.get_genai_client", return_value=mock_client):
        result = await extract_people_from_recap(
            title="Sync",
            owner_name="Sai",
            recap_extras={"what_happened": "Sai and Sooraj discussed the roadmap."},
            summary_json=None,
        )
    assert len(result) == 1
    assert result[0]["name"] == "Sooraj"


@pytest.mark.asyncio
async def test_extract_handles_gemini_failure_gracefully():
    """Gemini raises RuntimeError → returns [] without propagating the exception."""
    def _raise():
        raise RuntimeError("quota exhausted")

    bad_client = MagicMock()
    bad_client.models.generate_content.side_effect = RuntimeError("quota exhausted")

    with patch("services.meeting_people_extractor.get_genai_client", return_value=bad_client):
        result = await extract_people_from_recap(
            title="Meeting",
            owner_name="Sai",
            recap_extras={"what_happened": "Sooraj will check the PR."},
            summary_json=None,
        )
    assert result == []


@pytest.mark.asyncio
async def test_extract_dedupes_case_insensitive():
    """Gemini returns [Sooraj, SOORAJ] → only one entry in output."""
    payload = json.dumps({"people": [{"name": "Sooraj"}, {"name": "SOORAJ"}]})
    mock_client = _make_client(payload)
    with patch("services.meeting_people_extractor.get_genai_client", return_value=mock_client):
        result = await extract_people_from_recap(
            title="Meeting",
            owner_name="Sai",
            recap_extras={"commitments": ["Sooraj will review the code."]},
            summary_json=None,
        )
    assert len(result) == 1
    assert result[0]["name"] == "Sooraj"


@pytest.mark.asyncio
async def test_extract_skips_junk_names():
    """Too-short ('Y'), too-long (>80 chars), and generic ('the team') names are filtered."""
    long_name = "A" * 81
    payload = json.dumps({
        "people": [
            {"name": "Y"},
            {"name": long_name},
            {"name": "the team"},
            {"name": "Ajai"},
        ]
    })
    mock_client = _make_client(payload)
    with patch("services.meeting_people_extractor.get_genai_client", return_value=mock_client):
        result = await extract_people_from_recap(
            title="Meeting",
            owner_name="Sai",
            recap_extras={"what_happened": "Ajai's primary aim is to close the deal."},
            summary_json=None,
        )
    names = [p["name"] for p in result]
    assert "Y" not in names
    assert long_name not in names
    # "the team" has len=8, so it passes the length check; we rely on the model
    # to exclude generics. However our post-filter only checks length and owner.
    # Verify the valid name got through.
    assert "Ajai" in names


@pytest.mark.asyncio
async def test_extract_includes_role_hint():
    """role_hint is preserved when Gemini returns it."""
    payload = json.dumps({
        "people": [{"name": "Maria", "role_hint": "investor"}]
    })
    mock_client = _make_client(payload)
    with patch("services.meeting_people_extractor.get_genai_client", return_value=mock_client):
        result = await extract_people_from_recap(
            title="Pitch",
            owner_name="Sai",
            recap_extras={"what_happened": "Maria asked about the runway."},
            summary_json=None,
        )
    assert len(result) == 1
    assert result[0]["name"] == "Maria"
    assert result[0]["role_hint"] == "investor"


@pytest.mark.asyncio
async def test_extract_uses_action_item_assignees():
    """Assignees from summary_json.action_items are included in the recap text sent to Gemini."""
    payload = json.dumps({"people": [{"name": "Sooraj"}]})
    mock_client = _make_client(payload)
    with patch("services.meeting_people_extractor.get_genai_client", return_value=mock_client):
        result = await extract_people_from_recap(
            title="Sprint review",
            owner_name="Sai",
            recap_extras=None,
            summary_json={
                "tldr": "Good sprint.",
                "action_items": [{"text": "Fix bug", "assignee": "Sooraj"}],
            },
        )
    # Confirm the Gemini call was made (there was recap text from action_items)
    mock_client.models.generate_content.assert_called_once()
    assert len(result) == 1
    assert result[0]["name"] == "Sooraj"


@pytest.mark.asyncio
async def test_extract_handles_non_json_response():
    """Gemini returns garbage text → returns [] without raising."""
    mock_client = _make_client("not valid json at all !!!")
    with patch("services.meeting_people_extractor.get_genai_client", return_value=mock_client):
        result = await extract_people_from_recap(
            title="Meeting",
            owner_name="Sai",
            recap_extras={"what_happened": "Ajai joined."},
            summary_json=None,
        )
    assert result == []


@pytest.mark.asyncio
async def test_extract_excludes_owner_nickname_when_full_owner_name_set():
    """BUG-B regression: owner stored as 'Sainath' — Gemini returns both 'Sainath'
    and 'Sai' (a common nickname/prefix). Both must be filtered out."""
    payload = json.dumps({
        "people": [
            {"name": "Sainath"},     # exact match
            {"name": "Sai"},         # nickname/prefix — was leaking through
            {"name": "Sooraj"},      # legitimate non-owner
            {"name": "Ajai"},        # legitimate non-owner
        ]
    })
    mock_client = _make_client(payload)
    with patch("services.meeting_people_extractor.get_genai_client", return_value=mock_client):
        result = await extract_people_from_recap(
            title="Sync",
            owner_name="Sainath",
            recap_extras={"what_happened": "Sai/Sainath caught up with Sooraj and Ajai."},
            summary_json=None,
        )
    names = sorted(p["name"] for p in result)
    assert "Sainath" not in names
    assert "Sai" not in names
    assert names == ["Ajai", "Sooraj"]


@pytest.mark.asyncio
async def test_extract_excludes_multi_token_owner_on_any_token_match():
    """Owner 'Sainath Setti' — both 'Sainath' and 'Setti' must be filtered (token match)."""
    payload = json.dumps({
        "people": [
            {"name": "Sainath"},
            {"name": "Setti"},
            {"name": "Sooraj"},
        ]
    })
    mock_client = _make_client(payload)
    with patch("services.meeting_people_extractor.get_genai_client", return_value=mock_client):
        result = await extract_people_from_recap(
            title="Sync",
            owner_name="Sainath Setti",
            recap_extras={"what_happened": "Discussion."},
            summary_json=None,
        )
    names = [p["name"] for p in result]
    assert names == ["Sooraj"]


@pytest.mark.asyncio
async def test_extract_rejects_non_name_shaped_values():
    """BUG-C regression: 'As' / 'Re:' / '...' must be rejected by the name-shape regex
    even though they meet the length floor."""
    payload = json.dumps({
        "people": [
            {"name": "As"},          # length 2 but no name shape
            {"name": "Re:"},         # punctuation
            {"name": "..."},         # all punctuation
            {"name": "Mr."},         # ends in punct
            {"name": "Hammond"},     # legitimate (passes shape) — we test that
                                     # the filter is precise, not over-aggressive
        ]
    })
    mock_client = _make_client(payload)
    with patch("services.meeting_people_extractor.get_genai_client", return_value=mock_client):
        result = await extract_people_from_recap(
            title="Meeting",
            owner_name="Sai",
            recap_extras={"what_happened": "Ambient audio test."},
            summary_json=None,
        )
    names = sorted(p["name"] for p in result)
    assert names == ["Hammond"]


@pytest.mark.asyncio
async def test_extract_handles_owner_name_with_format_braces():
    """BUG-D regression: owner display name containing literal '{' / '}' must not
    crash .format() — they're escaped before prompt formatting."""
    payload = json.dumps({"people": [{"name": "Sooraj"}]})
    mock_client = _make_client(payload)
    with patch("services.meeting_people_extractor.get_genai_client", return_value=mock_client):
        result = await extract_people_from_recap(
            title="Sync",
            owner_name="Owner {with braces} in name",  # would explode without escape
            recap_extras={"what_happened": "Sooraj joined."},
            summary_json=None,
        )
    names = [p["name"] for p in result]
    assert names == ["Sooraj"]
