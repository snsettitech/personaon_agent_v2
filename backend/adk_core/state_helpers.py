"""Shared state helpers for the ADK runtime."""

from __future__ import annotations

import json
from typing import Any


def json_list(raw: Any) -> list[str]:
    """Parse a JSON list from state, tolerating strings and None."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(item) for item in raw if item]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(item) for item in parsed if item]
        except Exception:
            return [raw]
    return []


def merge_citations(*groups: list[str]) -> list[str]:
    """Deduplicate and merge citation lists preserving order."""
    merged: list[str] = []
    seen: set = set()
    for group in groups:
        for item in group:
            if item and item not in seen:
                seen.add(item)
                merged.append(item)
    return merged
