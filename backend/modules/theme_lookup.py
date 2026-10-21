"""Keyword-based default theme selection for newly created twins.

Execution-board 0.3: a non-customizing signup must never silently land on
Classic — the weakest, least-branded shell (and, until Phase 4's fix, the
only shell that also ignores the owner's accent choice). This module maps
common headline/role keywords to one of the other 5 layout shells at
twin-creation time, wired in from `routers/auto_create.py`.

Keep the theme ids in sync with:
  - backend/modules/public_profile_pack.py ALLOWED_THEME_IDS
  - frontend/lib/persona-themes/types.ts THEME_IDS
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Fallback when no keyword matches. Per the PRD (plans/personaon-prd.md, R2),
# "Site" is the most sophisticated shell and the designated non-Classic
# candidate default — this must never be "classic".
DEFAULT_FALLBACK_THEME_ID = "site"

# Ordered keyword -> theme_id groups. Group order is now only a tie-breaker
# (see _select_theme_id): the keyword whose match starts EARLIEST in the
# haystack wins, since the first-mentioned role in a headline is normally the
# person's primary identity (e.g. "Freelance photographer and part-time
# consultant" -> split, not conversion-warm, because "photographer" appears
# first). Group order only matters when two matches start at the same
# position, which cannot happen for distinct keywords.
KEYWORD_THEME_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    # Business/leadership roles -> founder-site
    (
        "founder-site",
        (
            "founder",
            "co-founder",
            "cofounder",
            "ceo",
            "chief executive",
            "president",
            "entrepreneur",
            "managing director",
        ),
    ),
    # Sales/marketing/advisory roles -> conversion-warm (persuasive, warm tone)
    (
        "conversion-warm",
        (
            "consultant",
            "consulting",
            "marketing",
            "marketer",
            "sales",
            "advisor",
            "coach",
            "strategist",
        ),
    ),
    # Writing/media/thought-leadership roles -> editorial
    (
        "editorial",
        (
            "writer",
            "journalist",
            "editor",
            "author",
            "content creator",
            "blogger",
            "columnist",
            "publisher",
        ),
    ),
    # Creative/visual roles -> split (visual split-screen layout)
    (
        "split",
        (
            "designer",
            "photographer",
            "artist",
            "creative director",
            "art director",
            "illustrator",
            "videographer",
        ),
    ),
    # Technical/engineering roles -> site (most sophisticated shell)
    (
        "site",
        (
            "engineer",
            "developer",
            "programmer",
            "software",
            "devops",
            "architect",
            "data scientist",
            "sre",
            "cto",
        ),
    ),
)


# Markers that mean the role mentioned near them is no longer the person's
# current identity (e.g. "former CEO", "ex-consultant"). A keyword match
# immediately preceded by one of these is demoted below any non-demoted
# match, rather than winning purely because it happens to appear first.
# Word-boundary patterns (not plain substrings) so e.g. "Rolex-obsessed" or
# "steadfast contributor" can't accidentally match "ex"/"past" mid-word.
# \b already treats "-" and " " as non-word boundaries, so a single "ex"
# token correctly matches both "ex-consultant" and "ex consultant".
_FORMER_ROLE_MARKER_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(r"\b" + re.escape(marker) + r"\b")
    for marker in ("former", "ex", "past", "retired")
)
_FORMER_MARKER_LOOKBACK = 12  # chars of context checked before a keyword match

# "<former role> turned <current role>" is a common headline pattern
# ("CEO turned software developer"). Everything before "turned" describes a
# past identity, so keyword matches before it are demoted the same way as an
# explicit former-role marker.
_TURNED_PATTERN = re.compile(r"\bturned\b")


def _contains_keyword(haystack: str, keyword: str) -> bool:
    """Whole-word/phrase match — avoids false positives like "design" inside
    "designated". Keywords may be multi-word phrases (e.g. "chief executive")."""
    pattern = r"\b" + re.escape(keyword) + r"\b"
    return re.search(pattern, haystack) is not None


def _find_keyword_matches(
    haystack: str,
) -> list[tuple[int, int, str]]:
    """Return (start_position, group_index, theme_id) for every keyword
    occurrence in `haystack`, across all KEYWORD_THEME_GROUPS."""
    matches: list[tuple[int, int, str]] = []
    for group_index, (theme_id, keywords) in enumerate(KEYWORD_THEME_GROUPS):
        for keyword in keywords:
            pattern = r"\b" + re.escape(keyword) + r"\b"
            found = re.search(pattern, haystack)
            if found:
                matches.append((found.start(), group_index, theme_id))
    return matches


def _is_demoted(start: int, haystack: str, turned_pos: int | None) -> bool:
    """A match is demoted when it sits before a "turned" transition (an
    earlier, no-longer-current role) or is immediately preceded by an
    explicit former-role marker like "former"/"ex-"."""
    if turned_pos is not None and start < turned_pos:
        return True
    lookback_start = max(0, start - _FORMER_MARKER_LOOKBACK)
    prefix = haystack[lookback_start:start]
    return any(pattern.search(prefix) for pattern in _FORMER_ROLE_MARKER_PATTERNS)


def _select_theme_id(haystack: str) -> str | None:
    """Pick the theme_id for the headline's primary occupation.

    Unlike a fixed group-priority scan, this looks at WHERE each keyword
    occurs: the earliest-mentioned, still-current role wins. Matches that
    are clearly a past role (per a "turned" transition or a "former"/"ex-"
    marker) are demoted and only used if nothing else matched at all.
    """
    matches = _find_keyword_matches(haystack)
    if not matches:
        return None

    turned = _TURNED_PATTERN.search(haystack)
    turned_pos = turned.start() if turned else None

    current_matches = [
        m for m in matches if not _is_demoted(m[0], haystack, turned_pos)
    ]
    pool = current_matches or matches
    # Earliest position wins; group order is only a tie-breaker (ties can't
    # happen for distinct keyword spans, but keep it deterministic).
    _start, _group_index, theme_id = min(pool, key=lambda m: (m[0], m[1]))
    return theme_id


def infer_default_theme_id(headline: str | None, context: str | None = None) -> str:
    """Map a persona's headline/role text to a default theme_id.

    Runs at twin-creation time so a non-customizing signup never silently
    lands on Classic. Considers both a verified headline (e.g. LinkedIn) and
    free-text onboarding context. Returns one of the 5 non-Classic layout
    shells; falls back to DEFAULT_FALLBACK_THEME_ID ("site") when nothing
    matches or no text is available.
    """
    haystack = " ".join(part for part in (headline, context) if part).strip().lower()
    if not haystack:
        return DEFAULT_FALLBACK_THEME_ID

    theme_id = _select_theme_id(haystack)
    if theme_id is not None:
        logger.info(
            "[ThemeLookup] matched theme_id=%s for headline=%r context=%r",
            theme_id,
            headline,
            context,
        )
        return theme_id

    logger.info(
        "[ThemeLookup] no keyword match, falling back to theme_id=%s for headline=%r context=%r",
        DEFAULT_FALLBACK_THEME_ID,
        headline,
        context,
    )
    return DEFAULT_FALLBACK_THEME_ID
