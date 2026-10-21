"""Tests for /v2/twins/{twin_id}/search endpoint."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from routers import twins_search as search_router

TWIN_ID = "twin-abc"
USER = {"user_id": "user-1", "tenant_id": "tenant-1"}

FIXTURE_RESULTS = {
    "people": [{"id": "p1", "name": "Alice", "email": "alice@example.com"}],
    "meetings": [{"id": "m1", "title": "Standup"}],
    "commitments": [
        {"id": "c1", "text": "Send report", "direction": "you_owe", "meeting_id": None}
    ],
    "memories": [{"id": "mem1", "text": "Likes jazz", "subject": "Alice"}],
}

EMPTY_RESULTS: dict = {"people": [], "meetings": [], "commitments": [], "memories": []}


class TestSearchHandler:
    @pytest.mark.asyncio
    async def test_returns_grouped_results(self):
        with (
            patch(
                "routers.twins_search.verify_twin_ownership", return_value=None
            ),
            patch(
                "routers.twins_search.search_all",
                return_value=FIXTURE_RESULTS,
            ) as mock_search,
        ):
            result = await search_router.search(
                twin_id=TWIN_ID, q="alice", user=USER
            )

        assert result["people"][0]["name"] == "Alice"
        assert result["meetings"][0]["title"] == "Standup"
        assert result["commitments"][0]["text"] == "Send report"
        assert result["memories"][0]["subject"] == "Alice"
        mock_search.assert_called_once_with(TWIN_ID, "alice")

    @pytest.mark.asyncio
    async def test_empty_results_shape(self):
        with (
            patch("routers.twins_search.verify_twin_ownership", return_value=None),
            patch(
                "routers.twins_search.search_all", return_value=EMPTY_RESULTS
            ),
        ):
            result = await search_router.search(
                twin_id=TWIN_ID, q="nomatch", user=USER
            )

        for key in ("people", "meetings", "commitments", "memories"):
            assert result[key] == []

    @pytest.mark.asyncio
    async def test_whitespace_only_q_returns_empty(self):
        """A query that strips to empty should short-circuit before calling search_all."""
        with (
            patch("routers.twins_search.verify_twin_ownership", return_value=None),
            patch(
                "routers.twins_search.search_all", return_value=EMPTY_RESULTS
            ) as mock_search,
        ):
            result = await search_router.search(
                twin_id=TWIN_ID, q="   ", user=USER
            )

        assert result == EMPTY_RESULTS
        mock_search.assert_not_called()

    @pytest.mark.asyncio
    async def test_unauthenticated_raises_401(self):
        """Passing user=None should trigger verify_owner's 401."""
        with pytest.raises(HTTPException) as exc:
            await search_router.search(twin_id=TWIN_ID, q="x", user=None)
        assert exc.value.status_code == 401

    @pytest.mark.asyncio
    async def test_ownership_check_called(self):
        """verify_twin_ownership must be invoked with correct args."""
        with (
            patch(
                "routers.twins_search.verify_twin_ownership"
            ) as mock_ownership,
            patch(
                "routers.twins_search.search_all", return_value=FIXTURE_RESULTS
            ),
        ):
            await search_router.search(twin_id=TWIN_ID, q="x", user=USER)

        mock_ownership.assert_called_once_with(TWIN_ID, USER)
