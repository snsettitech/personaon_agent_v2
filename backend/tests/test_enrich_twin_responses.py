"""Tests for _process_enrich_twin_responses worker job."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from modules.graph_outbox_worker import _process_enrich_twin_responses

_JOB = {
    "id": "job-enrich-1",
    "tenant_id": "tenant-1",
    "twin_id": "twin-111",
    "payload": {"meeting_id": "meeting-aaa"},
}

_RESPONSE_ROWS = [
    {"id": "r1", "turn_seq": 1, "response_text": "I approach this by first principles.", "is_deferral": False},
    {"id": "r2", "turn_seq": 2, "response_text": "I don't have information on that.", "is_deferral": True},
    {"id": "r3", "turn_seq": 3, "response_text": "Focus on execution speed.", "is_deferral": False},
]

_VECTOR_HITS = [
    {"text": "Chunk A about principles", "score": 0.85, "source_id": "src-1", "filename": "bio.pdf", "url": ""},
    {"text": "Chunk B about strategy",   "score": 0.78, "source_id": "src-2", "filename": "talk.pdf", "url": ""},
    {"text": "Chunk C about speed",      "score": 0.72, "source_id": "src-3", "filename": "essay.pdf", "url": ""},
]


class TestEnrichTwinResponses:

    @pytest.mark.asyncio
    async def test_enriches_non_deferral_rows(self):
        non_deferrals = [r for r in _RESPONSE_ROWS if not r["is_deferral"]]
        with (
            patch("modules.graph_outbox_worker.supabase") as mock_sb,
            patch("modules.graph_outbox_worker.vector_search", new_callable=AsyncMock, return_value=_VECTOR_HITS),
        ):
            mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = non_deferrals
            mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()
            result = await _process_enrich_twin_responses(_JOB)

        assert result is True
        assert mock_sb.table.return_value.update.call_count == 2

    @pytest.mark.asyncio
    async def test_confidence_is_mean_of_scores(self):
        non_deferrals = [_RESPONSE_ROWS[0]]
        captured_updates = []

        with (
            patch("modules.graph_outbox_worker.supabase") as mock_sb,
            patch("modules.graph_outbox_worker.vector_search", new_callable=AsyncMock, return_value=_VECTOR_HITS),
        ):
            mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = non_deferrals

            def capture_update(data):
                captured_updates.append(data)
                return mock_sb.table.return_value.update.return_value

            mock_sb.table.return_value.update.side_effect = capture_update
            mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

            await _process_enrich_twin_responses(_JOB)

        expected_confidence = round(sum(h["score"] for h in _VECTOR_HITS) / len(_VECTOR_HITS), 4)
        assert captured_updates[0]["confidence"] == expected_confidence

    @pytest.mark.asyncio
    async def test_no_vector_hits_leaves_confidence_null(self):
        non_deferrals = [_RESPONSE_ROWS[0]]
        captured_updates = []

        with (
            patch("modules.graph_outbox_worker.supabase") as mock_sb,
            patch("modules.graph_outbox_worker.vector_search", new_callable=AsyncMock, return_value=[]),
        ):
            mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = non_deferrals

            def capture_update(data):
                captured_updates.append(data)
                return mock_sb.table.return_value.update.return_value

            mock_sb.table.return_value.update.side_effect = capture_update
            mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

            await _process_enrich_twin_responses(_JOB)

        assert captured_updates[0]["confidence"] is None
        assert captured_updates[0]["sources"] is None

    @pytest.mark.asyncio
    async def test_missing_meeting_id_returns_true(self):
        result = await _process_enrich_twin_responses({"id": "j1", "payload": {}})
        assert result is True
