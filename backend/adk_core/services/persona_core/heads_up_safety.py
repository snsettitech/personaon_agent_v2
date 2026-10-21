"""W9b — Anti-pattern post-filter for Heads Up notes.

Defense-in-depth: even if the LLM emits forbidden language (despite the
system prompt forbidding it), this layer catches the match and drops the
note. Cheaper than re-prompting and bounds the worst-case shipped output.

Patterns are case-insensitive substring matches. False positives are
possible (rare) — every drop is logged with the pattern that matched so we
can tune the blocklist over time.

Source of truth: this list mirrors the anti_pattern_blocklist in
backend/tests/fixtures/heads_up_eval_set.yaml and the spec doc at
docs/superpowers/plans/2026-05-21-w9-heads-up-eval-set.md.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

logger = logging.getLogger(__name__)


def _hash_for_log(text: str) -> str:
    """Short stable hash of note text for log correlation.

    AUDIT FIX (HIGH security): when a note is dropped for an anti-pattern
    match, we previously logged the dropped text (up to 200 chars) at
    WARNING level. Cloud Logging scrapes WARNING by default; private KB
    content (which can flow through into rewritten notes) would land in
    logs accessible to anyone with Cloud Logging Viewer.

    The hash is enough to correlate a drop with a specific brief
    response or replay test during incident triage, without exposing
    content. 12 hex chars (~6 bytes of entropy) — collision-resistant
    for log-correlation purposes.
    """
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


ANTI_PATTERNS: list[str] = [
    # Imperative verbs (telling the user what to do)
    "you should",
    "don't forget to",
    "make sure to",
    "be sure to",
    # Failure verbs (accusing the user)
    "you forgot",
    "you missed",
    "you skipped",
    "you owe",
    "you failed",
    "you neglected",
    "you committed to",
    # Mind-reading the other party
    "they may be frustrated",
    "he might be annoyed",
    "she's likely upset",
    "they probably feel",
    "their morale may be",
    # Loaded judgment words
    "overdue",
    "deadline missed",
    "stalemate",
    "dropped the ball",
    "behind on",
]


def note_violates_anti_pattern(text: str) -> str | None:
    """Return the matched anti-pattern string, or None when the note is clean.

    Match is case-insensitive substring. Returns the FIRST match found so
    we can log a single specific reason (not "5 patterns matched").
    """
    lower = (text or "").lower()
    for pattern in ANTI_PATTERNS:
        if pattern in lower:
            return pattern
    return None


def filter_safe_notes(
    notes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split notes into (safe, dropped).

    Each dropped note gets a ``_dropped_reason`` key with the matched
    anti-pattern, useful for log enrichment and future tuning.

    Notes without a ``text`` field are treated as malformed and dropped
    (to avoid downstream crashes), with reason ``"missing_text"``.
    """
    safe: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for note in notes or []:
        text = note.get("text")
        if not text or not isinstance(text, str):
            logger.warning(
                "[HeadsUp] dropped malformed note (missing text): keys=%s",
                list(note.keys()),
            )
            dropped.append({**note, "_dropped_reason": "missing_text"})
            continue
        matched = note_violates_anti_pattern(text)
        if matched is None:
            safe.append(note)
        else:
            # Log the matched pattern + a short hash of the note (NOT the
            # note text). KB-private content can flow through Heads Up
            # notes, and WARNING-level logs are scraped to Cloud Logging
            # by default — exposing private content there is a leakage
            # surface. The hash is enough to correlate a drop with a
            # specific brief or replay test during triage.
            logger.warning(
                "[HeadsUp] dropped note with anti-pattern=%r text_hash=%s",
                matched, _hash_for_log(text),
            )
            dropped.append({**note, "_dropped_reason": matched})
    return safe, dropped
