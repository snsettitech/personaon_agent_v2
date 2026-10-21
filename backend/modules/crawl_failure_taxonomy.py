"""
Crawl Failure Taxonomy Module (Phase 1B.3)

Standardized failure classification and artifact generation for crawl operations.

Failure Categories:
- hard_block: Never retry (security/policy violations)
- soft_fail: May retry with backoff (transient issues)

Failure Types:
- auth: Authentication required (401/403)
- rate_limit: Rate limited (429)
- gating: Bot protection/captcha
- unavailable: Server error (5xx)
- network: Connection/DNS/TLS errors
- timeout: Request timeout
- parser_fail: Content parsing failed
- ssrf_blocked: Private IP/security block
- content_type_blocked: Non-allowed content type
- size_exceeded: Content too large
- too_many_redirects: Redirect loop/limit
- private_ip_blocked: Private IP range
"""

from enum import Enum
from typing import Any
from datetime import datetime


class FailureCategory(str, Enum):
    """High-level failure category."""
    HARD_BLOCK = "hard_block"  # Never retry
    SOFT_FAIL = "soft_fail"    # May retry


class FailureType(str, Enum):
    """Specific failure types."""
    # Hard blocks (security/policy)
    SSRF_BLOCKED = "ssrf_blocked"
    PRIVATE_IP_BLOCKED = "private_ip_blocked"
    CONTENT_TYPE_BLOCKED = "content_type_blocked"
    SIZE_EXCEEDED = "size_exceeded"
    TOO_MANY_REDIRECTS = "too_many_redirects"
    INVALID_HOSTNAME = "invalid_hostname"
    SCHEME_BLOCKED = "scheme_blocked"

    # Soft fails (may retry)
    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    GATING = "gating"
    UNAVAILABLE = "unavailable"
    NETWORK = "network"
    TIMEOUT = "timeout"
    PARSER_FAIL = "parser_fail"


# Retryability mapping
RETRYABLE_FAILURES = {
    # Hard blocks - never retry
    FailureType.SSRF_BLOCKED: False,
    FailureType.PRIVATE_IP_BLOCKED: False,
    FailureType.CONTENT_TYPE_BLOCKED: False,
    FailureType.SIZE_EXCEEDED: False,
    FailureType.TOO_MANY_REDIRECTS: False,
    FailureType.INVALID_HOSTNAME: False,
    FailureType.SCHEME_BLOCKED: False,

    # Soft fails - retry with backoff
    FailureType.AUTH: False,  # Auth won't succeed on retry
    FailureType.RATE_LIMIT: True,  # Retry after delay
    FailureType.GATING: False,  # Bot protection won't change
    FailureType.UNAVAILABLE: True,  # Server may recover
    FailureType.NETWORK: True,  # Network may recover
    FailureType.TIMEOUT: True,  # Timeout may be transient
    FailureType.PARSER_FAIL: False,  # Parse error won't change
}


class FailureStage(str, Enum):
    """Stage of crawl where failure occurred."""
    SAFETY_CHECK = "safety_check"
    DNS_RESOLUTION = "dns_resolution"
    CONNECT = "connect"
    FETCH = "fetch"
    VALIDATE = "validate"
    PARSE = "parse"
    PERSIST = "persist"


def classify_failure(
    status_code: int | None,
    error: str | None,
    stage: FailureStage = FailureStage.FETCH,
) -> FailureType:
    """
    Classify an HTTP error or exception into failure taxonomy.

    Args:
        status_code: HTTP status code if available
        error: Error message or exception string
        stage: Stage where failure occurred

    Returns:
        FailureType classification
    """
    error_lower = (error or "").lower()

    # Stage-specific classifications
    if stage == FailureStage.SAFETY_CHECK:
        if "private" in error_lower or "ssrf" in error_lower:
            return FailureType.SSRF_BLOCKED
        if "content type" in error_lower:
            return FailureType.CONTENT_TYPE_BLOCKED
        if "size" in error_lower or "exceed" in error_lower:
            return FailureType.SIZE_EXCEEDED
        if "redirect" in error_lower:
            return FailureType.TOO_MANY_REDIRECTS
        if "scheme" in error_lower:
            return FailureType.SCHEME_BLOCKED
        if "hostname" in error_lower:
            return FailureType.INVALID_HOSTNAME

    # Status code based classification
    if status_code:
        if status_code in (401, 403):
            return FailureType.AUTH
        if status_code == 429:
            return FailureType.RATE_LIMIT
        if status_code >= 500:
            return FailureType.UNAVAILABLE

    # Error message based classification
    if any(x in error_lower for x in ["timeout", "timed out"]):
        return FailureType.TIMEOUT
    if any(x in error_lower for x in ["connection", "dns", "network"]):
        return FailureType.NETWORK
    if any(x in error_lower for x in ["ssl", "certificate", "tls"]):
        return FailureType.NETWORK
    if any(x in error_lower for x in ["cloudflare", "captcha", "bot", "blocked"]):
        return FailureType.GATING
    if any(x in error_lower for x in ["parse", "decode", "encoding", "json", "xml"]):
        return FailureType.PARSER_FAIL
    if any(x in error_lower for x in ["private ip", "internal ip"]):
        return FailureType.PRIVATE_IP_BLOCKED
    if "too many redirects" in error_lower:
        return FailureType.TOO_MANY_REDIRECTS

    # Default to network for unknown errors
    return FailureType.NETWORK


def is_retryable(failure_type: FailureType) -> bool:
    """
    Determine if a failure type is retryable.

    Args:
        failure_type: Type of failure

    Returns:
        True if the failure should be retried
    """
    return RETRYABLE_FAILURES.get(failure_type, False)


def get_failure_category(failure_type: FailureType) -> FailureCategory:
    """
    Get the category for a failure type.

    Args:
        failure_type: Type of failure

    Returns:
        FailureCategory (hard_block or soft_fail)
    """
    if is_retryable(failure_type):
        return FailureCategory.SOFT_FAIL

    hard_block_types = {
        FailureType.SSRF_BLOCKED,
        FailureType.PRIVATE_IP_BLOCKED,
        FailureType.CONTENT_TYPE_BLOCKED,
        FailureType.SIZE_EXCEEDED,
        FailureType.TOO_MANY_REDIRECTS,
        FailureType.INVALID_HOSTNAME,
        FailureType.SCHEME_BLOCKED,
    }

    if failure_type in hard_block_types:
        return FailureCategory.HARD_BLOCK

    # Auth, gating, parser_fail are soft fails but not retryable
    return FailureCategory.SOFT_FAIL


def create_failure_artifact(
    url: str,
    canonical_url: str,
    crawl_id: str,
    crawl_page_id: str | None,
    failure_type: FailureType,
    error_detail: str,
    stage: FailureStage,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a standardized failure artifact.

    Args:
        url: Original URL
        canonical_url: Normalized canonical URL
        crawl_id: Crawl run ID
        crawl_page_id: Page ID if available
        failure_type: Type of failure
        error_detail: Detailed error message
        stage: Stage where failure occurred
        metadata: Additional context

    Returns:
        Failure artifact dictionary
    """
    return {
        "version": "1.0",
        "timestamp": datetime.utcnow().isoformat(),
        "url": url,
        "canonical_url": canonical_url,
        "crawl_id": crawl_id,
        "crawl_page_id": crawl_page_id,
        "failure": {
            "type": failure_type.value,
            "category": get_failure_category(failure_type).value,
            "retryable": is_retryable(failure_type),
            "stage": stage.value,
            "detail": error_detail,
        },
        "context": metadata or {},
    }


def create_failure_summary(
    crawl_id: str,
    failures: list,
) -> dict[str, Any]:
    """
    Create a summary of all failures in a crawl.

    Args:
        crawl_id: Crawl run ID
        failures: List of failure artifacts

    Returns:
        Summary dictionary
    """
    by_type = {}
    by_category = {cat.value: 0 for cat in FailureCategory}
    retryable_count = 0

    for failure in failures:
        ftype = failure.get("failure", {}).get("type", "unknown")
        cat = failure.get("failure", {}).get("category", "unknown")
        retry = failure.get("failure", {}).get("retryable", False)

        by_type[ftype] = by_type.get(ftype, 0) + 1
        by_category[cat] = by_category.get(cat, 0) + 1
        if retry:
            retryable_count += 1

    return {
        "crawl_id": crawl_id,
        "timestamp": datetime.utcnow().isoformat(),
        "total_failures": len(failures),
        "by_type": by_type,
        "by_category": by_category,
        "retryable": retryable_count,
        "not_retryable": len(failures) - retryable_count,
    }
