"""Shared text processing utilities for the ADK runtime.

Single source of truth for stopwords, tokenization, and text normalization.
Used by persona_materializer, enrichment_tools, and retrieval_tools.
"""

from __future__ import annotations

import re
from collections import Counter

STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "he", "her", "his", "in", "is", "it", "of", "on", "or", "she",
    "that", "the", "their", "they", "to", "was", "were", "with",
})


def normalize_text(text: str) -> str:
    """Collapse whitespace to single spaces."""
    return re.sub(r"\s+", " ", str(text or "").strip())


def tokenize(text: str, *, filter_stopwords: bool = True) -> list[str]:
    """Extract meaningful word tokens from text."""
    tokens = re.findall(r"[a-zA-Z][a-zA-Z'-]{2,}", str(text or "").lower())
    if filter_stopwords:
        return [t for t in tokens if t not in STOPWORDS]
    return tokens


def token_set(text: str) -> set[str]:
    """Return a set of meaningful tokens for overlap scoring."""
    return set(tokenize(text))


def top_terms(texts: list[str], limit: int = 8) -> list[str]:
    """Extract the most common meaningful terms from a list of texts."""
    counts: Counter[str] = Counter()
    for text in texts:
        for token in tokenize(text):
            counts[token] += 1
    return [term for term, _ in counts.most_common(limit)]


def signature_phrases(quotes: list[str], limit: int = 6) -> list[str]:
    """Extract distinctive short phrases from quotes."""
    phrases: list[str] = []
    for quote in quotes:
        cleaned = normalize_text(quote)
        if not cleaned or len(cleaned) < 15:
            continue
        # Take first ~80 chars as signature phrase
        phrase = cleaned[:80].rsplit(" ", 1)[0] if len(cleaned) > 80 else cleaned
        phrases.append(phrase)
        if len(phrases) >= limit:
            break
    return phrases


def slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    slug = re.sub(r"[^a-z0-9\s-]", "", text.lower().strip())
    slug = re.sub(r"[\s_]+", "-", slug)
    return re.sub(r"-+", "-", slug).strip("-")[:80]


def clamp_int(value: float, lo: int = 0, hi: int = 100) -> int:
    """Clamp a float to an integer range."""
    return max(lo, min(hi, int(round(value))))
