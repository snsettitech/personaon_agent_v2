"""Shared recap sanitization helpers.

Used by public_recap.py (public endpoint) and the owner preview endpoint
(twins_preview.py) to produce the same sanitized payload shape.
"""
from __future__ import annotations
from typing import Any

PUBLIC_ACTION_KEYS = ("text", "assignee", "context", "due_at", "completed")
PUBLIC_SUMMARY_KEYS = ("tldr", "topics", "key_questions")
PUBLIC_EXTRAS_KEYS = ("intent", "what_happened", "commitments")


def pick(value: Any, keys: tuple[str, ...]) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    return {k: value.get(k) for k in keys if k in value}


def sanitize_action_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    return [
        pick(it, PUBLIC_ACTION_KEYS) or {}
        for it in items
        if isinstance(it, dict)
    ]


def sanitize_meeting(meeting: dict[str, Any]) -> dict[str, Any]:
    summary = pick(meeting.get("summary_json"), PUBLIC_SUMMARY_KEYS)
    # Recap extras column is recap_extras_json
    extras = pick(meeting.get("recap_extras_json"), PUBLIC_EXTRAS_KEYS)
    action_items = sanitize_action_items(
        (summary or {}).get("action_items") if summary else []
    )
    return {
        "title": meeting.get("title"),
        "summary": summary,
        "extras": extras,
        "action_items": action_items,
    }
