"""
Tests for Crawl Failure Taxonomy (Phase 1B.3)
"""

import pytest

from modules.crawl_failure_taxonomy import (
    FailureType,
    FailureCategory,
    FailureStage,
    classify_failure,
    is_retryable,
    get_failure_category,
    create_failure_artifact,
    create_failure_summary,
)


class TestClassifyFailure:
    """Test failure classification."""

    def test_auth_401(self):
        """401 should be AUTH."""
        result = classify_failure(401, "Unauthorized")
        assert result == FailureType.AUTH

    def test_auth_403(self):
        """403 should be AUTH."""
        result = classify_failure(403, "Forbidden")
        assert result == FailureType.AUTH

    def test_rate_limit_429(self):
        """429 should be RATE_LIMIT."""
        result = classify_failure(429, "Too Many Requests")
        assert result == FailureType.RATE_LIMIT

    def test_unavailable_500(self):
        """500 should be UNAVAILABLE."""
        result = classify_failure(500, "Server Error")
        assert result == FailureType.UNAVAILABLE

    def test_unavailable_503(self):
        """503 should be UNAVAILABLE."""
        result = classify_failure(503, "Service Unavailable")
        assert result == FailureType.UNAVAILABLE

    def test_timeout(self):
        """Timeout error should be TIMEOUT."""
        result = classify_failure(None, "Connection timeout")
        assert result == FailureType.TIMEOUT

    def test_network_dns(self):
        """DNS error should be NETWORK."""
        result = classify_failure(None, "DNS resolution failed")
        assert result == FailureType.NETWORK

    def test_gating_cloudflare(self):
        """Cloudflare should be GATING."""
        result = classify_failure(None, "Cloudflare protection")
        assert result == FailureType.GATING

    def test_gating_captcha(self):
        """Captcha should be GATING."""
        result = classify_failure(None, "Captcha required")
        assert result == FailureType.GATING

    def test_parser_fail(self):
        """Parse error should be PARSER_FAIL."""
        result = classify_failure(None, "JSON decode error")
        assert result == FailureType.PARSER_FAIL

    def test_safety_private_ip(self):
        """Private IP in safety check should be SSRF_BLOCKED."""
        result = classify_failure(
            None,
            "Private IP blocked",
            stage=FailureStage.SAFETY_CHECK
        )
        assert result == FailureType.SSRF_BLOCKED

    def test_safety_content_type(self):
        """Content type block in safety check."""
        result = classify_failure(
            None,
            "Content type application/pdf blocked",
            stage=FailureStage.SAFETY_CHECK
        )
        assert result == FailureType.CONTENT_TYPE_BLOCKED


class TestRetryability:
    """Test retryability mapping."""

    def test_hard_blocks_not_retryable(self):
        """Hard blocks should never be retryable."""
        assert is_retryable(FailureType.SSRF_BLOCKED) is False
        assert is_retryable(FailureType.PRIVATE_IP_BLOCKED) is False
        assert is_retryable(FailureType.CONTENT_TYPE_BLOCKED) is False
        assert is_retryable(FailureType.SIZE_EXCEEDED) is False
        assert is_retryable(FailureType.TOO_MANY_REDIRECTS) is False

    def test_rate_limit_retryable(self):
        """Rate limit should be retryable."""
        assert is_retryable(FailureType.RATE_LIMIT) is True

    def test_network_retryable(self):
        """Network errors should be retryable."""
        assert is_retryable(FailureType.NETWORK) is True

    def test_timeout_retryable(self):
        """Timeout should be retryable."""
        assert is_retryable(FailureType.TIMEOUT) is True

    def test_unavailable_retryable(self):
        """Unavailable should be retryable."""
        assert is_retryable(FailureType.UNAVAILABLE) is True

    def test_auth_not_retryable(self):
        """Auth should not be retryable."""
        assert is_retryable(FailureType.AUTH) is False

    def test_gating_not_retryable(self):
        """Gating should not be retryable."""
        assert is_retryable(FailureType.GATING) is False


class TestFailureCategory:
    """Test failure category classification."""

    def test_hard_block_category(self):
        """Hard blocks should have HARD_BLOCK category."""
        assert get_failure_category(FailureType.SSRF_BLOCKED) == FailureCategory.HARD_BLOCK
        assert get_failure_category(FailureType.PRIVATE_IP_BLOCKED) == FailureCategory.HARD_BLOCK

    def test_retryable_is_soft_fail(self):
        """Retryable failures should be SOFT_FAIL."""
        assert get_failure_category(FailureType.RATE_LIMIT) == FailureCategory.SOFT_FAIL
        assert get_failure_category(FailureType.NETWORK) == FailureCategory.SOFT_FAIL

    def test_non_retryable_soft_fails(self):
        """Non-retryable soft fails should still be SOFT_FAIL."""
        assert get_failure_category(FailureType.AUTH) == FailureCategory.SOFT_FAIL
        assert get_failure_category(FailureType.GATING) == FailureCategory.SOFT_FAIL
        assert get_failure_category(FailureType.PARSER_FAIL) == FailureCategory.SOFT_FAIL


class TestCreateFailureArtifact:
    """Test failure artifact creation."""

    def test_artifact_structure(self):
        """Artifact should have required fields."""
        artifact = create_failure_artifact(
            url="https://example.com/page",
            canonical_url="https://example.com/page",
            crawl_id="crawl_123",
            crawl_page_id="page_456",
            failure_type=FailureType.RATE_LIMIT,
            error_detail="429 Too Many Requests",
            stage=FailureStage.FETCH,
            metadata={"retry_after": 60},
        )

        assert artifact["version"] == "1.0"
        assert artifact["url"] == "https://example.com/page"
        assert artifact["canonical_url"] == "https://example.com/page"
        assert artifact["crawl_id"] == "crawl_123"
        assert artifact["crawl_page_id"] == "page_456"
        assert artifact["failure"]["type"] == "rate_limit"
        assert artifact["failure"]["retryable"] is True
        assert artifact["failure"]["stage"] == "fetch"
        assert artifact["context"]["retry_after"] == 60
        assert "timestamp" in artifact

    def test_hard_block_artifact(self):
        """Hard block artifact should have correct category."""
        artifact = create_failure_artifact(
            url="http://10.0.0.1/secret",
            canonical_url="http://10.0.0.1/secret",
            crawl_id="crawl_123",
            crawl_page_id=None,
            failure_type=FailureType.SSRF_BLOCKED,
            error_detail="Private IP range blocked",
            stage=FailureStage.SAFETY_CHECK,
        )

        assert artifact["failure"]["category"] == "hard_block"
        assert artifact["failure"]["retryable"] is False


class TestCreateFailureSummary:
    """Test failure summary creation."""

    def test_summary_structure(self):
        """Summary should aggregate failures correctly."""
        failures = [
            create_failure_artifact(
                url="url1", canonical_url="canon1", crawl_id="crawl_123",
                crawl_page_id="p1", failure_type=FailureType.RATE_LIMIT,
                error_detail="429", stage=FailureStage.FETCH
            ),
            create_failure_artifact(
                url="url2", canonical_url="canon2", crawl_id="crawl_123",
                crawl_page_id="p2", failure_type=FailureType.RATE_LIMIT,
                error_detail="429", stage=FailureStage.FETCH
            ),
            create_failure_artifact(
                url="url3", canonical_url="canon3", crawl_id="crawl_123",
                crawl_page_id="p3", failure_type=FailureType.SSRF_BLOCKED,
                error_detail="Private IP", stage=FailureStage.SAFETY_CHECK
            ),
        ]

        summary = create_failure_summary("crawl_123", failures)

        assert summary["crawl_id"] == "crawl_123"
        assert summary["total_failures"] == 3
        assert summary["by_type"]["rate_limit"] == 2
        assert summary["by_type"]["ssrf_blocked"] == 1
        assert summary["by_category"]["soft_fail"] == 2
        assert summary["by_category"]["hard_block"] == 1
        assert summary["retryable"] == 2
        assert summary["not_retryable"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
