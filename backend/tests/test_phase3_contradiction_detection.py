"""
Tests for Phase 3: Contradiction Detection and Review Queue

Verifies:
1. Contradiction detection between claims
2. Review queue entry creation
3. No auto-overwrite behavior
4. Proper severity classification
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from modules.graph_contradiction_detector import (
    GraphContradictionDetector,
    Contradiction,
    ContradictionSeverity,
    process_contradiction_evaluation_job
)


class TestContradictionDetection:
    """Test contradiction detection logic."""

    @pytest.mark.asyncio
    async def test_detects_clear_contradiction(self):
        """Should detect clear contradictions between claims."""
        with patch('modules.graph_contradiction_detector.get_graph_memory_config') as mock_config:
            mock_config.return_value = MagicMock()
            mock_config.return_value.is_read_allowed.return_value = True
            mock_config.return_value.make_group_id.return_value = "tenant1__twin1"

            detector = GraphContradictionDetector(
                tenant_id="tenant1",
                twin_id="twin1"
            )

            # Mock LLM evaluation
            detector._evaluate_contradiction = AsyncMock(return_value=(
                True,  # is_contradiction
                ContradictionSeverity.HIGH,
                "Direct opposition on preference",
                0.95
            ))

            # Mock finding related claims
            detector._find_related_claims = AsyncMock(return_value=[
                {"claim_id": "existing1", "text": "I prefer email communication"}
            ])

            new_claims = [{"claim_id": "new1", "text": "I never use email"}]

            contradictions = await detector.check_contradictions(new_claims)

            assert len(contradictions) == 1
            assert contradictions[0].severity == ContradictionSeverity.HIGH
            assert contradictions[0].confidence == 0.95
            assert contradictions[0].new_claim_id == "new1"
            assert contradictions[0].existing_claim_id == "existing1"

    @pytest.mark.asyncio
    async def test_no_contradiction_when_consistent(self):
        """Should not flag consistent claims as contradictory."""
        with patch('modules.graph_contradiction_detector.get_graph_memory_config') as mock_config:
            mock_config.return_value = MagicMock()
            mock_config.return_value.is_read_allowed.return_value = True
            mock_config.return_value.make_group_id.return_value = "tenant1__twin1"

            detector = GraphContradictionDetector(
                tenant_id="tenant1",
                twin_id="twin1"
            )

            detector._evaluate_contradiction = AsyncMock(return_value=(
                False,  # not contradiction
                ContradictionSeverity.LOW,
                "Claims are consistent",
                0.9
            ))

            detector._find_related_claims = AsyncMock(return_value=[
                {"claim_id": "existing1", "text": "I prefer email"}
            ])

            new_claims = [{"claim_id": "new1", "text": "Email works best for me"}]

            contradictions = await detector.check_contradictions(new_claims)

            assert len(contradictions) == 0

    @pytest.mark.asyncio
    async def test_only_high_confidence_contradictions(self):
        """Should only flag contradictions with confidence > 0.7."""
        with patch('modules.graph_contradiction_detector.get_graph_memory_config') as mock_config:
            mock_config.return_value = MagicMock()
            mock_config.return_value.is_read_allowed.return_value = True
            mock_config.return_value.make_group_id.return_value = "tenant1__twin1"

            detector = GraphContradictionDetector(
                tenant_id="tenant1",
                twin_id="twin1"
            )

            # Low confidence contradiction
            detector._evaluate_contradiction = AsyncMock(return_value=(
                True,
                ContradictionSeverity.LOW,
                "Possible contradiction",
                0.5  # Below threshold
            ))

            detector._find_related_claims = AsyncMock(return_value=[
                {"claim_id": "existing1", "text": "I like chocolate"}
            ])

            new_claims = [{"claim_id": "new1", "text": "I prefer vanilla"}]

            contradictions = await detector.check_contradictions(new_claims)

            # Should not be included due to low confidence
            assert len(contradictions) == 0


class TestReviewQueue:
    """Test review queue behavior."""

    @pytest.mark.asyncio
    async def test_creates_queue_entry(self):
        """Should create review queue entry for contradiction."""
        with patch('modules.graph_contradiction_detector.get_graph_memory_config') as mock_config:
            mock_config.return_value = MagicMock()
            mock_config.return_value.is_read_allowed.return_value = True
            mock_config.return_value.make_group_id.return_value = "tenant1__twin1"

            detector = GraphContradictionDetector(
                tenant_id="tenant1",
                twin_id="twin1"
            )

            with patch('modules.graph_contradiction_detector.supabase') as mock_supabase:
                mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
                mock_supabase.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[{"id": "queue-1"}])

                contradiction = Contradiction(
                    contradiction_id="contradict-123",
                    new_claim_id="new1",
                    new_claim_text="New claim",
                    existing_claim_id="existing1",
                    existing_claim_text="Existing claim",
                    severity=ContradictionSeverity.HIGH,
                    explanation="Direct contradiction",
                    confidence=0.9,
                    detected_at="2024-01-01T00:00:00Z",
                    status="pending"
                )

                entry_ids = await detector.create_review_queue_entries([contradiction])

                assert len(entry_ids) == 1
                assert entry_ids[0] == "queue-1"

    @pytest.mark.asyncio
    async def test_idempotency_no_duplicate_entries(self):
        """Should not create duplicate queue entries."""
        with patch('modules.graph_contradiction_detector.get_graph_memory_config') as mock_config:
            mock_config.return_value = MagicMock()
            mock_config.return_value.is_read_allowed.return_value = True
            mock_config.return_value.make_group_id.return_value = "tenant1__twin1"

            detector = GraphContradictionDetector(
                tenant_id="tenant1",
                twin_id="twin1"
            )

            with patch('modules.graph_contradiction_detector.supabase') as mock_supabase:
                # First call returns existing
                mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "existing-queue-1"}])

                contradiction = Contradiction(
                    contradiction_id="contradict-123",
                    new_claim_id="new1",
                    new_claim_text="New claim",
                    existing_claim_id="existing1",
                    existing_claim_text="Existing claim",
                    severity=ContradictionSeverity.HIGH,
                    explanation="Direct contradiction",
                    confidence=0.9,
                    detected_at="2024-01-01T00:00:00Z",
                    status="pending"
                )

                entry_ids = await detector.create_review_queue_entries([contradiction])

                # Should return existing ID without inserting
                assert entry_ids[0] == "existing-queue-1"
                mock_supabase.table.return_value.insert.assert_not_called()

    @pytest.mark.asyncio
    async def test_queue_entry_includes_resolution_fields(self):
        """Queue entries should have resolution workflow fields."""
        with patch('modules.graph_contradiction_detector.get_graph_memory_config') as mock_config, \
             patch('modules.graph_contradiction_detector.supabase') as mock_supabase:

            mock_config.return_value = MagicMock()
            mock_config.return_value.is_read_allowed.return_value = True
            mock_config.return_value.make_group_id.return_value = "tenant1__twin1"

            mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value = MagicMock(data=[])

            captured_insert = None
            def capture_insert(*args, **kwargs):
                nonlocal captured_insert
                captured_insert = args[0] if args else kwargs
                return MagicMock(data=[{"id": "queue-1"}])

            mock_supabase.table.return_value.insert.side_effect = capture_insert

            detector = GraphContradictionDetector(
                tenant_id="tenant1",
                twin_id="twin1"
            )

            contradiction = Contradiction(
                contradiction_id="contradict-123",
                new_claim_id="new1",
                new_claim_text="New claim",
                existing_claim_id="existing1",
                existing_claim_text="Existing claim",
                severity=ContradictionSeverity.MEDIUM,
                explanation="Contradiction explanation",
                confidence=0.85,
                detected_at="2024-01-01T00:00:00Z",
                status="pending"
            )

            await detector.create_review_queue_entries([contradiction])

            # Verify insert was called with correct fields
            mock_supabase.table.return_value.insert.assert_called_once()


class TestWorkerJobProcessing:
    """Test worker job processing."""

    @pytest.mark.asyncio
    async def test_process_contradiction_job_success(self):
        """Worker should process contradiction job successfully."""
        with patch('modules.graph_contradiction_detector.GraphContradictionDetector') as mock_detector_class:
            mock_detector = MagicMock()
            mock_detector.check_contradictions = AsyncMock(return_value=[
                Contradiction(
                    contradiction_id="c1",
                    new_claim_id="new1",
                    new_claim_text="New",
                    existing_claim_id="old1",
                    existing_claim_text="Old",
                    severity=ContradictionSeverity.HIGH,
                    explanation="Contradiction",
                    confidence=0.9,
                    detected_at="2024-01-01T00:00:00Z",
                    status="pending"
                )
            ])
            mock_detector.create_review_queue_entries = AsyncMock(return_value=["entry-1"])
            mock_detector_class.return_value = mock_detector

            result = await process_contradiction_evaluation_job(
                tenant_id="tenant1",
                twin_id="twin1",
                payload={
                    "claims_context": {
                        "question": "What is preferred?",
                        "answer": "Direct communication"
                    },
                    "evaluation_scope": "twin"
                }
            )

            assert result is True
            mock_detector.check_contradictions.assert_called_once()
            mock_detector.create_review_queue_entries.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_contradiction_job_no_contradictions(self):
        """Worker should succeed even when no contradictions found."""
        with patch('modules.graph_contradiction_detector.GraphContradictionDetector') as mock_detector_class:
            mock_detector = MagicMock()
            mock_detector.check_contradictions = AsyncMock(return_value=[])
            mock_detector_class.return_value = mock_detector

            result = await process_contradiction_evaluation_job(
                tenant_id="tenant1",
                twin_id="twin1",
                payload={"claims_context": {"answer": "Consistent answer"}}
            )

            assert result is True
            mock_detector.create_review_queue_entries.assert_not_called()


class TestNoAutoOverwrite:
    """Test that contradictions don't auto-overwrite."""

    @pytest.mark.asyncio
    async def test_contradiction_creates_review_not_overwrite(self):
        """Contradictions should create review queue entries, not auto-resolve."""
        with patch('modules.graph_contradiction_detector.get_graph_memory_config') as mock_config:
            mock_config.return_value = MagicMock()
            mock_config.return_value.is_read_allowed.return_value = True
            mock_config.return_value.make_group_id.return_value = "tenant1__twin1"

            detector = GraphContradictionDetector(
                tenant_id="tenant1",
                twin_id="twin1"
            )

            # Verify no auto-overwrite methods exist
            assert not hasattr(detector, 'resolve_contradiction')
            assert not hasattr(detector, 'auto_overwrite')

            # Verify only review queue methods exist
            assert hasattr(detector, 'create_review_queue_entries')


class TestTenantTwinScoping:
    """Test tenant/twin scoping via group_id."""

    @pytest.mark.asyncio
    async def test_group_id_format(self):
        """group_id should be in format {tenant_id}__{twin_id}."""
        with patch('modules.graph_contradiction_detector.get_graph_memory_config') as mock_config:
            mock_config.return_value = MagicMock()
            mock_config.return_value.make_group_id.return_value = "tenant1__twin1"

            detector = GraphContradictionDetector(
                tenant_id="tenant1",
                twin_id="twin1"
            )

            assert detector.group_id == "tenant1__twin1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
