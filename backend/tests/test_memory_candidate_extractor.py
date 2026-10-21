import pytest
from unittest.mock import MagicMock, AsyncMock, patch


@pytest.mark.asyncio
async def test_extracts_candidates_from_recap():
    fake_resp = MagicMock()
    fake_resp.text = '{"candidates":[{"kind":"preference","subject":"Maria","predicate":"prefers async updates","text":"Maria prefers async updates","confidence":0.8}]}'
    with patch("services.memory_candidate_extractor.run_with_budget", new_callable=AsyncMock, return_value=fake_resp):
        from services.memory_candidate_extractor import extract_memory_candidates
        out = await extract_memory_candidates(
            tenant_id="t", twin_id="tw", meeting_id="m",
            owner_name="Sai",
            recap_extras={"what_happened": "Maria said she prefers async updates"},
            summary_json={"tldr": "Sync with Maria"},
        )
    assert len(out) == 1
    assert out[0]["subject"] == "Maria"
    assert out[0]["kind"] == "preference"
    assert out[0]["confidence"] == 0.8


@pytest.mark.asyncio
async def test_returns_empty_on_gemini_failure():
    with patch("services.memory_candidate_extractor.run_with_budget", new_callable=AsyncMock, side_effect=Exception("api error")):
        from services.memory_candidate_extractor import extract_memory_candidates
        out = await extract_memory_candidates(
            tenant_id="t", twin_id="tw", meeting_id="m",
            owner_name="Sai", recap_extras={}, summary_json={},
        )
    assert out == []


@pytest.mark.asyncio
async def test_filters_low_confidence():
    fake_resp = MagicMock()
    fake_resp.text = '{"candidates":[{"kind":"fact","subject":"x","predicate":"y","text":"z","confidence":0.3}]}'
    with patch("services.memory_candidate_extractor.run_with_budget", new_callable=AsyncMock, return_value=fake_resp):
        from services.memory_candidate_extractor import extract_memory_candidates
        out = await extract_memory_candidates(
            tenant_id="t", twin_id="tw", meeting_id="m",
            owner_name="Sai", recap_extras={"what_happened": "something"}, summary_json={},
        )
    assert out == []
