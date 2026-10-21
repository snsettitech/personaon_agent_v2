"""Deprecated shim — use `adk_core.services.persona_core.recap` instead.

Kept for one release while callers migrate. All callers that import from
`services.meeting_analyzer` continue to work via these re-exports.
"""
from __future__ import annotations

from adk_core.services.persona_core.recap import (  # noqa: F401
    # Public API
    analyze_meeting,
    compute_speaker_analytics,
    # Module-level constants
    SUMMARY_SCHEMA,
    SENTIMENT_SCHEMA,
    SUMMARY_PROMPT_TEMPLATE,
    REDUCE_PROMPT_TEMPLATE,
    # Private helpers used by other modules / tests
    _analyze_speaker_sentiment,
    _estimate_duration_from_transcript,
    _get_genai_client,
    _reduce_summaries,
    _split_transcript_into_segments,
    _strip_markdown_fences,
    _summarize_segments,
    _summarize_text,
)
