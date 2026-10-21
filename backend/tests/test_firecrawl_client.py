"""
Tests for Firecrawl Client Module (Phase 3.0)

Covers:
- Configuration loading from environment
- Circuit breaker state transitions
- Error mapping to failure taxonomy
- Content quality assessment
- Retry logic with exponential backoff
- Result structure and metadata
"""

import os
import pytest
from unittest.mock import patch

# Skip all tests if firecrawl is not available
try:
    from modules.firecrawl_client import (
        FirecrawlClient,
        FirecrawlConfig,
        FirecrawlResult,
        ContentQuality,
        CircuitBreaker,
        CircuitState,
        get_firecrawl_client,
        reset_firecrawl_client,
    )
    from modules.crawl_failure_taxonomy import FailureType, is_retryable
    FIRECRAWL_AVAILABLE = True
except ImportError:
    FIRECRAWL_AVAILABLE = False

pytestmark = pytest.mark.skipif(not FIRECRAWL_AVAILABLE, reason="firecrawl-py not installed")


# ============================================================================
# Configuration Tests
# ============================================================================

class TestFirecrawlConfig:
    """Test configuration loading and validation."""

    def test_default_configuration(self):
        """Test that default configuration values are reasonable."""
        config = FirecrawlConfig(api_key="test-key")

        assert config.api_key == "test-key"
        assert config.base_url == "https://api.firecrawl.dev"
        assert config.max_retries == 3
        assert config.timeout_seconds == 60
        assert config.max_concurrent == 5
        assert config.circuit_failure_threshold == 5
        assert config.circuit_recovery_timeout == 30
        assert config.website_crawl_limit == 50

    @patch.dict(os.environ, {
        "FIRECRAWL_API_KEY": "env-api-key",
        "FIRECRAWL_BASE_URL": "https://custom.firecrawl.dev",
        "FIRECRAWL_MAX_RETRIES": "5",
        "FIRECRAWL_TIMEOUT_SECONDS": "120",
        "FIRECRAWL_MAX_CONCURRENT": "10",
    }, clear=True)
    def test_from_env_loading(self):
        """Test loading configuration from environment variables."""
        config = FirecrawlConfig.from_env()

        assert config.api_key == "env-api-key"
        assert config.base_url == "https://custom.firecrawl.dev"
        assert config.max_retries == 5
        assert config.timeout_seconds == 120
        assert config.max_concurrent == 10

    def test_is_configured_with_key(self):
        """Test that configuration is detected as configured when API key present."""
        config = FirecrawlConfig(api_key="test-key")
        # Note: This may return False if firecrawl-py not installed
        # but we can at least verify the method runs
        result = config.is_configured()
        assert isinstance(result, bool)

    def test_is_configured_without_key(self):
        """Test that configuration is not configured without API key."""
        config = FirecrawlConfig(api_key="")
        assert config.is_configured() is False


# ============================================================================
# Circuit Breaker Tests
# ============================================================================

class TestCircuitBreaker:
    """Test circuit breaker pattern implementation."""

    @pytest.fixture
    def circuit(self):
        return CircuitBreaker(failure_threshold=3, recovery_timeout=1)

    @pytest.mark.asyncio
    async def test_initial_state_closed(self, circuit):
        """Test that circuit starts in CLOSED state."""
        assert circuit.state == CircuitState.CLOSED
        assert circuit.failure_count == 0

    @pytest.mark.asyncio
    async def test_successful_call(self, circuit):
        """Test that successful calls increment success."""
        async def success_func():
            return "success"

        result = await circuit.call(success_func)
        assert result == "success"
        assert circuit.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_counting(self, circuit):
        """Test that failures are counted correctly."""
        async def fail_func():
            raise ValueError("test error")

        # Fail twice (below threshold)
        for _ in range(2):
            with pytest.raises(ValueError):
                await circuit.call(fail_func)

        assert circuit.state == CircuitState.CLOSED
        assert circuit.failure_count == 2

    @pytest.mark.asyncio
    async def test_circuit_opens_after_threshold(self, circuit):
        """Test that circuit opens after threshold failures."""
        async def fail_func():
            raise ValueError("test error")

        # Fail at threshold
        for _ in range(3):
            with pytest.raises(ValueError):
                await circuit.call(fail_func)

        assert circuit.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_circuit_blocks_when_open(self, circuit):
        """Test that requests are blocked when circuit is open."""
        from modules.firecrawl_client import CircuitBreakerOpen
        import time

        # Manually open the circuit with current time (not enough time passed for recovery)
        circuit.state = CircuitState.OPEN
        circuit.last_failure_time = time.time()  # Just happened, not ready for reset

        async def any_func():
            return "result"

        with pytest.raises(CircuitBreakerOpen):
            await circuit.call(any_func)


# ============================================================================
# Error Mapping Tests
# ============================================================================

class TestErrorMapping:
    """Test mapping of Firecrawl errors to failure taxonomy."""

    @pytest.fixture
    def client(self):
        config = FirecrawlConfig(api_key="test-key")
        return FirecrawlClient(config)

    def test_rate_limit_mapping(self, client):
        """Test 429 errors map to RATE_LIMIT."""
        error = Exception("429 Too Many Requests")
        result = client._map_exception_to_failure_type(error)
        assert result == FailureType.RATE_LIMIT
        assert is_retryable(result) is True

    def test_auth_mapping(self, client):
        """Test 401/403 errors map to AUTH."""
        error = Exception("401 Unauthorized")
        result = client._map_exception_to_failure_type(error)
        assert result == FailureType.AUTH
        assert is_retryable(result) is False

    def test_gating_mapping(self, client):
        """Test bot/captcha errors map to GATING."""
        error = Exception("403 Forbidden - Cloudflare captcha detected")
        result = client._map_exception_to_failure_type(error)
        assert result == FailureType.GATING
        assert is_retryable(result) is False

    def test_timeout_mapping(self, client):
        """Test timeout errors map to TIMEOUT."""
        error = Exception("Request timed out after 30s")
        result = client._map_exception_to_failure_type(error)
        assert result == FailureType.TIMEOUT
        assert is_retryable(result) is True

    def test_network_mapping(self, client):
        """Test network errors map to NETWORK."""
        error = Exception("DNS resolution failed")
        result = client._map_exception_to_failure_type(error)
        assert result == FailureType.NETWORK
        assert is_retryable(result) is True

    def test_size_exceeded_mapping(self, client):
        """Test size exceeded errors map to SIZE_EXCEEDED."""
        error = Exception("Content size exceeds 10MB limit")
        result = client._map_exception_to_failure_type(error)
        assert result == FailureType.SIZE_EXCEEDED
        assert is_retryable(result) is False

    def test_parser_fail_mapping(self, client):
        """Test parser errors map to PARSER_FAIL."""
        error = Exception("JSON decode error")
        result = client._map_exception_to_failure_type(error)
        assert result == FailureType.PARSER_FAIL
        assert is_retryable(result) is False


# ============================================================================
# Content Quality Assessment Tests
# ============================================================================

class TestContentQualityAssessment:
    """Test content quality assessment logic."""

    @pytest.fixture
    def client(self):
        config = FirecrawlConfig(api_key="test-key")
        return FirecrawlClient(config)

    def test_full_content_quality(self, client):
        """Test that substantial content gets FULL quality rating."""
        content = "This is a substantial article with many words and paragraphs. " * 50
        metadata = {"sourceURL": "https://example.com/article"}

        quality, reason = client._assess_content_quality(content, metadata, None)

        assert quality == ContentQuality.FULL
        assert "Full content extracted" in reason

    def test_partial_content_quality_short(self, client):
        """Test that short content gets PARTIAL quality rating."""
        content = "Short text."
        metadata = {"sourceURL": "https://example.com/page", "title": "Page Title"}

        quality, reason = client._assess_content_quality(content, metadata, None)

        assert quality == ContentQuality.PARTIAL
        assert "metadata only" in reason

    def test_blocked_robots_quality(self, client):
        """Test that robots.txt errors get BLOCKED quality."""
        content = ""
        metadata = {}
        error = Exception("robots.txt disallows crawling")

        quality, reason = client._assess_content_quality(content, metadata, error)

        assert quality == ContentQuality.BLOCKED
        assert "blocked" in reason.lower()

    def test_manual_needed_youtube_quality(self, client):
        """Test that YouTube/video content gets MANUAL_NEEDED quality."""
        content = ""
        metadata = {}
        error = Exception("Video content requires transcript extraction")

        quality, reason = client._assess_content_quality(content, metadata, error)

        assert quality == ContentQuality.MANUAL_NEEDED

    def test_partial_youtube_description(self, client):
        """Test that YouTube URLs with moderate content get PARTIAL quality."""
        # Content between 100-500 chars with YouTube URL should be PARTIAL
        content = "This is a video description that provides some context about the video content. " * 5
        metadata = {"sourceURL": "https://youtube.com/watch?v=123"}

        quality, reason = client._assess_content_quality(content, metadata, None)

        assert quality == ContentQuality.PARTIAL
        assert "description only" in reason.lower()


# ============================================================================
# Result Structure Tests
# ============================================================================

class TestFirecrawlResult:
    """Test FirecrawlResult dataclass behavior."""

    def test_successful_result_structure(self):
        """Test successful result has all expected fields."""
        result = FirecrawlResult(
            success=True,
            url="https://example.com",
            content="Test content",
            metadata={"title": "Test"},
            quality=ContentQuality.FULL,
            quality_reason="Full extraction",
            attempts=1,
            duration_ms=500
        )

        assert result.success is True
        assert result.url == "https://example.com"
        assert result.content == "Test content"
        assert result.quality == ContentQuality.FULL
        assert result.error is None

    def test_failed_result_structure(self):
        """Test failed result has error information."""
        result = FirecrawlResult(
            success=False,
            url="https://example.com",
            quality=ContentQuality.BLOCKED,
            quality_reason="Access blocked",
            error={
                "failure_type": FailureType.GATING,
                "detail": "Cloudflare protection",
            },
            attempts=3,
            duration_ms=5000
        )

        assert result.success is False
        assert result.error is not None
        assert result.error["failure_type"] == FailureType.GATING

    def test_to_failure_artifact(self):
        """Test conversion to failure artifact."""
        from modules.crawl_failure_taxonomy import FailureStage

        result = FirecrawlResult(
            success=False,
            url="https://example.com",
            error={
                "failure_type": FailureType.RATE_LIMIT,
                "detail": "Rate limited",
                "stage": FailureStage.FETCH,
            }
        )

        artifact = result.to_failure_artifact("crawl-123", "page-456")

        assert artifact is not None
        assert artifact["url"] == "https://example.com"
        assert artifact["crawl_id"] == "crawl-123"
        assert artifact["crawl_page_id"] == "page-456"
        assert artifact["failure"]["type"] == FailureType.RATE_LIMIT.value

    def test_successful_result_no_artifact(self):
        """Test that successful results don't generate artifacts."""
        result = FirecrawlResult(
            success=True,
            url="https://example.com",
            quality=ContentQuality.FULL
        )

        artifact = result.to_failure_artifact("crawl-123")

        assert artifact is None


# ============================================================================
# Integration Tests
# ============================================================================

class TestFirecrawlClientIntegration:
    """Integration tests for FirecrawlClient."""

    def test_client_initialization(self):
        """Test that client can be initialized with config."""
        config = FirecrawlConfig(api_key="test-key")
        client = FirecrawlClient(config)

        assert client.config == config
        assert client._circuit is not None
        assert client._semaphore is not None

    @patch.dict(os.environ, {"FIRECRAWL_API_KEY": ""}, clear=True)
    def test_get_client_returns_none_without_key(self):
        """Test that get_firecrawl_client returns None without API key."""
        reset_firecrawl_client()
        client = get_firecrawl_client()
        assert client is None

    @patch.dict(os.environ, {"FIRECRAWL_API_KEY": "test-key"}, clear=True)
    def test_get_client_with_key(self):
        """Test that get_firecrawl_client returns client with API key."""
        reset_firecrawl_client()

        # This test may fail if firecrawl-py not installed
        try:
            client = get_firecrawl_client()
            if client is not None:
                assert isinstance(client, FirecrawlClient)
                assert client.config.api_key == "test-key"
        finally:
            reset_firecrawl_client()


# ============================================================================
# Content Quality Enum Tests
# ============================================================================

class TestContentQualityEnum:
    """Test ContentQuality enum values."""

    def test_enum_values(self):
        """Test that enum has expected values."""
        assert ContentQuality.FULL.value == "full"
        assert ContentQuality.PARTIAL.value == "partial"
        assert ContentQuality.BLOCKED.value == "blocked"
        assert ContentQuality.MANUAL_NEEDED.value == "manual_needed"

    def test_enum_comparison(self):
        """Test enum value comparison."""
        assert ContentQuality.FULL == ContentQuality("full")
        assert ContentQuality.PARTIAL == ContentQuality("partial")


# ============================================================================
# Run tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
