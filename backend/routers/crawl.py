"""Crawl compatibility helpers.

This module preserves the small crawl-changes helper expected by legacy tests.
The active crawl/enrichment paths live elsewhere.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _calculate_changes(pages: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize crawl page classifications for the legacy changes endpoint."""
    result: dict[str, Any] = {
        "unchanged": 0,
        "changed": 0,
        "new": 0,
        "changes_list": [],
    }

    for page in pages:
        status = str(page.get("status") or "")
        if status == "unchanged":
            classification = "unchanged"
            result["unchanged"] += 1
        elif status == "changed":
            classification = "changed"
            result["changed"] += 1
        else:
            classification = "new"
            result["new"] += 1

        raw_metadata = page.get("metadata")
        metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
        result["changes_list"].append(
            {
                "url": page.get("canonical_url") or page.get("url"),
                "classification": classification,
                "previous_hash": metadata.get("previous_content_hash"),
                "current_hash": page.get("content_hash"),
            }
        )

    return result
