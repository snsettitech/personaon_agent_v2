"""Convert recap_extras_json.commitments into structured rows for meeting_commitments.

Pure function — no LLM, no DB. Called by graph_outbox_worker after extract_recap_extras
returns to materialize meeting_commitments rows. Idempotency via content_hash:
UPSERT on (meeting_id, content_hash, source) preserves user-set done/dismissed status.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from services.name_match import is_name_variant

logger = logging.getLogger(__name__)


def _direction(assignee: str | None, owner_name: str) -> str:
    if not assignee:
        return "unknown"
    a = assignee.strip().lower()
    if not a or a in {"owner", "you", "me", "i"}:
        return "you_owe"
    if is_name_variant(assignee, owner_name):
        return "you_owe"
    return "they_owe"


def content_hash(text: str, assignee_name: str | None, due_at: str | None) -> str:
    key = f"{text.strip().lower()}|{(assignee_name or '').strip().lower()}|{(due_at or '').strip()}"
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def structured_commitments_from_extras(
    extras: dict[str, Any] | None,
    *,
    owner_name: str,
) -> list[dict[str, Any]]:
    """Convert the commitments list from recap_extras_json into structured dicts.

    Args:
        extras: The full recap_extras_json dict (may be None or empty).
        owner_name: The meeting owner's display name, used to classify direction.

    Returns:
        List of dicts with keys: text, direction, assignee_name, due_at, content_hash.
        Returns [] if extras has no usable commitments.
    """
    if not isinstance(extras, dict):
        return []
    raw = extras.get("commitments") or []
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            if not text:
                continue
            out.append({
                "text": text,
                "direction": "unknown",
                "assignee_name": None,
                "due_at": None,
                "content_hash": content_hash(text, None, None),
            })
            continue
        if not isinstance(item, dict):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        assignee = item.get("assignee")
        assignee = assignee.strip() if isinstance(assignee, str) and assignee.strip() else None
        direction = _direction(assignee, owner_name)
        assignee_name = None if direction == "you_owe" else assignee
        due_at = item.get("due_at") if isinstance(item.get("due_at"), str) else None
        out.append({
            "text": text,
            "direction": direction,
            "assignee_name": assignee_name,
            "due_at": due_at,
            "content_hash": content_hash(text, assignee_name, due_at),
        })
    return out
