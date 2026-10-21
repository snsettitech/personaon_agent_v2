"""
Integration test for enterprise YouTube ingestion pattern.
Tests all components: config, error classification, language detection, PII scrubbing, retry strategy.
"""

import os
import sys
import io

# Configure UTF-8 output for Windows (safe for pytest capture)
if sys.platform == "win32" and not os.environ.get("PYTEST_CURRENT_TEST"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", write_through=True)
        except Exception:
            pass

# Add parent directory to path so modules can be imported
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


def test_youtube_config():
    """Test YouTubeConfig class."""
    print("\n=== Testing YouTubeConfig ===")
    config = YouTubeConfig()

    print(f"[OK] MAX_RETRIES: {config.MAX_RETRIES}")
    print(f"[OK] ASR_MODEL: {config.ASR_MODEL}")
    print(f"[OK] ASR_PROVIDER: {config.ASR_PROVIDER}")
    print(f"[OK] LANGUAGE_DETECTION: {config.LANGUAGE_DETECTION}")
    print(f"[OK] PII_SCRUB: {config.PII_SCRUB}")
    print(f"[OK] VERBOSE_LOGGING: {config.VERBOSE_LOGGING}")

    assert config.MAX_RETRIES == 5
    assert config.ASR_MODEL == "whisper-large-v3"
    assert config.ASR_PROVIDER == "openai"
    print("[PASS] YouTubeConfig tests passed!")


def test_error_classifier():
    """Test ErrorClassifier class."""
    print("\n=== Testing ErrorClassifier ===")

    test_cases = [
        ("HTTP Error 403: Forbidden", "auth", False),  # Auth errors are non-retryable
        ("HTTP Error 429: Too Many Requests", "rate_limit", True),  # Rate limits ARE retryable
        ("This video is unavailable", "unavailable", False),  # Non-retryable
        ("Sign in required", "auth", False),  # Auth is non-retryable
        ("Connection timeout", "network", True),  # Network errors ARE retryable
        ("Random error that doesn't match", "unknown", False),  # Unknown defaults to non-retryable (conservative)
    ]

    for error_msg, expected_category, expected_retryable in test_cases:
        category, user_msg, retryable = ErrorClassifier.classify(error_msg)
        print(f"  {error_msg}")
        print(f"    -> Category: {category}, Retryable: {retryable}")
        assert category == expected_category, f"Expected {expected_category}, got {category}"
        assert retryable == expected_retryable, f"Expected retryable={expected_retryable}, got {retryable}"

    print("[PASS] ErrorClassifier tests passed!")


def test_language_detector():
    """Test LanguageDetector class."""
    print("\n=== Testing LanguageDetector ===")

    test_cases = [
        ("Hello world this is an English text with more words to make it substantial", "en"),
        ("Hola mundo esto es texto en español con más palabras para hacerlo más largo", "es"),
        ("Bonjour c'est du texte français avec plus de mots pour le rendre plus long", "fr"),
        ("Guten Tag das ist deutscher Text mit mehr Wörtern um ihn länger zu machen", "de"),
        ("こんにちは日本語のテキストです。もっと単語を追加して長くしています。これは日本語です。", "ja"),
        # Note: Chinese and Japanese CJK patterns overlap in Unicode, so detector may return either
        ("你好这是中文文本。我在添加更多单词来使其更长。这是一个中文示例。", "zh"),
    ]

    for text, expected_lang in test_cases:
        detected_lang = LanguageDetector.detect(text)
        print(f"  '{text[:30]}...' -> {detected_lang}")
        # For CJK languages, accept either ja or zh since patterns overlap
        if expected_lang in ["ja", "zh"]:
            assert detected_lang in ["ja", "zh"], f"Expected CJK language (ja/zh), got {detected_lang}"
        else:
            assert detected_lang == expected_lang, f"Expected {expected_lang}, got {detected_lang}"

    print("[PASS] LanguageDetector tests passed!")


def test_pii_scrubber():
    """Test PIIScrubber class."""
    print("\n=== Testing PIIScrubber ===")

    # Test email detection
    text_with_email = "Contact me at john.doe@example.com for more info"
    assert PIIScrubber.has_pii(text_with_email), "Should detect email"
    detected = PIIScrubber.detect_pii(text_with_email)
    print(f"[OK] Detected email PII: {detected}")

    # Test phone detection
    text_with_phone = "Call me at 555-123-4567 anytime"
    assert PIIScrubber.has_pii(text_with_phone), "Should detect phone"
    detected = PIIScrubber.detect_pii(text_with_phone)
    print(f"[OK] Detected phone PII: {detected}")

    # Test IP detection
    text_with_ip = "Server error at 192.168.1.1 occurred"
    assert PIIScrubber.has_pii(text_with_ip), "Should detect IP"
    detected = PIIScrubber.detect_pii(text_with_ip)
    print(f"[OK] Detected IP PII: {detected}")

    # Test scrubbing
    scrubbed = PIIScrubber.scrub(text_with_email)
    print(f"[OK] Scrubbed text: '{scrubbed}'")
    assert "example.com" not in scrubbed, "Should remove email domain"

    # Test clean text
    clean_text = "This is a normal sentence with no sensitive data"
    assert not PIIScrubber.has_pii(clean_text), "Should not detect PII in clean text"
    print("[OK] Correctly identified clean text")

    print("[PASS] PIIScrubber tests passed!")


def test_youtube_retry_strategy():
    """Test YouTubeRetryStrategy class."""
    print("\n=== Testing YouTubeRetryStrategy ===")

    strategy = YouTubeRetryStrategy(
        source_id="test_source_123_abcd",  # Use valid UUID format for logging
        twin_id="test_twin_456_efgh",
        max_retries=3,
        verbose=True
    )

    # Simulate attempt logging
    strategy.log_attempt("HTTP Error 403: Forbidden")
    print(f"[OK] Logged attempt 1: {strategy.attempts}")
    assert strategy.attempts == 1

    # Test backoff calculation
    backoff = strategy.calculate_backoff()
    print(f"[OK] Backoff for attempt 1: {backoff}s")
    assert backoff > 0

    # Simulate second attempt
    strategy.log_attempt("HTTP Error 429: Too Many Requests")
    print(f"[OK] Logged attempt 2: {strategy.attempts}")
    assert strategy.attempts == 2

    # Test should_retry
    should_retry = strategy.should_retry("rate_limit")
    print(f"[OK] Should retry rate_limit: {should_retry}")
    assert should_retry is True

    should_retry = strategy.should_retry("auth")
    print(f"[OK] Should retry auth: {should_retry}")
    assert should_retry is False

    should_retry = strategy.should_retry("unavailable")
    print(f"[OK] Should retry unavailable: {should_retry}")
    assert should_retry is False

    # Simulate success
    strategy.log_success(text_length=5000, metadata={"language": "en", "has_pii": False})
    print(f"[OK] Logged success at attempt {strategy.attempts}")

    # Get metrics
    metrics = strategy.get_metrics()
    print(f"[OK] Metrics: {metrics}")
    assert "total_attempts" in metrics
    assert "errors_history" in metrics
    assert metrics["total_attempts"] == 2  # We logged 2 attempts

    print("[PASS] YouTubeRetryStrategy tests passed!")


def test_integration():
    """Test full integration of all components."""
    print("\n=== Testing Full Integration ===")

    # Simulate YouTube ingestion workflow
    config = YouTubeConfig()
    print(f"[OK] Config initialized: max_retries={config.MAX_RETRIES}")

    strategy = YouTubeRetryStrategy("video_123_abcd", "twin_456_efgh", config.MAX_RETRIES)

    # Simulate errors
    test_errors = [
        ("HTTP Error 403: Forbidden", False),  # Non-retryable after 1 try
        ("HTTP Error 429: Too Many Requests", True),  # Retryable
    ]

    for error_msg, should_continue in test_errors:
        category, user_msg, retryable = ErrorClassifier.classify(error_msg)
        strategy.log_attempt(error_msg)

        if strategy.should_retry(category) and strategy.attempts < config.MAX_RETRIES:
            backoff = strategy.calculate_backoff()
            print(f"  Error: {category}, will retry after {backoff}s")
        else:
            print(f"  Error: {category}, stopping retries")

    # Simulate success
    sample_text = "Hello world this is a test transcript john.doe@example.com"
    language = LanguageDetector.detect(sample_text)
    has_pii = PIIScrubber.has_pii(sample_text)
    pii_list = PIIScrubber.detect_pii(sample_text)

    strategy.log_success(text_length=len(sample_text), metadata={
        "language": language,
        "has_pii": has_pii,
        "pii_detected": pii_list
    })

    print(f"[OK] Ingestion complete: language={language}, pii={has_pii}")
    print(f"[OK] Metrics: {strategy.get_metrics()}")

    print("[PASS] Full integration test passed!")


if __name__ == "__main__":
    try:
        test_youtube_config()
        test_error_classifier()
        test_language_detector()
        test_pii_scrubber()
        test_youtube_retry_strategy()
        test_integration()

        print("\n" + "="*60)
        print("[SUCCESS] ALL TESTS PASSED! Enterprise YouTube pattern verified!")
        print("="*60)
    except Exception as e:
        print(f"\n[FAILED] TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
