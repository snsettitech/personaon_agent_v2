"""Shared helpers for ADK tool functions.

Eliminates duplicated state-extraction, URL hashing, and result
accumulation patterns across retrieval, search, and research tools.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from typing import Any

from google.adk.tools import ToolContext

from adk_core.state_keys import SessionKey


def require_state(tool_context: ToolContext, key: str) -> str:
    """Extract and validate a required state key. Returns the stripped value.

    Raises ValueError if the key is missing or blank.
    """
    value = str(tool_context.state.get(key) or "").strip()
    if not value:
        raise ValueError(f"Missing required state: {key}")
    return value


def require_twin_id(tool_context: ToolContext) -> str:
    """Shortcut: extract session:twin_id or raise."""
    return require_state(tool_context, SessionKey.TWIN_ID)


def get_state_str(tool_context: ToolContext, key: str, default: str = "") -> str:
    """Extract an optional state key as a stripped string."""
    return str(tool_context.state.get(key) or default).strip()


def url_source_id(url: str, fallback_idx: int) -> str:
    """URL -> deterministic source ID (domain prefix + MD5 hash)."""
    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc.replace("www.", "")[:20]
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        return f"{domain}-{url_hash}"
    except Exception:
        return f"src-{fallback_idx}"


def accumulate_json_list(
    tool_context: ToolContext,
    key: str,
    items: list[dict[str, Any]],
    *,
    dedup_field: str | None = None,
) -> None:
    """Append items to an existing JSON list in state, optionally deduplicating."""
    existing = json.loads(tool_context.state.get(key, "[]"))
    if dedup_field:
        seen = {r[dedup_field] for r in existing if dedup_field in r}
        for item in items:
            if item.get(dedup_field) not in seen:
                existing.append(item)
                seen.add(item.get(dedup_field))
    else:
        existing.extend(items)
    tool_context.state[key] = json.dumps(existing)


def error_result(message: str) -> dict[str, Any]:
    """Standard error return for tool functions."""
    return {"status": "error", "error_message": message}
