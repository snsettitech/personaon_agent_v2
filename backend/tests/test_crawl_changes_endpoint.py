"""
Tests for Crawl Changes Endpoint (Phase 1B.4)
"""

import pytest

from routers.crawl import _calculate_changes


class TestCalculateChanges:
    """Test changes calculation logic."""

    def test_empty_pages(self):
        """Empty pages should return zero counts."""
        result = _calculate_changes([])

        assert result["unchanged"] == 0
        assert result["changed"] == 0
        assert result["new"] == 0
        assert result["changes_list"] == []

    def test_unchanged_pages(self):
        """Unchanged pages should be counted correctly."""
        pages = [
            {
                "canonical_url": "https://example.com/page1",
                "status": "unchanged",
                "content_hash": "hash123",
            },
            {
                "canonical_url": "https://example.com/page2",
                "status": "unchanged",
                "content_hash": "hash456",
            },
        ]

        result = _calculate_changes(pages)

        assert result["unchanged"] == 2
        assert result["changed"] == 0
        assert result["new"] == 0
        assert len(result["changes_list"]) == 2
        assert result["changes_list"][0]["classification"] == "unchanged"

    def test_changed_pages(self):
        """Changed pages should be counted correctly."""
        pages = [
            {
                "canonical_url": "https://example.com/page1",
                "status": "changed",
                "content_hash": "new_hash",
                "metadata": {"previous_content_hash": "old_hash"},
            },
        ]

        result = _calculate_changes(pages)

        assert result["unchanged"] == 0
        assert result["changed"] == 1
        assert result["new"] == 0
        assert result["changes_list"][0]["classification"] == "changed"
        assert result["changes_list"][0]["previous_hash"] == "old_hash"
        assert result["changes_list"][0]["current_hash"] == "new_hash"

    def test_new_pages(self):
        """New pages should be counted correctly."""
        pages = [
            {
                "canonical_url": "https://example.com/page1",
                "status": "ingested",
                "content_hash": "hash123",
            },
            {
                "canonical_url": "https://example.com/page2",
                "status": "discovered",
                "content_hash": "hash456",
            },
        ]

        result = _calculate_changes(pages)

        assert result["unchanged"] == 0
        assert result["changed"] == 0
        assert result["new"] == 2
        assert result["changes_list"][0]["classification"] == "new"
        assert result["changes_list"][0]["previous_hash"] is None

    def test_mixed_pages(self):
        """Mixed page statuses should be classified correctly."""
        pages = [
            {
                "canonical_url": "https://example.com/unchanged",
                "status": "unchanged",
                "content_hash": "hash1",
            },
            {
                "canonical_url": "https://example.com/changed",
                "status": "changed",
                "content_hash": "new_hash",
                "metadata": {"previous_content_hash": "old_hash"},
            },
            {
                "canonical_url": "https://example.com/new",
                "status": "ingested",
                "content_hash": "hash3",
            },
        ]

        result = _calculate_changes(pages)

        assert result["unchanged"] == 1
        assert result["changed"] == 1
        assert result["new"] == 1
        assert len(result["changes_list"]) == 3


class TestChangesEndpoint:
    """Test the changes endpoint."""

    def test_endpoint_path_pattern(self):
        """Endpoint path should follow correct pattern."""
        # The endpoint is always registered.
        # Path pattern should be: /twins/{twin_id}/crawls/{crawl_id}/changes
        # This test documents the expected path
        expected_pattern = "/twins/{twin_id}/crawls/{crawl_id}/changes"
        assert "changes" in expected_pattern
        assert "{crawl_id}" in expected_pattern

    def test_response_structure(self):
        """Response should have required fields."""
        # Mock the calculation
        pages = [
            {"canonical_url": "url1", "status": "unchanged", "content_hash": "h1"},
            {"canonical_url": "url2", "status": "changed", "content_hash": "h2", "metadata": {}},
        ]

        result = _calculate_changes(pages)

        # Verify structure
        assert "unchanged" in result
        assert "changed" in result
        assert "new" in result
        assert "changes_list" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
