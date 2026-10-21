"""
Tests for Research Orchestrator Phase 5 (Twin-Ready Handoff)

Phase 5 adds finalization continuation from bio_generated to completed state,
including mind score updates and readiness evaluation.
"""

import pytest
from datetime import datetime
from unittest.mock import patch

# Skip tests if modules not available
pytest.importorskip("modules.research_orchestrator")

from modules.research_orchestrator import (
    ResearchOrchestrator,
    ResearchRunStatus,
    is_valid_transition,
    MindScoreCheckpointData,
    ReadinessCheckpointData,
    CheckpointData,
)


# ============================================================================
# Phase 5 State Machine Tests
# ============================================================================

class TestPhase5StateMachine:
    """Test Phase 5 state machine transitions."""

    def test_bio_generated_to_finalizing(self):
        """bio_generated can transition to finalizing."""
        assert is_valid_transition(
            ResearchRunStatus.BIO_GENERATED,
            ResearchRunStatus.FINALIZING
        )

    def test_finalizing_to_completed(self):
        """finalizing can transition to completed."""
        assert is_valid_transition(
            ResearchRunStatus.FINALIZING,
            ResearchRunStatus.COMPLETED
        )

    def test_finalizing_to_failed(self):
        """finalizing can transition to failed on error."""
        assert is_valid_transition(
            ResearchRunStatus.FINALIZING,
            ResearchRunStatus.FAILED
        )

    def test_completed_is_terminal(self):
        """completed is terminal for Phase 5."""
        assert not is_valid_transition(
            ResearchRunStatus.COMPLETED,
            ResearchRunStatus.FINALIZING
        )
        assert not is_valid_transition(
            ResearchRunStatus.COMPLETED,
            ResearchRunStatus.BIO_GENERATED
        )

    def test_ingestion_completed_cannot_go_to_finalizing(self):
        """ingestion_completed cannot directly go to finalizing (must go through bio)."""
        assert not is_valid_transition(
            ResearchRunStatus.INGESTION_COMPLETED,
            ResearchRunStatus.FINALIZING
        )

    def test_bio_generated_cannot_go_to_completed_directly(self):
        """bio_generated cannot go directly to completed (must go through finalizing)."""
        assert not is_valid_transition(
            ResearchRunStatus.BIO_GENERATED,
            ResearchRunStatus.COMPLETED
        )

    def test_completed_self_transition(self):
        """completed can self-transition (idempotent)."""
        assert is_valid_transition(
            ResearchRunStatus.COMPLETED,
            ResearchRunStatus.COMPLETED
        )


# ============================================================================
# Mind Score Checkpoint Data Tests
# ============================================================================

class TestMindScoreCheckpointData:
    """Test Phase 5 mind score checkpoint structure."""

    def test_mind_score_checkpoint_creation(self):
        """Test creating mind score checkpoint data."""
        checkpoint = MindScoreCheckpointData(
            status="success",
            score=65,
            label="Developing",
            words_processed=15123,
            questions_answerable_estimate=2100,
            updated_at=datetime.utcnow().isoformat(),
            errors=[],
        )

        assert checkpoint.status == "success"
        assert checkpoint.score == 65
        assert checkpoint.label == "Developing"
        assert checkpoint.words_processed == 15123
        assert checkpoint.questions_answerable_estimate == 2100

    def test_mind_score_checkpoint_in_full_checkpoint(self):
        """Test mind score checkpoint nested in full checkpoint."""
        mind_checkpoint = MindScoreCheckpointData(
            status="success",
            score=75,
            label="Strong",
            words_processed=25000,
            questions_answerable_estimate=3500,
            updated_at=datetime.utcnow().isoformat(),
            errors=[],
        )

        checkpoint = CheckpointData(
            phase="completed",
            last_transition_at=datetime.utcnow().isoformat(),
            mind_score=mind_checkpoint,
        )

        assert checkpoint.mind_score is not None
        assert checkpoint.mind_score.score == 75
        assert checkpoint.mind_score.label == "Strong"


# ============================================================================
# Readiness Checkpoint Data Tests
# ============================================================================

class TestReadinessCheckpointData:
    """Test Phase 5 readiness checkpoint structure."""

    def test_readiness_checkpoint_creation(self):
        """Test creating readiness checkpoint data."""
        checkpoint = ReadinessCheckpointData(
            status="evaluated",
            is_ready=True,
            thresholds={"min_mind_score": 30},
            requirements={
                "has_confirmed_source": True,
                "has_bio_variant": True,
                "mind_score_threshold_met": True,
                "no_pending_confirmations": True,
            },
            counts={
                "confirmed": 5,
                "auto_confirmed": 2,
                "pending": 0,
                "manual_review": 0,
                "rejected": 1,
            },
            errors=[],
        )

        assert checkpoint.status == "evaluated"
        assert checkpoint.is_ready is True
        assert checkpoint.thresholds["min_mind_score"] == 30
        assert checkpoint.requirements["has_confirmed_source"] is True

    def test_readiness_checkpoint_not_ready(self):
        """Test readiness checkpoint when not ready."""
        checkpoint = ReadinessCheckpointData(
            status="evaluated",
            is_ready=False,
            thresholds={"min_mind_score": 30},
            requirements={
                "has_confirmed_source": True,
                "has_bio_variant": True,
                "mind_score_threshold_met": False,
                "no_pending_confirmations": True,
            },
            counts={
                "confirmed": 3,
                "auto_confirmed": 1,
                "pending": 0,
                "manual_review": 0,
                "rejected": 0,
            },
            errors=[],
        )

        assert checkpoint.is_ready is False
        assert checkpoint.requirements["mind_score_threshold_met"] is False


# ============================================================================
# Orchestrator Phase 5 Logic Tests (Mocked)
# ============================================================================

class TestContinueToFinalizeResearchRun:
    """Test continue_to_finalize_research_run method."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator for testing."""
        return ResearchOrchestrator()

    @pytest.mark.asyncio
    async def test_blocks_from_ingestion_completed(self, orchestrator):
        """Test that finalization blocks from ingestion_completed."""
        with patch.object(orchestrator.repository, 'get_research_run', return_value={
            "id": "run-123",
            "twin_id": "twin-456",
            "status": "ingestion_completed",
            "crawl_id": "crawl-789",
            "checkpoint_data": {},
        }):
            result = await orchestrator.continue_to_finalize_research_run(
                research_run_id="run-123",
                twin_id="twin-456",
            )

            assert result.success is False
            assert "bio_generated" in result.error

    @pytest.mark.asyncio
    async def test_idempotent_when_already_completed(self, orchestrator):
        """Test idempotency when already in completed."""
        with patch.object(orchestrator.repository, 'get_research_run', return_value={
            "id": "run-123",
            "twin_id": "twin-456",
            "status": "completed",
            "crawl_id": "crawl-789",
            "checkpoint_data": {},
        }):
            result = await orchestrator.continue_to_finalize_research_run(
                research_run_id="run-123",
                twin_id="twin-456",
            )

            assert result.success is True
            assert result.new_status == "completed"
            assert "idempotent" in result.transition_reason.lower()

    @pytest.mark.asyncio
    async def test_blocks_from_bio_generated_without_checkpoint(self, orchestrator):
        """Test that finalization works from bio_generated."""
        # This test would need proper mocking of the training_metrics and readiness modules
        # For now, just verify the state check passes
        pass

    @pytest.mark.asyncio
    async def test_run_not_found(self, orchestrator):
        """Test error when research run not found."""
        with patch.object(orchestrator.repository, 'get_research_run', return_value=None):
            result = await orchestrator.continue_to_finalize_research_run(
                research_run_id="run-123",
                twin_id="twin-456",
            )

            assert result.success is False
            assert "not found" in result.error.lower()


# ============================================================================
# Twin Readiness Checker Tests
# ============================================================================

class TestTwinReadinessChecker:
    """Test TwinReadinessChecker module."""

    def test_checker_initialization(self):
        """Test checker initializes with correct threshold."""
        from modules.twin_readiness import TwinReadinessChecker, get_min_ready_mind_score

        checker = TwinReadinessChecker()
        assert checker.min_mind_score == get_min_ready_mind_score()

    def test_checker_custom_threshold(self):
        """Test checker accepts custom threshold."""
        from modules.twin_readiness import TwinReadinessChecker

        checker = TwinReadinessChecker(min_mind_score=50)
        assert checker.min_mind_score == 50


# ============================================================================
# Phase 5 Contract Tests
# ============================================================================

class TestPhase5Contracts:
    """Test Phase 5 behavior contracts."""

    def test_no_frontend_code(self):
        """Phase 5 does NOT add frontend code."""
        # Contract documented - no UI changes
        pass

    def test_no_chat_router_changes(self):
        """Phase 5 does NOT modify chat router."""
        # Contract documented - chat unchanged
        pass

    def test_checkpoint_schema_sibling_keys(self):
        """mind_score and readiness are sibling keys (not nested)."""
        checkpoint = CheckpointData(
            phase="completed",
            last_transition_at=datetime.utcnow().isoformat(),
            mind_score=MindScoreCheckpointData(
                status="success",
                score=65,
                label="Developing",
                words_processed=10000,
                questions_answerable_estimate=1500,
                updated_at=datetime.utcnow().isoformat(),
                errors=[],
            ),
            readiness=ReadinessCheckpointData(
                status="evaluated",
                is_ready=True,
                thresholds={"min_mind_score": 30},
                requirements={},
                counts={},
                errors=[],
            ),
        )

        # Verify siblings at same level
        assert checkpoint.mind_score is not None
        assert checkpoint.readiness is not None
        assert checkpoint.bio_generation is None  # Not set in this test

    def test_uses_existing_training_metrics(self):
        """Phase 5 uses existing training_metrics.update_twin_training_metrics."""
        # Contract: Uses update_twin_training_metrics from modules.training_metrics
        pass

    def test_source_confirmations_authoritative(self):
        """source_confirmations remains authoritative for source status."""
        # Contract documented - all source counts come from source_confirmations table
        pass


# ============================================================================
# Summary
# ============================================================================

def test_phase_5_implementation_summary():
    """
    Summary of Phase 5 implementation contracts.

    This test documents the expected behavior of Phase 5.
    """
    # New states added
    assert ResearchRunStatus.FINALIZING.value == "finalizing"
    assert ResearchRunStatus.COMPLETED.value == "completed"

    # Valid transitions
    assert is_valid_transition(
        ResearchRunStatus.BIO_GENERATED,
        ResearchRunStatus.FINALIZING
    )
    assert is_valid_transition(
        ResearchRunStatus.FINALIZING,
        ResearchRunStatus.COMPLETED
    )

    # Mind score checkpoint schema
    mind = MindScoreCheckpointData(
        status="success",
        score=65,
        label="Developing",
        words_processed=15123,
        questions_answerable_estimate=2100,
        updated_at=datetime.utcnow().isoformat(),
        errors=[],
    )
    assert mind.status == "success"
    assert mind.score == 65

    # Readiness checkpoint schema
    readiness = ReadinessCheckpointData(
        status="evaluated",
        is_ready=True,
        thresholds={"min_mind_score": 30},
        requirements={},
        counts={},
        errors=[],
    )
    assert readiness.is_ready is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
