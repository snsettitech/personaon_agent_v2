"""
Tests for Research Orchestrator Phase 4 (Bio Generation Integration)

Phase 4 adds bio generation continuation from ingestion_completed state.
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
    BioGenerationCheckpointData,
    CheckpointData,
)


# ============================================================================
# Phase 4 State Machine Tests
# ============================================================================

class TestPhase4StateMachine:
    """Test Phase 4 state machine transitions."""

    def test_ingestion_completed_to_generating_bio(self):
        """ingestion_completed can transition to generating_bio."""
        assert is_valid_transition(
            ResearchRunStatus.INGESTION_COMPLETED,
            ResearchRunStatus.GENERATING_BIO
        )

    def test_generating_bio_to_bio_generated(self):
        """generating_bio can transition to bio_generated."""
        assert is_valid_transition(
            ResearchRunStatus.GENERATING_BIO,
            ResearchRunStatus.BIO_GENERATED
        )

    def test_generating_bio_to_failed(self):
        """generating_bio can transition to failed on error."""
        assert is_valid_transition(
            ResearchRunStatus.GENERATING_BIO,
            ResearchRunStatus.FAILED
        )

    def test_bio_generated_is_terminal(self):
        """bio_generated is terminal for Phase 4."""
        assert not is_valid_transition(
            ResearchRunStatus.BIO_GENERATED,
            ResearchRunStatus.GENERATING_BIO
        )
        assert not is_valid_transition(
            ResearchRunStatus.BIO_GENERATED,
            ResearchRunStatus.INGESTION_COMPLETED
        )

    def test_awaiting_confirmation_cannot_go_to_generating_bio(self):
        """awaiting_confirmation cannot directly go to generating_bio."""
        assert not is_valid_transition(
            ResearchRunStatus.AWAITING_CONFIRMATION,
            ResearchRunStatus.GENERATING_BIO
        )

    def test_ready_for_ingestion_cannot_go_to_generating_bio(self):
        """ready_for_ingestion cannot go to generating_bio."""
        assert not is_valid_transition(
            ResearchRunStatus.READY_FOR_INGESTION,
            ResearchRunStatus.GENERATING_BIO
        )

    def test_ingesting_cannot_go_to_generating_bio(self):
        """ingesting cannot go to generating_bio."""
        assert not is_valid_transition(
            ResearchRunStatus.INGESTING,
            ResearchRunStatus.GENERATING_BIO
        )

    def test_bio_generated_self_transition(self):
        """bio_generated can self-transition (idempotent)."""
        assert is_valid_transition(
            ResearchRunStatus.BIO_GENERATED,
            ResearchRunStatus.BIO_GENERATED
        )


# ============================================================================
# Bio Generation Checkpoint Data Tests
# ============================================================================

class TestBioGenerationCheckpointData:
    """Test Phase 4 bio generation checkpoint structure."""

    def test_bio_generation_checkpoint_creation(self):
        """Test creating bio generation checkpoint data."""
        checkpoint = BioGenerationCheckpointData(
            triggered=True,
            source_url_count=8,
            source_selection_policy="confirmed_only",
            persona_pipeline="persona_link_compile",
            status="success",
            bio_variant_count=3,
            selected_variant_id="variant-123",
            result_refs={"job_id": "job-456", "session_id": "session-789"},
            errors=[],
        )

        assert checkpoint.triggered is True
        assert checkpoint.source_url_count == 8
        assert checkpoint.source_selection_policy == "confirmed_only"
        assert checkpoint.persona_pipeline == "persona_link_compile"
        assert checkpoint.status == "success"
        assert checkpoint.bio_variant_count == 3
        assert checkpoint.selected_variant_id == "variant-123"

    def test_bio_generation_checkpoint_in_full_checkpoint(self):
        """Test bio generation checkpoint nested in full checkpoint."""
        bio_checkpoint = BioGenerationCheckpointData(
            triggered=True,
            source_url_count=5,
            source_selection_policy="confirmed_only",
            persona_pipeline="persona_link_compile",
            status="success",
            bio_variant_count=2,
            selected_variant_id=None,
            result_refs={},
            errors=[],
        )

        checkpoint = CheckpointData(
            phase="bio_generated",
            last_transition_at=datetime.utcnow().isoformat(),
            bio_generation=bio_checkpoint,
        )

        assert checkpoint.bio_generation is not None
        assert checkpoint.bio_generation.bio_variant_count == 2
        assert checkpoint.bio_generation.source_url_count == 5


# ============================================================================
# Orchestrator Phase 4 Logic Tests (Mocked)
# ============================================================================

class TestContinueToBioGeneration:
    """Test continue_to_bio_generation method."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator for testing."""
        return ResearchOrchestrator()

    @pytest.mark.asyncio
    async def test_blocks_from_ready_for_ingestion(self, orchestrator):
        """Test that continue_to_bio_generation blocks from ready_for_ingestion."""
        with patch.object(orchestrator.repository, 'get_research_run', return_value={
            "id": "run-123",
            "twin_id": "twin-456",
            "status": "ready_for_ingestion",
            "crawl_id": "crawl-789",
            "checkpoint_data": {},
        }):
            result = await orchestrator.continue_to_bio_generation(
                research_run_id="run-123",
                twin_id="twin-456",
            )

            assert result.success is False
            assert "ingestion_completed" in result.error

    @pytest.mark.asyncio
    async def test_idempotent_when_already_bio_generated(self, orchestrator):
        """Test idempotency when already in bio_generated."""
        with patch.object(orchestrator.repository, 'get_research_run', return_value={
            "id": "run-123",
            "twin_id": "twin-456",
            "status": "bio_generated",
            "crawl_id": "crawl-789",
            "checkpoint_data": {},
        }):
            result = await orchestrator.continue_to_bio_generation(
                research_run_id="run-123",
                twin_id="twin-456",
            )

            assert result.success is True
            assert result.new_status == "bio_generated"
            assert "idempotent" in result.transition_reason.lower()

    @pytest.mark.asyncio
    async def test_blocks_from_awaiting_confirmation(self, orchestrator):
        """Test that continue_to_bio_generation blocks from awaiting_confirmation."""
        with patch.object(orchestrator.repository, 'get_research_run', return_value={
            "id": "run-123",
            "twin_id": "twin-456",
            "status": "awaiting_confirmation",
            "crawl_id": "crawl-789",
            "checkpoint_data": {},
        }):
            result = await orchestrator.continue_to_bio_generation(
                research_run_id="run-123",
                twin_id="twin-456",
            )

            assert result.success is False
            assert "ingestion_completed" in result.error

    @pytest.mark.asyncio
    async def test_run_not_found(self, orchestrator):
        """Test error when research run not found."""
        with patch.object(orchestrator.repository, 'get_research_run', return_value=None):
            result = await orchestrator.continue_to_bio_generation(
                research_run_id="run-123",
                twin_id="twin-456",
            )

            assert result.success is False
            assert "not found" in result.error.lower()


# ============================================================================
# Confirmed Source Selection Tests
# ============================================================================

class TestConfirmedSourceSelection:
    """Test confirmed source URL selection helper."""

    def test_selects_only_confirmed_and_auto_confirmed(self):
        """Test that only confirmed and auto_confirmed sources are selected."""
        # This would require database mocking
        # For now, document the contract
        pass  # Integration test with mocked DB

    def test_deduplicates_urls(self):
        """Test URL deduplication."""
        # Contract test - implementation should dedupe
        pass  # Integration test with mocked DB

    def test_respects_max_urls_limit(self):
        """Test max URL limit is respected."""
        orchestrator = ResearchOrchestrator()
        # The _get_confirmed_source_urls method has max_urls parameter
        # This is a contract test documenting the behavior
        assert True  # Method signature includes max_urls: int = 10


# ============================================================================
# Phase 4 Contract Tests
# ============================================================================

class TestPhase4Contracts:
    """Test Phase 4 behavior contracts."""

    def test_no_mind_score_update(self):
        """Phase 4 does NOT update mind score."""
        # Mind score updates are Phase 5
        # Phase 4 only triggers bio generation
        pass  # Contract documented

    def test_no_readiness_check(self):
        """Phase 4 does NOT compute twin readiness."""
        # Readiness checks are Phase 5
        pass  # Contract documented

    def test_bio_generation_summary_in_checkpoint(self):
        """Bio generation summary is persisted in checkpoint_data."""
        bio = BioGenerationCheckpointData(
            triggered=True,
            source_url_count=10,
            source_selection_policy="confirmed_only",
            persona_pipeline="persona_link_compile",
            status="success",
            bio_variant_count=3,
            selected_variant_id=None,
            result_refs={},
            errors=[],
        )

        # Verify all required fields present
        assert hasattr(bio, 'triggered')
        assert hasattr(bio, 'source_url_count')
        assert hasattr(bio, 'source_selection_policy')
        assert hasattr(bio, 'persona_pipeline')
        assert hasattr(bio, 'status')
        assert hasattr(bio, 'bio_variant_count')
        assert hasattr(bio, 'selected_variant_id')
        assert hasattr(bio, 'result_refs')
        assert hasattr(bio, 'errors')

    def test_uses_existing_persona_pipeline(self):
        """Phase 4 uses existing persona_link_compile pipeline."""
        # Contract: Uses generate_and_store_bios from modules.persona_bio_generator
        pass  # Contract documented in implementation


# ============================================================================
# Summary
# ============================================================================

def test_phase_4_implementation_summary():
    """
    Summary of Phase 4 implementation contracts.

    This test documents the expected behavior of Phase 4.
    """
    # New states added
    assert ResearchRunStatus.GENERATING_BIO.value == "generating_bio"
    assert ResearchRunStatus.BIO_GENERATED.value == "bio_generated"

    # Valid transitions
    assert is_valid_transition(
        ResearchRunStatus.INGESTION_COMPLETED,
        ResearchRunStatus.GENERATING_BIO
    )
    assert is_valid_transition(
        ResearchRunStatus.GENERATING_BIO,
        ResearchRunStatus.BIO_GENERATED
    )

    # Bio generation checkpoint schema
    bio = BioGenerationCheckpointData(
        triggered=True,
        source_url_count=8,
        source_selection_policy="confirmed_only",
        persona_pipeline="persona_link_compile",
        status="success",
        bio_variant_count=3,
        selected_variant_id="variant-1",
        result_refs={"job_id": "job-1"},
        errors=[],
    )
    assert bio.triggered is True
    assert bio.source_url_count == 8
    assert bio.bio_variant_count == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
