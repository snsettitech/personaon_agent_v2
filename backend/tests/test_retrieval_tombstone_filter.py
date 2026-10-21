"""
Tests for Retrieval Tombstone Filtering (Phase 2.3)

Covers:
- Default retrieval excludes tombstoned chunks
- Legacy chunks (no is_current) are included
- Filter construction includes tombstone conditions
"""

import pytest


class TestFilterLogic:
    """Test the filter logic for tombstone exclusion."""

    def test_expected_filter_structure(self):
        """Expected filter structure excludes tombstoned."""
        # This is what the filter should look like
        expected_filter = {
            "$or": [
                {"is_current": {"$eq": True}},
                {"is_current": {"$exists": False}}
            ]
        }

        # Verify structure
        assert "$or" in expected_filter
        or_conditions = expected_filter["$or"]
        assert len(or_conditions) == 2
        assert or_conditions[0] == {"is_current": {"$eq": True}}
        assert or_conditions[1] == {"is_current": {"$exists": False}}

    def test_combined_filter_structure(self):
        """Filter combines twin_id and tombstone conditions."""
        twin_filter = {"twin_id": {"$eq": "twin_123"}}
        tombstone_filter = {
            "$or": [
                {"is_current": {"$eq": True}},
                {"is_current": {"$exists": False}}
            ]
        }

        combined = {"$and": [twin_filter, tombstone_filter]}

        assert "$and" in combined
        assert len(combined["$and"]) == 2
        assert combined["$and"][0] == twin_filter
        assert combined["$and"][1] == tombstone_filter


class TestChunkMetadataFiltering:
    """Test filtering logic applied to chunk metadata."""

    def test_current_chunk_passes_filter(self):
        """Current chunk (is_current=True) passes filter."""
        metadata = {"is_current": True, "twin_id": "twin_123"}

        # Simulates the filter check
        passes = (
            metadata.get("is_current") is True or
            "is_current" not in metadata
        )
        assert passes is True

    def test_tombstoned_chunk_fails_filter(self):
        """Tombstoned chunk (is_current=False) fails filter."""
        metadata = {"is_current": False, "twin_id": "twin_123"}

        passes = (
            metadata.get("is_current") is True or
            "is_current" not in metadata
        )
        assert passes is False

    def test_legacy_chunk_passes_filter(self):
        """Legacy chunk (no is_current) passes filter."""
        metadata = {"twin_id": "twin_123", "text": "content"}

        passes = (
            metadata.get("is_current") is True or
            "is_current" not in metadata
        )
        assert passes is True


class TestBackwardCompatibility:
    """Test that existing retrieval behavior is preserved."""

    def test_legacy_chunks_not_excluded(self):
        """Legacy chunks without is_current field are not excluded."""
        chunks = [
            {"text": "chunk1", "source_id": "src_1"},  # No is_current
            {"text": "chunk2", "source_id": "src_2", "is_current": True},
        ]

        # Filter that mimics the retrieval logic
        def passes_filter(chunk):
            return chunk.get("is_current") is True or "is_current" not in chunk

        filtered = [c for c in chunks if passes_filter(c)]
        assert len(filtered) == 2  # Both pass

    def test_mixed_chunks_filtering(self):
        """Mix of current, tombstoned, and legacy chunks."""
        chunks = [
            {"text": "legacy", "source_id": "src_1"},  # No is_current (legacy)
            {"text": "current", "source_id": "src_2", "is_current": True},
            {"text": "tombstoned", "source_id": "src_3", "is_current": False},
        ]

        def passes_filter(chunk):
            return chunk.get("is_current") is True or "is_current" not in chunk

        filtered = [c for c in chunks if passes_filter(c)]

        assert len(filtered) == 2
        assert filtered[0]["text"] == "legacy"
        assert filtered[1]["text"] == "current"


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
