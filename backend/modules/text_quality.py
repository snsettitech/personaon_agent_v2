"""Shared meaningfulness validation for user-authored profile text.

Root cause (PRD R1, execution-board 0.2): a live persona page shipped with
headline "software engineer" and bio literally "nill" — zero other content —
because nothing on the write path ever checked whether bio/headline text was
*meaningful*. Only HTML/prompt-injection sanitization existed (see
`routers.auto_create._sanitize_context`), which happily lets "nill" through
since it contains no HTML tags or injection phrases.

This module is the single source of truth for that check. Reused by:
  - `routers.onboarding.CreatePersonaRequest` (short_intro / headline)
  - `routers.profile.UpdateProfileRequest` (bio / headline)
  - `routers.twins.patch_twin` (raw settings.public_profile / persona_profile
    bio + headline — the dashboard profile-edit save path)
  - the publish gate (execution-board 0.1) — reuse `is_meaningful_text` /
    `validate_meaningful_text` there. Do not re-implement this logic.

Mirrored on the client in `frontend/lib/validation/textQuality.ts` — keep the
two in sync (same thresholds, same messages) since both must reject the same
four cases: too short ("nill"), single word ("a"), all-whitespace, and
repeated-character/low-entropy filler ("asdf asdf asdf").
"""

from __future__ import annotations

import re
import unicodedata

# Bio-style free text ("at least a sentence") — the PRD's explicit bar.
BIO_MIN_LENGTH = 40

# Headlines are legitimately short and often a single word ("CEO", "Founder"),
# so they don't get the bio's 40-char/2-word bar. This floor only exists to
# block near-nothing input ("a", "ai") while still allowing real short titles.
HEADLINE_MIN_LENGTH = 3

_EMPTY_ERROR = "Tell us a bit more — at least a sentence."
_TOO_SHORT_ERROR = "Tell us a bit more — at least a sentence ({min_length}+ characters)."
_SINGLE_WORD_ERROR = "Tell us a bit more — at least a sentence, not a single word."
_LOW_ENTROPY_ERROR = "That doesn't look like real content — please write a genuine sentence about yourself."

# Matches a string entirely made of 2+ back-to-back copies of the same
# 1-20 char chunk, e.g. "aaaa" (chunk "a"), "asdfasdfasdf" (chunk "asdf"),
# "abab" (chunk "ab"). Applied after whitespace is stripped so
# "asdf asdf asdf" is caught the same way as "asdfasdfasdf".
_REPEATING_PATTERN_RE = re.compile(r"^(.{1,20}?)\1+$")

# Matches a 2-20 char chunk repeated 3+ times *anywhere* in the string, not
# just anchored at the start like _REPEATING_PATTERN_RE — catches keyboard
# mash such as "asdkfj" + "qwoeiru" x4, where a real-looking prefix defeats
# the start-anchored check but the string is still mostly filler.
_LONG_REPEAT_RE = re.compile(r"(.{2,20}?)\1{2,}")


def _strip_invisible_chars(text: str) -> str:
    """Strip Unicode "format" category (Cf) characters: zero-width
    space/joiner/non-joiner, BOM, directional marks, etc.

    These render invisibly but count toward length, and `str.split()` word
    boundaries are unaffected by them — so text padded with them (e.g.
    "Hi there" + U+200B*40) would otherwise clear the meaningfulness
    length/word floor while rendering as near-empty content.
    """
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def _collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _is_low_entropy(candidate: str, words: list[str]) -> bool:
    """True if `candidate` reads like keyboard-mash/filler rather than real content.

    Four independent signals (any one triggers a reject):
      1. the whole string (ignoring whitespace) is a short chunk repeated
         end-to-end — catches "aaaa", "abab", "asdfasdfasdf"
      2. the same word is repeated across 3+ words with almost no variety —
         catches "asdf asdf asdf", "lol lol lol lol"
      3. the string is long but drawn from a tiny alphabet — catches
         "aaaaaaaaaa bbbbbbbbbb" style filler that doesn't match signal 1
         because it isn't a single repeating chunk
      4. a large majority of a single long "word" is a short chunk repeated
         3+ times *somewhere* inside it (not required to start at position
         0) — catches single-word keyboard mash like "asdkfj" + "qwoeiru"*4,
         which defeats signal 1 (real-looking prefix breaks the start
         anchor) and signal 3 (alphabet is diverse enough to clear the
         <=3-distinct-chars bar)
    """
    collapsed = _collapse_whitespace(candidate).lower()
    if not collapsed:
        return True

    if _REPEATING_PATTERN_RE.match(collapsed):
        return True

    lowered_words = [w.lower() for w in words]
    if len(lowered_words) >= 3 and len(set(lowered_words)) <= 2:
        return True

    if len(collapsed) >= 12 and len(set(collapsed)) <= 3:
        return True

    repeat_match = _LONG_REPEAT_RE.search(collapsed)
    if repeat_match is None:
        return False
    return len(repeat_match.group(0)) >= max(12, len(collapsed) * 0.6)


def meaningful_text_error(
    text: str | None,
    *,
    min_length: int = BIO_MIN_LENGTH,
    min_words: int = 2,
) -> str | None:
    """Return a user-facing, inline-message-worthy error if `text` fails the
    meaningfulness bar, else None.

    Checks (all must pass):
      - non-empty after stripping whitespace
      - at least `min_length` characters
      - at least `min_words` distinct words (set `min_words=1` to allow
        legitimate single-word input, e.g. a headline like "CEO")
      - not low-entropy / repetitive (see `_is_low_entropy`)
    """
    candidate = _strip_invisible_chars(text or "").strip()
    if not candidate:
        return _EMPTY_ERROR

    if len(candidate) < min_length:
        return _TOO_SHORT_ERROR.format(min_length=min_length)

    words = candidate.split()
    if min_words > 1 and len(words) < min_words:
        return _SINGLE_WORD_ERROR

    if _is_low_entropy(candidate, words):
        return _LOW_ENTROPY_ERROR

    return None


def is_meaningful_text(
    text: str | None,
    *,
    min_length: int = BIO_MIN_LENGTH,
    min_words: int = 2,
) -> bool:
    """True iff `text` passes the meaningfulness bar. See `meaningful_text_error`."""
    return meaningful_text_error(text, min_length=min_length, min_words=min_words) is None


def validate_meaningful_text(
    text: str | None,
    *,
    min_length: int = BIO_MIN_LENGTH,
    min_words: int = 2,
) -> str:
    """Return the stripped text if meaningful, else raise ValueError with an
    inline-message-worthy reason. Intended for use inside Pydantic
    `field_validator`s (Pydantic wraps the ValueError into a 422 response).
    """
    error = meaningful_text_error(text, min_length=min_length, min_words=min_words)
    if error:
        raise ValueError(error)
    return (text or "").strip()


def validate_headline_text(text: str | None) -> str:
    """Headline-specific wrapper: same low-entropy/whitespace checks as bio,
    but a much lower length floor and single-word input allowed (real
    headlines are often one word — "CEO", "Founder").
    """
    return validate_meaningful_text(text, min_length=HEADLINE_MIN_LENGTH, min_words=1)
