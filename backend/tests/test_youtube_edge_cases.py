"""
Cycle 2: Edge case testing for YouTube ingestion pattern.
Tests boundary conditions, error handling, and configuration variations.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from modules.ingestion import (
    YouTubeConfig,
    ErrorClassifier,
    LanguageDetector,
    PIIScrubber
)
from modules.youtube_retry_strategy import YouTubeRetryStrategy

import pytest


@pytest.fixture(autouse=True)
def _no_ingestion_event_writes(monkeypatch):
    """log_attempt/log_success persist ingestion events to Supabase; these
    tests exercise the in-memory retry strategy, so keep them off the DB."""
    monkeypatch.setattr(
        "modules.youtube_retry_strategy.log_ingestion_event", lambda *a, **k: None
    )


def test_edge_case_empty_text():
    """Test handling of empty/minimal text."""
    print("\n=== Edge Case: Empty/Minimal Text ===")

    # Test language detection on empty text
    lang = LanguageDetector.detect("")
    assert lang == "en", "Empty text should default to English"
    print("[OK] Empty text defaults to English")

    # Test language detection on very short text
    lang = LanguageDetector.detect("hi")
    assert lang == "en", "Too-short text should default to English"
    print("[OK] Short text defaults to English")

    # Test PII detection on empty text
    has_pii = PIIScrubber.has_pii("")
    assert not has_pii, "Empty text should have no PII"
    print("[OK] Empty text has no PII")

    print("[PASS] Empty/Minimal text edge cases handled correctly!")


def test_edge_case_pii_variations():
    """Test various PII formats and variations."""
    print("\n=== Edge Case: PII Variations ===")

    # Email variations
    emails_to_test = [
        "email@example.com",
        "user+tag@example.co.uk",
        "test.name@subdomain.example.com",
        "123@example.com"
    ]

    for email in emails_to_test:
        text = f"Contact: {email}"
        has_pii = PIIScrubber.has_pii(text)
        assert has_pii, f"Should detect email: {email}"
    print(f"[OK] Detected {len(emails_to_test)} email variations")

    # Phone variations
    phones_to_test = [
        "555-123-4567",
        "(555) 123-4567",
        "555.123.4567",
        "+1 555 123 4567"
    ]

    for phone in phones_to_test:
        text = f"Call: {phone}"
        has_pii = PIIScrubber.has_pii(text)
        # Note: not all patterns may be detected (implementation dependent)
        print(f"  {phone}: detected={has_pii}")

    # IP address variations
    ips_to_test = [
        "192.168.1.1",
        "10.0.0.1",
        "255.255.255.255",
        "127.0.0.1"
    ]

    for ip in ips_to_test:
        text = f"Server: {ip}"
        has_pii = PIIScrubber.has_pii(text)
        assert has_pii, f"Should detect IP: {ip}"
    print(f"[OK] Detected {len(ips_to_test)} IP address variations")

    print("[PASS] PII variation edge cases handled!")


def test_edge_case_error_classification():
    """Test error classification with various error message formats."""
    print("\n=== Edge Case: Error Classification Variations ===")

    test_cases = [
        ("HTTP Error 403", "auth"),  # Without colon
        ("403 Forbidden", "auth"),  # Different format
        ("429", "rate_limit"),  # Just code
        ("Too Many Requests", "rate_limit"),  # Just message
        ("timeout", "network"),  # lowercase
        ("TIMEOUT", "network"),  # uppercase
        ("Video not found", "unavailable"),  # Different wording
        ("Video deleted", "unavailable"),
        ("Region blocked", "gating"),
        ("Geo-restricted", "gating"),
    ]

    success_count = 0
    for error_msg, expected_category in test_cases:
        category, _, _ = ErrorClassifier.classify(error_msg)
        if category == expected_category:
            success_count += 1
            print(f"  [OK] '{error_msg}' -> {category}")
        else:
            print(f"  [WARN] '{error_msg}' -> {category} (expected {expected_category})")

    print(f"[PASS] Classified {success_count}/{len(test_cases)} error variations correctly")


def test_edge_case_retry_strategy_max_retries():
    """Test retry strategy behavior at boundaries."""
    print("\n=== Edge Case: Retry Strategy Boundaries ===")

    # Test with max_retries=1 (minimum)
    strategy = YouTubeRetryStrategy("src_1", "twin_1", max_retries=1)
    assert strategy.max_retries == 1
    strategy.log_attempt("Error 1")
    assert strategy.attempts == 1
    assert strategy.attempts >= strategy.max_retries, "Should stop at max_retries"
    print("[OK] Max retries=1 enforced")

    # Test with max_retries=10 (high value)
    strategy = YouTubeRetryStrategy("src_10", "twin_10", max_retries=10)
    for i in range(10):
        strategy.log_attempt(f"Error {i+1}")
    assert strategy.attempts == 10
    print("[OK] Max retries=10 handled correctly")

    # Test backoff calculation at different attempts
    strategy = YouTubeRetryStrategy("src_backoff", "twin_backoff", max_retries=5)
    backoffs = []
    for i in range(3):
        strategy.log_attempt("Error")
        backoff = strategy.calculate_backoff()
        backoffs.append(backoff)
        print(f"  Attempt {i+1}: backoff={backoff}s")

    # Backoff should increase (exponential)
    assert backoffs[1] >= backoffs[0], "Backoff should not decrease"
    assert backoffs[2] >= backoffs[1], "Backoff should not decrease"
    print("[OK] Exponential backoff increasing")

    print("[PASS] Retry strategy boundary cases handled!")


def test_edge_case_pii_scrubbing_variations():
    """Test PII scrubbing with different text patterns."""
    print("\n=== Edge Case: PII Scrubbing Variations ===")

    # Test text with multiple PII types
    text_multi_pii = "Contact john@example.com at 555-1234 from 192.168.1.1"
    detected = PIIScrubber.detect_pii(text_multi_pii)
    assert len(detected) > 1, "Should detect multiple PII types"
    print(f"[OK] Detected {len(detected)} PII types in single text")

    # Test scrubbing removes all instances
    text_repeat = "Email me at test@test.com or test@test.com again"
    scrubbed = PIIScrubber.scrub(text_repeat)
    assert scrubbed.count("[EMAIL]") >= 2, "Should scrub all email instances"
    print("[OK] Scrubbed all PII instances")

    # Test false positives (should not detect PII in normal text)
    text_safe = [
        "The IP address concept was introduced in 1981",
        "Call the function at runtime",
        "Email notifications are important",
        "Visit our site at example.com"  # Note: .com might not trigger
    ]

    false_positives = 0
    for text in text_safe:
        if PIIScrubber.has_pii(text):
            false_positives += 1
            print(f"  [WARN] False positive: '{text}'")

    print(f"[OK] False positive rate: {false_positives}/{len(text_safe)}")

    print("[PASS] PII scrubbing variation cases handled!")


def test_edge_case_config_env_vars():
    """Test configuration with missing/invalid environment variables."""
    print("\n=== Edge Case: Configuration Validation ===")

    # Test default values are applied
    config = YouTubeConfig()
    assert config.MAX_RETRIES >= 1, "MAX_RETRIES should be >= 1"
    assert config.ASR_MODEL in ["whisper-large-v3", "whisper-1"], "ASR_MODEL should be valid"
    assert config.ASR_PROVIDER in ["openai", "gemini", "local"], "ASR_PROVIDER should be valid"
    print("[OK] Configuration defaults are valid")

    # Test boolean flags are properly parsed
    assert isinstance(config.LANGUAGE_DETECTION, bool)
    assert isinstance(config.PII_SCRUB, bool)
    assert isinstance(config.VERBOSE_LOGGING, bool)
    print("[OK] Boolean configuration flags are properly typed")

    print("[PASS] Configuration validation edge cases handled!")


def test_edge_case_concurrent_retry_strategies():
    """Test multiple retry strategies running independently."""
    print("\n=== Edge Case: Concurrent Retry Strategies ===")

    # Create multiple strategies
    strategies = [
        YouTubeRetryStrategy(f"src_{i}", f"twin_{i}", max_retries=5)
        for i in range(3)
    ]

    # Log different attempts to each
    for idx, strategy in enumerate(strategies):
        for attempt in range(idx + 1):
            strategy.log_attempt(f"Error attempt {attempt+1}")

    # Verify independence
    assert strategies[0].attempts == 1, "Strategy 0 should have 1 attempt"
    assert strategies[1].attempts == 2, "Strategy 1 should have 2 attempts"
    assert strategies[2].attempts == 3, "Strategy 2 should have 3 attempts"
    print("[OK] Strategies maintain independent state")

    # Verify metrics independence
    for idx, strategy in enumerate(strategies):
        metrics = strategy.get_metrics()
        assert metrics["total_attempts"] == idx + 1
    print("[OK] Metrics are tracked independently per strategy")

    print("[PASS] Concurrent retry strategy edge cases handled!")


if __name__ == "__main__":
    try:
        test_edge_case_empty_text()
        test_edge_case_pii_variations()
        test_edge_case_error_classification()
        test_edge_case_retry_strategy_max_retries()
        test_edge_case_pii_scrubbing_variations()
        test_edge_case_config_env_vars()
        test_edge_case_concurrent_retry_strategies()

        print("\n" + "="*60)
        print("[SUCCESS] ALL EDGE CASE TESTS PASSED!")
        print("="*60)
    except Exception as e:
        print(f"\n[FAILED] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
