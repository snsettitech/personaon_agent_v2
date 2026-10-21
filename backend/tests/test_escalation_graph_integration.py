"""
Tests for Escalation Graph Integration (Phase 2)

Verifies that:
1. Escalation resolve enqueues outbox jobs without blocking
2. Jobs are created with proper idempotency keys
3. Returns successfully when graph/extractor are down
4. Outbox is created for background processing
"""

import pytest
from unittest.mock import MagicMock, patch

from modules.escalation_graph_integration import (
    enqueue_escalation_graph_jobs,
    check_escalation_graph_status
)
from modules.graph_outbox import GraphOperationType


class TestEscalationGraphEnqueue:
    """Test async outbox job enqueueing for escalations."""

    @pytest.mark.asyncio
    async def test_enqueues_all_three_jobs(self):
        """Should enqueue episode, claim extraction, and contradiction jobs."""
        with patch('modules.escalation_graph_integration.GraphMemoryCore') as mock_core:
            mock_outbox = MagicMock()
            mock_outbox.submit = MagicMock(return_value="job-123")

            mock_client = MagicMock()
            mock_client.outbox = mock_outbox
            mock_core.return_value = mock_client

            result = await enqueue_escalation_graph_jobs(
                tenant_id="tenant-1",
                twin_id="twin-1",
                escalation_id="esc-123",
                question="What is the answer?",
                answer="The answer is 42.",
                owner_id="owner-1"
            )

            assert result["escalation_episode_job"] == "job-123"
            assert result["claim_extraction_job"] == "job-123"
            assert result["contradiction_eval_job"] == "job-123"
            assert len(result["errors"]) == 0

    @pytest.mark.asyncio
    async def test_uses_idempotency_keys(self):
        """Should use deterministic idempotency keys for deduplication."""
        with patch('modules.escalation_graph_integration.GraphMemoryCore') as mock_core:
            mock_outbox = MagicMock()
            submitted_jobs = []

            def capture_submit(*args, **kwargs):
                submitted_jobs.append(kwargs.get('idempotency_key'))
                return f"job-{len(submitted_jobs)}"

            mock_outbox.submit = capture_submit

            mock_client = MagicMock()
            mock_client.outbox = mock_outbox
            mock_core.return_value = mock_client

            await enqueue_escalation_graph_jobs(
                tenant_id="tenant-1",
                twin_id="twin-1",
                escalation_id="esc-123",
                question="What?",
                answer="Answer.",
                owner_id="owner-1"
            )

            # Each job should have a unique idempotency key
            assert len(submitted_jobs) == 3
            assert all(key is not None for key in submitted_jobs)
            # Keys should be deterministic (same input = same key)
            assert submitted_jobs[0].startswith("escalation_episode:")
            assert submitted_jobs[1].startswith("claim_extract:")
            assert submitted_jobs[2].startswith("contradiction_eval:")

    @pytest.mark.asyncio
    async def test_same_escalation_same_idempotency_key(self):
        """Same escalation should generate same idempotency keys (idempotent)."""
        with patch('modules.escalation_graph_integration.GraphMemoryCore') as mock_core:
            mock_outbox = MagicMock()
            submitted_keys = []

            def capture_submit(*args, **kwargs):
                submitted_keys.append(kwargs.get('idempotency_key'))
                return f"job-{len(submitted_keys)}"

            mock_outbox.submit = capture_submit

            mock_client = MagicMock()
            mock_client.outbox = mock_outbox
            mock_core.return_value = mock_client

            # Call twice with same parameters
            await enqueue_escalation_graph_jobs(
                tenant_id="tenant-1",
                twin_id="twin-1",
                escalation_id="esc-123",
                question="What?",
                answer="Answer.",
                owner_id="owner-1"
            )

            first_keys = list(submitted_keys)
            submitted_keys.clear()

            await enqueue_escalation_graph_jobs(
                tenant_id="tenant-1",
                twin_id="twin-1",
                escalation_id="esc-123",
                question="What?",
                answer="Answer.",
                owner_id="owner-1"
            )

            second_keys = list(submitted_keys)

            # Keys should be identical (idempotent)
            assert first_keys == second_keys

    @pytest.mark.asyncio
    async def test_returns_successfully_when_outbox_down(self):
        """Should return successfully even if outbox submission fails."""
        with patch('modules.escalation_graph_integration.GraphMemoryCore') as mock_core:
            mock_outbox = MagicMock()
            mock_outbox.submit = MagicMock(side_effect=Exception("Redis connection failed"))

            mock_client = MagicMock()
            mock_client.outbox = mock_outbox
            mock_core.return_value = mock_client

            # Should not raise exception
            result = await enqueue_escalation_graph_jobs(
                tenant_id="tenant-1",
                twin_id="twin-1",
                escalation_id="esc-123",
                question="What?",
                answer="Answer.",
                owner_id="owner-1"
            )

            # Should record errors but not crash
            assert len(result["errors"]) > 0
            assert "episode_job_failed" in str(result["errors"])

    @pytest.mark.asyncio
    async def test_partial_failure_graceful(self):
        """Should handle partial failures gracefully (some jobs succeed)."""
        with patch('modules.escalation_graph_integration.GraphMemoryCore') as mock_core:
            mock_outbox = MagicMock()
            call_count = [0]

            def conditional_fail(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 2:  # Second call fails
                    raise Exception("Outbox full")
                return f"job-{call_count[0]}"

            mock_outbox.submit = conditional_fail

            mock_client = MagicMock()
            mock_client.outbox = mock_outbox
            mock_core.return_value = mock_client

            result = await enqueue_escalation_graph_jobs(
                tenant_id="tenant-1",
                twin_id="twin-1",
                escalation_id="esc-123",
                question="What?",
                answer="Answer.",
                owner_id="owner-1"
            )

            # First job succeeded, second failed, third may or may not have run
            assert result["escalation_episode_job"] == "job-1"
            assert len(result["errors"]) >= 1


class TestEscalationJobTypes:
    """Test correct job types are enqueued."""

    @pytest.mark.asyncio
    async def test_episode_job_type(self):
        """Should enqueue CREATE_EPISODE for escalation."""
        with patch('modules.escalation_graph_integration.GraphMemoryCore') as mock_core:
            mock_outbox = MagicMock()
            job_types = []

            def capture_type(*args, **kwargs):
                job_types.append(kwargs.get('operation'))
                return "job-123"

            mock_outbox.submit = capture_type

            mock_client = MagicMock()
            mock_client.outbox = mock_outbox
            mock_core.return_value = mock_client

            await enqueue_escalation_graph_jobs(
                tenant_id="tenant-1",
                twin_id="twin-1",
                escalation_id="esc-123",
                question="What?",
                answer="Answer.",
                owner_id="owner-1"
            )

            assert GraphOperationType.CREATE_EPISODE in job_types
            assert GraphOperationType.EXTRACT_CLAIMS in job_types
            assert GraphOperationType.EVALUATE_CONTRADICTIONS in job_types

    @pytest.mark.asyncio
    async def test_episode_payload_structure(self):
        """Episode job should have correct payload structure."""
        with patch('modules.escalation_graph_integration.GraphMemoryCore') as mock_core:
            mock_outbox = MagicMock()
            payloads = []

            def capture_payload(*args, **kwargs):
                payloads.append(kwargs.get('payload'))
                return "job-123"

            mock_outbox.submit = capture_payload

            mock_client = MagicMock()
            mock_client.outbox = mock_outbox
            mock_core.return_value = mock_client

            await enqueue_escalation_graph_jobs(
                tenant_id="tenant-1",
                twin_id="twin-1",
                escalation_id="esc-123",
                question="What is the meaning?",
                answer="The meaning is 42.",
                owner_id="owner-1"
            )

            # Find episode payload
            episode_payload = None
            for p in payloads:
                if p.get('source_type') == 'escalation_resolution':
                    episode_payload = p
                    break

            assert episode_payload is not None
            assert "name" in episode_payload
            assert "body" in episode_payload
            assert "What is the meaning?" in episode_payload["body"]
            assert "The meaning is 42." in episode_payload["body"]
            assert episode_payload["source_ref"] == "esc-123"
            assert "metadata" in episode_payload


class TestEscalationStatusCheck:
    """Test status checking for escalation graph jobs."""

    def test_status_check_returns_outbox_stats(self):
        """Status check should return outbox statistics."""
        with patch('modules.escalation_graph_integration.GraphMemoryCore') as mock_core:
            mock_outbox = MagicMock()
            mock_outbox.get_stats = MagicMock(return_value={
                "pending": 5,
                "processing": 2,
                "completed": 10,
                "failed": 1
            })

            mock_client = MagicMock()
            mock_client.outbox = mock_outbox
            mock_core.return_value = mock_client

            status = check_escalation_graph_status(
                tenant_id="tenant-1",
                twin_id="twin-1",
                escalation_id="esc-123"
            )

            assert status["escalation_id"] == "esc-123"
            assert status["outbox_pending"] == 5
            assert status["outbox_processing"] == 2
            assert status["outbox_completed"] == 10
            assert status["outbox_failed"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
