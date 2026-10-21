"""Shared name-variant matching utility.

Used by:
  - meeting_people_extractor (owner exclusion)
  - contact_analysis endpoint (assignee role resolution)

Handles three cases:
  - Exact lowercase match
  - Multi-token overlap ("Sainath" vs "Sainath Setti")
  - Nickname/prefix: short candidate (<=4 chars) prefix of any reference token
    ("Sai" vs "Sainath")
"""
from __future__ import annotations

import re

_TOKEN_SPLIT = re.compile(r"[\s\-]+")


def _tokenize(name: str) -> set[str]:
    return {
        t.strip(".,;'\"")
        for t in _TOKEN_SPLIT.split(name.strip().lower())
        if t.strip()
    }


def is_name_variant(candidate: str | None, reference: str | None) -> bool:
    """True if candidate and reference are likely the same person.

    Returns False if either side is empty or only whitespace.

    Handles:
      - Exact lowercase match
      - Multi-token: any token overlap ('Sainath' vs 'Sainath Setti')
      - Nickname/prefix: short candidate (<=4 chars) prefix of a reference token
        ('Sai' vs 'Sainath')
      - Reverse nickname: short reference prefix of a candidate token
    """
    if not candidate or not reference:
        return False
    cand_lc = candidate.strip().lower()
    ref_lc = reference.strip().lower()
    if not cand_lc or not ref_lc:
        return False
    if cand_lc == ref_lc:
        return True
    cand_tokens = _tokenize(candidate)
    ref_tokens = _tokenize(reference)
    if cand_tokens & ref_tokens:
        return True
    # Nickname catch — short candidate prefix of a reference token
    if len(cand_lc) <= 4:
        for tok in ref_tokens:
            if tok.startswith(cand_lc) and tok != cand_lc:
                return True
    # Reverse: short reference (e.g. "Sai" owner) prefix of candidate token
    if len(ref_lc) <= 4:
        for tok in cand_tokens:
            if tok.startswith(ref_lc) and tok != ref_lc:
                return True
    return False
