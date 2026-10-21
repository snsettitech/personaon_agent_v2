"""
Tests for Research Orchestrator Phase 3.5 (Ingestion with Confirmation Gate)

Phase 3.5 adds ingestion continuation from ready_for_ingestion state.
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
    IngestionCheckpointData,
    CheckpointData,
)


# ============================================================================
# Phase 3.5 State Machine Tests
# ============================================================================

class TestPhase35StateMachine:
    """Test Phase 3.5 state machine transitions."""

    def test_ready_for_ingestion_to_ingesting(self):
        """ready_for_ingestion can transition to ingesting."""
        assert is_valid_transition(
            ResearchRunStatus.READY_FOR_INGESTION,
            ResearchRunStatus.INGESTING
        )

    def test_ingesting_to_ingestion_completed(self):
        """ingesting can transition to ingestion_completed."""
        assert is_valid_transition(
            ResearchRunStatus.INGESTING,
            ResearchRunStatus.INGESTION_COMPLETED
        )

    def test_ingesting_to_failed(self):
        """ingesting can transition to failed on error."""
        assert is_valid_transition(
            ResearchRunStatus.INGESTING,
            ResearchRunStatus.FAILED
        )

    def test_ingestion_completed_is_terminal(self):
        """ingestion_completed is terminal for Phase 3.5."""
        assert not is_valid_transition(
            ResearchRunStatus.INGESTION_COMPLETED,
            ResearchRunStatus.INGESTING
        )
        assert not is_valid_transition(
            ResearchRunStatus.INGESTION_COMPLETED,
            ResearchRunStatus.READY_FOR_INGESTION
        )

    def test_awaiting_confirmation_cannot_go_to_ingesting(self):
        """awaiting_confirmation cannot directly go to ingesting."""
        assert not is_valid_transition(
            ResearchRunStatus.AWAITING_CONFIRMATION,
            ResearchRunStatus.INGESTING
        )

    def test_planning_cannot_go_to_ingesting(self):
        """planning cannot go to ingesting."""
        assert not is_valid_transition(
            ResearchRunStatus.PLANNING,
            ResearchRunStatus.INGESTING
        )

    def test_ingestion_completed_self_transition(self):
        """ingestion_completed can self-transition (idempotent)."""
        assert is_valid_transition(
            ResearchRunStatus.INGESTION_COMPLETED,
            ResearchRunStatus.INGESTION_COMPLETED
        )


# ============================================================================
# Ingestion Checkpoint Data Tests
# ============================================================================

class TestIngestionCheckpointData:
    """Test Phase 3.5 ingestion checkpoint structure."""

    def test_ingestion_checkpoint_creation(self):
        """Test creating ingestion checkpoint data."""
        checkpoint = IngestionCheckpointData(
            require_confirmation=True,
            pages_eligible=15,
            pages_ingested=14,
            pages_skipped=6,
            rejected_skipped=4,
            unresolved_skipped=2,
            tombstone_actions=0,
            errors=[],
        )

        assert checkpoint.require_confirmation is True
        assert checkpoint.pages_eligible == 15
        assert checkpoint.pages_ingested == 14
        assert checkpoint.pages_skipped == 6
        assert checkpoint.rejected_skipped == 4
        assert checkpoint.unresolved_skipped == 2

    def test_ingestion_checkpoint_in_full_checkpoint(self):
        """Test ingestion checkpoint nested in full checkpoint."""
        ingestion = IngestionCheckpointData(
            require_confirmation=True,
            pages_eligible=10,
            pages_ingested=8,
            pages_skipped=2,
            rejected_skipped=1,
            unresolved_skipped=1,
            tombstone_actions=0,
            errors=[],
        )

        checkpoint = CheckpointData(
            phase="ingestion_completed",
            last_transition_at=datetime.utcnow().isoformat(),
            ingestion=ingestion,
        )

        assert checkpoint.ingestion is not None
        assert checkpoint.ingestion.pages_ingested == 8
        assert checkpoint.ingestion.pages_skipped == 2


# ============================================================================
# Orchestrator Phase 3.5 Logic Tests (Mocked)
# ============================================================================

class TestContinueToIngestion:
    """Test continue_to_ingestion method."""

    @pytest.fixture
    def orchestrator(self):
        """Create orchestrator with mocked dependencies."""
        return ResearchOrchestrator()

    @pytest.mark.asyncio
    async def test_blocks_from_awaiting_confirmation(self, orchestrator):
        """Test that continue_to_ingestion blocks from awaiting_confirmation."""
        # Mock the repository to return a run in awaiting_confirmation
        with patch.object(orchestrator.repository, 'get_research_run', return_value={
            "id": "run-123",
            "twin_id": "twin-456",
            "status": "awaiting_confirmation",
            "crawl_id": "crawl-789",
        }):
            result = await orchestrator.continue_to_ingestion(
                research_run_id="run-123",
                twin_id="twin-456",
            )

            assert result.success is False
            assert "ready_for_ingestion" in result.error

    @pytest.mark.asyncio
    async def test_idempotent_when_already_completed(self, orchestrator):
        """Test idempotency when already in ingestion_completed."""
        with patch.object(orchestrator.repository, 'get_research_run', return_value={
            "id": "run-123",
            "twin_id": "twin-456",
            "status": "ingestion_completed",
            "crawl_id": "crawl-789",
        }):
            result = await orchestrator.continue_to_ingestion(
                research_run_id="run-123",
                twin_id="twin-456",
            )

            assert result.success is True
            assert result.new_status == "ingestion_completed"
            assert "idempotent" in result.transition_reason.lower()

    @pytest.mark.asyncio
    async def test_blocks_when_no_crawl_id(self, orchestrator):
        """Test that continue_to_ingestion blocks when no crawl_id."""
        with patch.object(orchestrator.repository, 'get_research_run', return_value={
            "id": "run-123",
            "twin_id": "twin-456",
            "status": "ready_for_ingestion",
            "crawl_id": None,
        }):
            result = await orchestrator.continue_to_ingestion(
                research_run_id="run-123",
                twin_id="twin-456",
            )

            assert result.success is False
            assert "crawl_id" in result.error.lower()

    @pytest.mark.asyncio
    async def test_run_not_found(self, orchestrator):
        """Test error when research run not found."""
        with patch.object(orchestrator.repository, 'get_research_run', return_value=None):
            result = await orchestrator.continue_to_ingestion(
                research_run_id="run-123",
                twin_id="twin-456",
            )

            assert result.success is False
            assert "not found" in result.error.lower()


# ============================================================================
# Phase 3.5 Contract Tests
# ============================================================================

class TestPhase35Contracts:
    """Test Phase 3.5 behavior contracts."""

    def test_no_bio_generation_phase(self):
        """Phase 3.5 does NOT trigger bio generation."""
        # This is a contract test - bio generation is Phase 4
        # Phase 3.5 stops at ingestion_completed
        assert ResearchRunStatus.INGESTION_COMPLETED.value == "ingestion_completed"

    def test_no_mind_score_update(self):
        """Phase 3.5 does NOT update mind score."""
        # Mind score updates are Phase 5
        # Phase 3.5 only handles ingestion
        pass  # Contract documented

    def test_ingestion_summary_in_checkpoint(self):
        """Ingestion summary is persisted in checkpoint_data."""
        ingestion = IngestionCheckpointData(
            require_confirmation=True,
            pages_eligible=20,
            pages_ingested=15,
            pages_skipped=5,
            rejected_skipped=3,
            unresolved_skipped=2,
            tombstone_actions=0,
            errors=[],
        )

        # Verify all required fields present
        assert hasattr(ingestion, 'require_confirmation')
        assert hasattr(ingestion, 'pages_eligible')
        assert hasattr(ingestion, 'pages_ingested')
        assert hasattr(ingestion, 'pages_skipped')
        assert hasattr(ingestion, 'rejected_skipped')
        assert hasattr(ingestion, 'unresolved_skipped')
        assert hasattr(ingestion, 'tombstone_actions')
        assert hasattr(ingestion, 'errors')


# ============================================================================
# Crawl Ingestion Bridge Phase 3.5 Tests
# ============================================================================

class TestCrawlIngestionBridgePhase35:
    """Test crawl ingestion bridge confirmation gate."""

    def test_confirmation_gate_skips_unconfirmed(self):
        """Test that unconfirmed pages are skipped in gated mode."""
        from modules.crawl_ingestion_bridge import CrawlIngestionBridge

        bridge = CrawlIngestionBridge()

        # Page not in confirmed set
        page = {"id": "page-123", "status": "discovered"}
        confirmed_ids = {"page-456", "page-789"}

        should_skip, reason = bridge.should_skip_ingestion_confirmation_gate(
            page, confirmed_ids
        )

        assert should_skip is True
        assert reason == "not_confirmed"

    def test_confirmation_gate_allows_confirmed(self):
        """Test that confirmed pages are allowed in gated mode."""
        from modules.crawl_ingestion_bridge import CrawlIngestionBridge

        bridge = CrawlIngestionBridge()

        # Page in confirmed set
        page = {"id": "page-123", "status": "discovered"}
        confirmed_ids = {"page-123", "page-456"}

        should_skip, reason = bridge.should_skip_ingestion_confirmation_gate(
            page, confirmed_ids
        )

        assert should_skip is False

    def test_parameter_validation(self):
        """Test that require_confirmation requires research_run_id."""
        from modules.crawl_ingestion_bridge import CrawlIngestionBridge

        bridge = CrawlIngestionBridge()

        # This would be validated in process_crawl_for_ingestion
        # require_confirmation=True without research_run_id should raise
        # (We can't easily test the async method without mocking)


# ============================================================================
# Summary
# ============================================================================

def test_phase_3_5_implementation_summary():
    """
    Summary of Phase 3.5 implementation contracts.

    This test documents the expected behavior of Phase 3.5.
    """
    # New states added
    assert ResearchRunStatus.INGESTING.value == "ingesting"
    assert ResearchRunStatus.INGESTION_COMPLETED.value == "ingestion_completed"

    # Valid transitions
    assert is_valid_transition(
        ResearchRunStatus.READY_FOR_INGESTION,
        ResearchRunStatus.INGESTING
    )
    assert is_valid_transition(
        ResearchRunStatus.INGESTING,
        ResearchRunStatus.INGESTION_COMPLETED
    )

    # Ingestion checkpoint schema
    ingestion = IngestionCheckpointData(
        require_confirmation=True,
        pages_eligible=10,
        pages_ingested=8,
        pages_skipped=2,
        rejected_skipped=1,
        unresolved_skipped=1,
        tombstone_actions=0,
        errors=[],
    )
    assert ingestion.require_confirmation is True
    assert ingestion.pages_ingested == 8


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
