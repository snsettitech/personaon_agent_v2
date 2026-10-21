"""
Ingestion configuration classes and shared utilities.

Extracted from ingestion.py -- contains YouTubeConfig, ErrorClassifier,
LanguageDetector, PIIScrubber, and small helper functions used across
multiple ingestion sub-modules.
"""

import logging
import os
import re

logger = logging.getLogger(__name__)
from typing import Any


# ============================================================================
# Enterprise Configuration & Utilities
# ============================================================================

class YouTubeConfig:
    """Enterprise-grade YouTube ingestion configuration."""
    MAX_RETRIES = int(os.getenv("YOUTUBE_MAX_RETRIES", "5"))
    ASR_MODEL = os.getenv("YOUTUBE_ASR_MODEL", "whisper-large-v3")
    ASR_PROVIDER = os.getenv("YOUTUBE_ASR_PROVIDER", "openai")
    LANGUAGE_DETECTION = os.getenv("YOUTUBE_LANGUAGE_DETECTION", "true").lower() == "true"
    PII_SCRUB = os.getenv("YOUTUBE_PII_SCRUB", "true").lower() == "true"
    VERBOSE_LOGGING = os.getenv("YOUTUBE_VERBOSE_LOGGING", "false").lower() == "true"
    COOKIES_FILE = os.getenv("YOUTUBE_COOKIES_FILE")
    PROXY = os.getenv("YOUTUBE_PROXY")


class ErrorClassifier:
    """Classify YouTube/yt-dlp errors for better handling and telemetry."""

    @staticmethod
    def classify(error_msg: str) -> tuple[str, str, bool]:
        """
        Classify error and return (category, user_message, is_retryable).

        Categories:
        - auth: Authentication/login required
        - rate_limit: HTTP 429, quota exceeded
        - gating: Age/region/access restrictions
        - unavailable: Video deleted/private
        - network: Connection/timeout issues
        - unknown: Unclassified
        """
        error_lower = error_msg.lower()

        # Rate limiting
        if "429" in error_msg or "rate" in error_lower or "quota" in error_lower or "too many requests" in error_lower:
            return "rate_limit", "YouTube rate limit reached. Retrying with backoff...", True

        # Authentication required
        if "403" in error_msg or "sign in" in error_lower or "unauthorized" in error_lower:
            return "auth", "This video requires authentication or is age-restricted.", False

        # Gating (region, age, etc.)
        if "geo" in error_lower or "region" in error_lower or "not available" in error_lower:
            return "gating", "This video is not available in your region.", False

        # Video unavailable
        if "unavailable" in error_lower or "deleted" in error_lower or "not found" in error_lower:
            return "unavailable", "This video is unavailable (deleted, private, or not found).", False

        # Network issues
        if "timeout" in error_lower or "connection" in error_lower or "socket" in error_lower:
            return "network", "Network connection issue. Retrying...", True

        return "unknown", f"Unexpected error: {error_msg}", False


class LanguageDetector:
    """Lightweight language detection for transcripts."""

    # Simple heuristics for common languages (word counts and patterns)
    LANGUAGE_PATTERNS = {
        "en": [r"\b(the|and|a|to|of|in|is|that|it)\b"],
        "es": [r"\b(el|la|de|que|y|a|en|un|es)\b"],
        "fr": [r"\b(le|la|de|et|a|en|un|est|c'est)\b"],
        "de": [r"\b(der|die|und|in|den|von|zu|das)\b"],
        "ja": [r"[ぁ-ん]|[ァ-ヴー]|[一-龥]"],
        "zh": [r"[\u4e00-\u9fff]"],
    }

    @staticmethod
    def detect(text: str) -> str:
        """Detect language of text. Returns language code (e.g., 'en', 'es')."""
        if not text or len(text) < 10:
            return "en"  # Default

        text_lower = text.lower()
        scores = {}

        for lang, patterns in LanguageDetector.LANGUAGE_PATTERNS.items():
            count = 0
            for pattern in patterns:
                count += len(re.findall(pattern, text_lower))
            scores[lang] = count

        if scores:
            return max(scores, key=scores.get)
        return "en"


class PIIScrubber:
    """Lightweight PII detection and redaction."""

    # Regex patterns for common PII (very permissive, for flagging)
    PATTERNS = {
        "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "phone": r"(?:\+1[-.\s]?)?\(?([0-9]{3})\)?[-.\s]?([0-9]{3})[-.\s]?([0-9]{4})\b",  # Matches multiple formats
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "credit_card": r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b",
        "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
    }

    @staticmethod
    def detect_pii(text: str) -> dict[str, list[str]]:
        """Detect PII in text. Returns dict of pii_type -> [matches]."""
        detected = {}
        for pii_type, pattern in PIIScrubber.PATTERNS.items():
            matches = re.findall(pattern, text)
            if matches:
                detected[pii_type] = matches
        return detected

    @staticmethod
    def has_pii(text: str) -> bool:
        """Check if text contains any PII."""
        return bool(PIIScrubber.detect_pii(text))

    @staticmethod
    def scrub(text: str) -> str:
        """Redact PII from text."""
        for pii_type, pattern in PIIScrubber.PATTERNS.items():
            placeholder = f"[{pii_type.upper()}]"
            text = re.sub(pattern, placeholder, text)
        return text


def _to_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
    return default


def _truncate_text(value: str | None, limit: int = 800) -> str:
    text_value = str(value or "").strip()
    if not text_value:
        return ""
    return text_value[:limit]


def _resolve_tenant_id(twin_id: str, source_id: str | None = None) -> str | None:
    """Best-effort tenant lookup used for audit logging paths."""
    from modules.observability import supabase, log_ingestion_event
    try:
        twin_res = supabase.table("twins").select("tenant_id").eq("id", twin_id).single().execute()
        return twin_res.data.get("tenant_id") if twin_res.data else None
    except Exception as exc:
        message = f"Tenant lookup failed for twin {twin_id}: {type(exc).__name__}"
        if source_id and twin_id:
            try:
                log_ingestion_event(source_id, twin_id, "warning", message)
            except Exception:
                logger.warning("[Ingestion] %s", message)
        else:
            logger.warning("[Ingestion] %s", message)
        return None
