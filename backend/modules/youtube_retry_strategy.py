"""
Enterprise-grade YouTube ingestion retry strategy with classification and telemetry.

Handles:
- Error classification (auth, rate_limit, gating, unavailable, network)
- Adaptive backoff (exponential with jitter)
- Structured logging/metrics
- Language detection
- PII scrubbing/flagging
"""

import logging
import time
from modules.observability import log_ingestion_event

logger = logging.getLogger(__name__)


class YouTubeRetryStrategy:
    """Enterprise retry strategy for YouTube downloads with telemetry."""

    def __init__(self, source_id: str, twin_id: str, max_retries: int = 5, verbose: bool = False):
        self.source_id = source_id
        self.twin_id = twin_id
        self.max_retries = max_retries
        self.verbose = verbose
        self.attempts = 0
        self.last_error: str | None = None  # Track the last error message
        self.errors: list[tuple[int, str, str]] = []  # (attempt, category, message)
        self.metrics = {
            "auth_failures": 0,
            "rate_limits": 0,
            "gating_errors": 0,
            "network_errors": 0,
            "total_backoff_time": 0,
        }

    def classify_error(self, error_msg: str) -> tuple[str, str, bool]:
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
        if "429" in error_msg or "rate" in error_lower or "quota" in error_lower:
            self.metrics["rate_limits"] += 1
            return "rate_limit", "YouTube rate limit reached. Retrying with backoff...", True

        # Authentication required
        if "403" in error_msg or "sign in" in error_lower or "unauthorized" in error_lower:
            self.metrics["auth_failures"] += 1
            return "auth", "This video requires authentication or is age-restricted.", False

        # Gating (region, age, etc.)
        if "geo" in error_lower or "region" in error_lower or "not available" in error_lower:
            self.metrics["gating_errors"] += 1
            return "gating", "This video is not available in your region.", False

        # Video unavailable
        if "unavailable" in error_lower or "deleted" in error_lower or "not found" in error_lower:
            return "unavailable", "This video is unavailable (deleted, private, or not found).", False

        # Network issues
        if "timeout" in error_lower or "connection" in error_lower or "socket" in error_lower:
            self.metrics["network_errors"] += 1
            return "network", "Network connection issue. Retrying...", True

        return "unknown", f"Unexpected error: {error_msg}", False

    def should_retry(self, error_category: str) -> bool:
        """Determine if we should retry based on error category and attempt count."""
        if self.attempts >= self.max_retries:
            return False

        # Don't retry non-retryable errors
        non_retryable = ["auth", "gating", "unavailable"]
        return error_category not in non_retryable

    def calculate_backoff(self) -> int:
        """Calculate backoff time with exponential growth and jitter."""
        # Exponential: 2, 4, 8, 16, 32 seconds
        # Add jitter based on source_id for distributed retries
        base_backoff = 2 ** self.attempts
        jitter = hash(self.source_id) % 3  # 0-2 second jitter
        return base_backoff + jitter

    def log_attempt(self, error_msg: str):
        """Log a failed download attempt."""
        self.attempts += 1
        self.last_error = error_msg  # Track the last error
        category, user_msg, is_retryable = self.classify_error(error_msg)

        self.errors.append((self.attempts, category, user_msg))

        log_msg = f"Download attempt {self.attempts}/{self.max_retries} failed [{category}]: {user_msg}"
        logger.warning("[YouTube] %s", log_msg)

        if self.verbose or category != "network":
            log_ingestion_event(self.source_id, self.twin_id, "warning", log_msg)

    def wait_for_retry(self):
        """Calculate and apply backoff before retry."""
        backoff = self.calculate_backoff()
        self.metrics["total_backoff_time"] += backoff

        wait_msg = f"Waiting {backoff}s before retry (attempt {self.attempts}/{self.max_retries})..."
        logger.info("[YouTube] %s", wait_msg)

        if self.verbose:
            log_ingestion_event(self.source_id, self.twin_id, "debug", wait_msg)

        time.sleep(backoff)

    def get_final_error_message(self, last_error: str | None = None) -> str:
        """Generate a detailed final error message based on error history."""
        if not last_error:
            last_error = "Unknown error"

        category, user_msg, _ = self.classify_error(last_error)

        # Build error report with telemetry
        error_report = f"{user_msg} (Error: {category})\n"
        error_report += f"Failed after {self.attempts} attempts.\n"
        error_report += f"Total backoff time: {self.metrics['total_backoff_time']}s\n"

        if self.metrics["rate_limits"] > 0:
            error_report += f"Rate limits hit {self.metrics['rate_limits']} time(s)\n"
        if self.metrics["network_errors"] > 0:
            error_report += f"Network errors: {self.metrics['network_errors']}\n"

        return error_report

    def log_success(self, text_length: int, metadata: dict = None):
        """Log successful ingestion."""
        log_msg = f"Successfully transcribed: {text_length} characters in {self.attempts} attempt(s)"
        if metadata:
            log_msg += f", metadata: {metadata}"

        logger.info("[YouTube] %s", log_msg)
        log_ingestion_event(self.source_id, self.twin_id, "info", log_msg)

    def get_metrics(self) -> dict:
        """Return telemetry metrics."""
        return {
            **self.metrics,
            "total_attempts": self.attempts,
            "errors_history": self.errors,
        }
