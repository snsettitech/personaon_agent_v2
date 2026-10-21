"""
Training Metrics Module

Computes creator-scoped profile training metrics for twins/profiles.

V1 Heuristic Implementation:
- Words Processed: Total words from successfully ingested sources
- Questions Answerable: Estimated coverage based on content volume and diversity
- Mind Score: 0-100 training completeness score

NOTE: This is a V1 heuristic implementation. V2 will use eval-backed metrics.
"""

import logging
import re
from typing import Any
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

from modules.observability import supabase


# =============================================================================
# Constants and Configuration
# =============================================================================

class MetricConstants:
    """Central constants for metric calculations."""

    # Version tracking
    METHOD_VERSION = "v1_heuristic"

    # Word counting
    WORD_REGEX = r"\b[a-zA-Z0-9\'-]+\b"
    MIN_WORD_LENGTH = 1

    # Question estimation baseline: ~90 words per question on average
    WORDS_PER_QUESTION_BASELINE = 90

    # Compression factor to prevent inflation
    COMPRESSION_FACTOR = 0.85

    # Mind Score weights (must sum to 1.0)
    VOLUME_WEIGHT = 0.25
    DIVERSITY_WEIGHT = 0.20
    QUALITY_WEIGHT = 0.20
    FRESHNESS_WEIGHT = 0.10
    STRUCTURE_WEIGHT = 0.15
    VERIFICATION_WEIGHT = 0.10

    # Volume score thresholds (logarithmic scale)
    VOLUME_TIERS = [
        (0, 0),           # 0 words = 0 score
        (100, 10),        # 100 words = 10 score
        (1000, 25),       # 1K words = 25 score
        (10000, 50),      # 10K words = 50 score
        (50000, 70),      # 50K words = 70 score
        (100000, 85),     # 100K words = 85 score
        (500000, 95),     # 500K words = 95 score
        (1000000, 100),   # 1M words = 100 score
    ]

    # Source type diversity multipliers
    SOURCE_TYPE_MULTIPLIERS = {
        "youtube": 1.2,
        "web": 1.0,
        "file": 1.0,
        "podcast": 1.3,
        "x": 1.1,
        "linkedin": 1.2,
        "instagram": 1.1,
        "facebook": 1.0,
        "unknown": 0.8,
    }

    # Mind score labels
    SCORE_LABELS = [
        (0, 15, "Early"),
        (15, 35, "Growing"),
        (35, 55, "Developing"),
        (55, 75, "Strong"),
        (75, 90, "Highly Trained"),
        (90, 100, "Expert"),
    ]

    # Source statuses that count as successfully processed
    # NOTE: "staged" is intentionally excluded - sources must be fully processed
    SUCCESSFUL_STATUSES = ("live", "processed", "active")


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class SourceMetrics:
    """Metrics for a single source."""
    source_id: str
    source_type: str
    status: str
    word_count: int = 0
    extracted_at: str | None = None
    has_content: bool = False


@dataclass
class TrainingMetrics:
    """Computed training metrics for a twin/profile."""
    # Core metrics
    words_processed: int = 0
    words_processed_display: str = "0"
    questions_answerable_est: int = 0
    questions_answerable_display: str = "0"
    mind_score: int = 0
    mind_score_label: str = "Early"

    # Metadata
    method_version: str = MetricConstants.METHOD_VERSION
    last_computed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: str = "Estimated metrics based on ingested content volume, diversity, and extraction quality."

    # Debug/Internal fields (not exposed in public API)
    component_scores: dict[str, float] = field(default_factory=dict)
    source_count: int = 0
    failed_source_count: int = 0
    source_type_diversity: int = 0


# =============================================================================
# Word Counting Utility
# =============================================================================

def count_words(text: str | None) -> int:
    """
    Count words in text using regex-based word tokenization.

    Args:
        text: Input text to count words in

    Returns:
        Number of words (0 if text is None/empty)

    Note:
        - Uses regex to find word boundaries
        - Handles punctuation, unicode, and special characters
        - Does NOT count chunks - this is actual word count from extracted text
    """
    if not text or not isinstance(text, str):
        return 0

    # Normalize whitespace and strip
    text = text.strip()
    if not text:
        return 0

    # Use regex to find word tokens
    # Matches alphanumeric sequences including apostrophes and hyphens
    words = re.findall(MetricConstants.WORD_REGEX, text)

    # Filter out very short tokens (likely noise)
    valid_words = [w for w in words if len(w) >= MetricConstants.MIN_WORD_LENGTH]

    return len(valid_words)


# =============================================================================
# Number Formatting Utility
# =============================================================================

def format_number_compact(n: int) -> str:
    """
    Format a number in compact form (e.g., 167123 -> "167.1K").

    Args:
        n: Number to format

    Returns:
        Compact string representation

    Formatting rules:
        - 0-999: as-is (e.g., "999")
        - 1K-999K: in thousands (e.g., "1K", "167.1K")
        - 1M-999M: in millions (e.g., "1M", "2.5M")
        - 1B+: in billions (e.g., "1B", "1.5B")

    Edge case handling:
        - 999500+ -> rounds to "1.0M" (not "1000.0K")
        - 999500000+ -> rounds to "1.0B" (not "1000.0M")
    """
    if n < 1000:
        return str(n)
    if n < 999500:  # Threshold to avoid "1000.0K"
        # Format as X.XK
        value = n / 1000
        # Show one decimal if not a whole number
        if value == int(value):
            return f"{int(value)}K"
        return f"{value:.1f}K"
    if n < 999500000:  # Threshold to avoid "1000.0M"
        # Format as X.XM
        value = n / 1000000
        if value == int(value):
            return f"{int(value)}M"
        return f"{value:.1f}M"
    # Format as X.XB
    value = n / 1000000000
    if value == int(value):
        return f"{int(value)}B"
    return f"{value:.1f}B"


# =============================================================================
# Metric Calculators
# =============================================================================

def calculate_volume_score(words_processed: int) -> float:
    """
    Calculate volume score based on words processed (logarithmic scale).

    Args:
        words_processed: Total words processed

    Returns:
        Score between 0-100
    """
    if words_processed <= 0:
        return 0.0

    # Use tier-based scoring with interpolation
    tiers = MetricConstants.VOLUME_TIERS

    # Find the appropriate tier
    for i, (threshold, score) in enumerate(tiers):
        if words_processed < threshold:
            if i == 0:
                return 0.0
            # Interpolate between previous tier and current
            prev_threshold, prev_score = tiers[i - 1]
            if threshold == prev_threshold:
                return float(score)
            # Linear interpolation
            ratio = (words_processed - prev_threshold) / (threshold - prev_threshold)
            return prev_score + ratio * (score - prev_score)

    # Above highest tier
    return 100.0


def calculate_diversity_score(sources: list[SourceMetrics]) -> tuple[float, int]:
    """
    Calculate source diversity score based on source types.

    Args:
        sources: List of source metrics

    Returns:
        Tuple of (score 0-100, unique_type_count)
    """
    if not sources:
        return 0.0, 0

    # Get unique source types
    source_types = set(s.source_type.lower() for s in sources if s.has_content)
    unique_count = len(source_types)

    if unique_count == 0:
        return 0.0, 0

    # Score based on diversity
    # 1 type = 20, 2 types = 40, 3 types = 60, 4 types = 80, 5+ types = 100
    diversity_scores = {1: 20, 2: 40, 3: 60, 4: 80, 5: 100}
    score = diversity_scores.get(min(unique_count, 5), 100)

    return float(score), unique_count


def calculate_quality_score(sources: list[SourceMetrics]) -> tuple[float, float]:
    """
    Calculate extraction quality score based on success rate.

    Args:
        sources: List of source metrics

    Returns:
        Tuple of (score 0-100, success_rate 0-1)
    """
    if not sources:
        return 0.0, 0.0

    total = len(sources)
    successful = sum(1 for s in sources if s.has_content and s.word_count > 0)
    _ = sum(1 for s in sources if s.status in ("error", "failed"))

    if total == 0:
        return 0.0, 0.0

    success_rate = successful / total

    # Score based on success rate
    # 100% success = 100, 90% = 90, etc.
    # Penalize failures more heavily
    if success_rate >= 0.95:
        score = 100.0
    elif success_rate >= 0.8:
        score = 90.0
    elif success_rate >= 0.6:
        score = 70.0
    elif success_rate >= 0.4:
        score = 50.0
    else:
        score = max(0.0, success_rate * 100)

    return score, success_rate


def calculate_freshness_score(sources: list[SourceMetrics]) -> float:
    """
    Calculate freshness score based on recency of sources.

    Args:
        sources: List of source metrics

    Returns:
        Score between 0-100
    """
    if not sources:
        return 0.0

    # Count sources with extraction timestamp
    recent_sources = sum(1 for s in sources if s.extracted_at is not None)

    if recent_sources == 0:
        return 50.0  # Neutral if no timestamp data

    # For now, give full score if we have timestamp data
    # TODO: V2 - Check actual recency (within 30 days = full score, etc.)
    return 100.0


def calculate_structure_score(sources: list[SourceMetrics]) -> float:
    """
    Calculate structured signal score.

    Args:
        sources: List of source metrics

    Returns:
        Score between 0-100
    """
    if not sources:
        return 0.0

    # For V1, base this on having content with reasonable word counts
    # Sources with >500 words likely have structure
    structured_count = sum(1 for s in sources if s.word_count >= 500)
    total_count = len(sources)

    if total_count == 0:
        return 0.0

    # Score based on percentage of structured sources
    ratio = structured_count / total_count
    return min(100.0, ratio * 120)  # Slight bonus for high structure


def calculate_verification_score(twin_id: str) -> float:
    """
    Calculate verification/owner-approved signal score.

    Args:
        twin_id: Twin ID to check

    Returns:
        Score between 0-100
    """
    try:
        # Check for verified QnA entries
        result = supabase.table("verified_qna").select("id", count="exact").eq("twin_id", twin_id).execute()
        verified_count = result.count or 0

        # Score based on verified content
        # 0 = 0, 1-5 = 50, 6-10 = 75, 11+ = 100
        if verified_count == 0:
            return 0.0
        if verified_count <= 5:
            return 50.0
        if verified_count <= 10:
            return 75.0
        return 100.0
    except Exception:
        # Default to neutral if query fails
        return 50.0


def estimate_questions_answerable(
    words_processed: int,
    sources: list[SourceMetrics],
    quality_factor: float,
    diversity_factor: float
) -> int:
    """
    Estimate number of questions the twin can answer.

    V1 Heuristic Formula:
        base_estimate = words_processed / WORDS_PER_QUESTION_BASELINE
        adjusted = base_estimate * quality_factor * diversity_factor * COMPRESSION_FACTOR

    Args:
        words_processed: Total words processed
        sources: List of source metrics
        quality_factor: Quality multiplier (0-1)
        diversity_factor: Diversity multiplier (1+)

    Returns:
        Estimated number of questions (integer, >= 0)
    """
    if words_processed <= 0:
        return 0

    # Base estimate: words / baseline
    base_estimate = words_processed / MetricConstants.WORDS_PER_QUESTION_BASELINE

    # Apply quality factor (failed extractions reduce capacity)
    quality_adjusted = base_estimate * quality_factor

    # Apply diversity factor (diverse sources increase coverage)
    diversity_adjusted = quality_adjusted * (1 + (diversity_factor - 1) * 0.3)

    # Apply compression factor to prevent over-inflation
    final_estimate = diversity_adjusted * MetricConstants.COMPRESSION_FACTOR

    # Round and ensure non-negative
    return max(0, round(final_estimate))


def calculate_mind_score(
    volume_score: float,
    diversity_score: float,
    quality_score: float,
    freshness_score: float,
    structure_score: float,
    verification_score: float
) -> int:
    """
    Calculate overall Mind Score (0-100).

    Weighted formula:
        25% volume + 20% diversity + 20% quality +
        10% freshness + 15% structure + 10% verification

    Args:
        volume_score: Volume component score
        diversity_score: Diversity component score
        quality_score: Quality component score
        freshness_score: Freshness component score
        structure_score: Structure component score
        verification_score: Verification component score

    Returns:
        Mind score (0-100, integer)
    """
    weighted_score = (
        MetricConstants.VOLUME_WEIGHT * volume_score +
        MetricConstants.DIVERSITY_WEIGHT * diversity_score +
        MetricConstants.QUALITY_WEIGHT * quality_score +
        MetricConstants.FRESHNESS_WEIGHT * freshness_score +
        MetricConstants.STRUCTURE_WEIGHT * structure_score +
        MetricConstants.VERIFICATION_WEIGHT * verification_score
    )

    # Clamp to 0-100 and round
    return max(0, min(100, round(weighted_score)))


def get_mind_score_label(score: int) -> str:
    """
    Get label for mind score.

    Args:
        score: Mind score (0-100)

    Returns:
        Label string
    """
    for min_score, max_score, label in MetricConstants.SCORE_LABELS:
        if min_score <= score < max_score:
            return label
    return "Expert"


# =============================================================================
# Main Metric Computation
# =============================================================================

def compute_training_metrics(twin_id: str, force_recompute: bool = False) -> TrainingMetrics:
    """
    Compute training metrics for a twin.

    Args:
        twin_id: Twin ID to compute metrics for
        force_recompute: If True, ignore cached values

    Returns:
        TrainingMetrics object with computed values

    Note:
        This is the main entry point for metric computation.
        It aggregates data from all sources and applies the V1 heuristic formulas.
    """
    metrics = TrainingMetrics()

    try:
        # Fetch all sources for this twin.
        #
        # IMPORTANT: production `sources` is the simplified schema
        # ``(id, twin_id, filename, file_url, content_text)``. The legacy
        # columns (``status``, ``citation_url``, ``extracted_text_length``,
        # ``created_at``) referenced earlier raised
        # ``42703 column sources.<x> does not exist`` for every post-launch
        # twin, the bare ``except`` swallowed it, and the function returned
        # ``mind_score=0, _source_count=0`` with the cryptic
        # ``"Error computing metrics: 23"`` note. See PR #27 for the same
        # bug class on ``twins.user_id`` / ``settings.owner_user_id``.
        #
        # We select ``*`` so the function still works on legacy projects
        # that retain the extra columns (and gives them their richer
        # signal), while not exploding on production.
        result = supabase.table("sources").select("*").eq("twin_id", twin_id).execute()

        sources_data = result.data or []

        if not sources_data:
            # No sources - return default (empty) metrics
            return metrics

        # Process each source
        source_metrics: list[SourceMetrics] = []
        total_words = 0
        failed_count = 0

        for source in sources_data:
            source_id = source.get("id", "unknown")
            status = source.get("status", "live")  # Production schema has no status; treat row presence as live
            content_text = source.get("content_text", "")
            # Prefer the optional citation_url, fall back to file_url which
            # production stores for both web extracts and uploads.
            citation_url = source.get("citation_url") or source.get("file_url") or ""
            filename = source.get("filename") or ""
            created_at = source.get("created_at")

            # Detect source type from URL or default to file
            source_type = "file"
            if citation_url:
                url_lower = citation_url.lower()
                if "youtube" in url_lower or "youtu.be" in url_lower:
                    source_type = "youtube"
                elif "twitter" in url_lower or "x.com" in url_lower:
                    source_type = "x"
                elif "linkedin" in url_lower:
                    source_type = "linkedin"
                elif "instagram" in url_lower:
                    source_type = "instagram"
                elif "facebook" in url_lower or "fb.com" in url_lower:
                    source_type = "facebook"
                elif ".rss" in url_lower or "podcast" in url_lower:
                    source_type = "podcast"
                elif url_lower.startswith("http"):
                    source_type = "web"
            elif filename:
                # Uploaded file with no URL — keep it as "file"
                source_type = "file"

            # Count words from content_text
            word_count = count_words(content_text)
            # Only count sources that are fully processed and live.
            # NOTE: "staged" is intentionally excluded - sources must be
            # live/processed to count. On the simplified production schema
            # there is no status column, so a row with non-empty
            # content_text is by definition processed (status defaults to
            # "live" above).
            has_content = word_count > 0 and status in ("live", "processed", "active")

            if status in ("error", "failed"):
                failed_count += 1

            sm = SourceMetrics(
                source_id=source_id,
                source_type=source_type,
                status=status,
                word_count=word_count,
                extracted_at=created_at,
                has_content=has_content
            )
            source_metrics.append(sm)

            # Only count words from successful sources
            if has_content:
                total_words += word_count

        # Calculate component scores
        volume_score = calculate_volume_score(total_words)
        diversity_score, unique_types = calculate_diversity_score(source_metrics)
        quality_score, success_rate = calculate_quality_score(source_metrics)
        freshness_score = calculate_freshness_score(source_metrics)
        structure_score = calculate_structure_score(source_metrics)
        verification_score = calculate_verification_score(twin_id)

        # Calculate mind score
        mind_score = calculate_mind_score(
            volume_score=volume_score,
            diversity_score=diversity_score,
            quality_score=quality_score,
            freshness_score=freshness_score,
            structure_score=structure_score,
            verification_score=verification_score
        )

        # Estimate questions answerable
        questions_est = estimate_questions_answerable(
            words_processed=total_words,
            sources=source_metrics,
            quality_factor=success_rate,
            diversity_factor=1 + (unique_types - 1) * 0.2 if unique_types > 0 else 1
        )

        # Populate metrics
        metrics.words_processed = total_words
        metrics.words_processed_display = format_number_compact(total_words)
        metrics.questions_answerable_est = questions_est
        metrics.questions_answerable_display = format_number_compact(questions_est)
        metrics.mind_score = mind_score
        metrics.mind_score_label = get_mind_score_label(mind_score)
        metrics.source_count = len(source_metrics)
        metrics.failed_source_count = failed_count
        metrics.source_type_diversity = unique_types

        # Store component scores for debugging
        metrics.component_scores = {
            "volume_score": volume_score,
            "diversity_score": diversity_score,
            "quality_score": quality_score,
            "freshness_score": freshness_score,
            "structure_score": structure_score,
            "verification_score": verification_score,
            "success_rate": success_rate,
        }

    except Exception as e:
        # Log error but return default metrics (don't crash)
        logger.warning("[TrainingMetrics] Error computing metrics for twin %s: %s", twin_id, e)
        # Return default metrics with error note
        metrics.notes = f"Error computing metrics: {str(e)}"

    return metrics


def get_training_metrics_for_api(twin_id: str) -> dict[str, Any]:
    """
    Get training metrics formatted for API response.

    Args:
        twin_id: Twin ID to get metrics for

    Returns:
        Dictionary formatted for API response
    """
    metrics = compute_training_metrics(twin_id)

    return {
        "training_metrics": {
            "words_processed": metrics.words_processed,
            "words_processed_display": metrics.words_processed_display,
            "questions_answerable_est": metrics.questions_answerable_est,
            "questions_answerable_display": metrics.questions_answerable_display,
            "mind_score": metrics.mind_score,
            "mind_score_label": metrics.mind_score_label,
            "method_version": metrics.method_version,
            "last_computed_at": metrics.last_computed_at,
            "notes": metrics.notes,
        }
    }


def update_twin_training_metrics(twin_id: str) -> bool:
    """
    Compute and store training metrics in twin's settings.

    Args:
        twin_id: Twin ID to update

    Returns:
        True if successful, False otherwise

    Note:
        Stores metrics in twin.settings.training_metrics for persistence.
        This allows fast reads without recomputing on every request.
    """
    try:
        metrics = compute_training_metrics(twin_id)

        # Get current settings
        result = supabase.table("twins").select("settings").eq("id", twin_id).single().execute()
        if not result.data:
            logger.warning("[TrainingMetrics] Twin %s not found", twin_id)
            return False

        current_settings = result.data.get("settings") or {}

        # Update settings with metrics
        updated_settings = {
            **current_settings,
            "training_metrics": {
                "words_processed": metrics.words_processed,
                "words_processed_display": metrics.words_processed_display,
                "questions_answerable_est": metrics.questions_answerable_est,
                "questions_answerable_display": metrics.questions_answerable_display,
                "mind_score": metrics.mind_score,
                "mind_score_label": metrics.mind_score_label,
                "method_version": metrics.method_version,
                "last_computed_at": metrics.last_computed_at,
                "notes": metrics.notes,
                # Internal fields for debugging
                "_component_scores": metrics.component_scores,
                "_source_count": metrics.source_count,
                "_failed_count": metrics.failed_source_count,
            }
        }

        # Update twin
        supabase.table("twins").update({
            "settings": updated_settings
        }).eq("id", twin_id).execute()

        logger.info(
            "[TrainingMetrics] Updated metrics for twin %s: words=%s, questions=%s, score=%s",
            twin_id, metrics.words_processed, metrics.questions_answerable_est, metrics.mind_score,
        )

        return True

    except Exception as e:
        logger.error("[TrainingMetrics] Error updating metrics for twin %s: %s", twin_id, e)
        return False


# =============================================================================
# Feature Flag Check
# =============================================================================

def is_training_metrics_enabled() -> bool:
    """
    Check if training metrics feature is enabled.

    Returns:
        True if enabled, False otherwise
    """
    import os
    return os.getenv("PROFILE_TRAINING_METRICS_ENABLED", "true").lower() == "true"
