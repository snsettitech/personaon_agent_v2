"""
Generic section parsing utilities for document ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from collections.abc import Sequence

_WHITESPACE_RE = re.compile(r"\s+")
_NUMBERED_HEADING_RE = re.compile(r"^\s*(\d{1,3})[\)\.]?\s+(.+?)\s*$")
_MARKDOWN_HEADING_RE = re.compile(r"^\s*#{1,6}\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d{1,3}[\)\.])\s+.+")
_PROMPT_LEAD_RE = re.compile(
    r"^\s*(?:who|what|when|where|why|how|can|do|does|did|should|would|is|are|could)\b",
    re.IGNORECASE,
)


def _normalize_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", (value or "").strip())


def _split_doc_lines(text: str) -> list[str]:
    raw = (text or "").replace("\r\n", "\n")
    raw = raw.replace(" | ", "\n").replace("|", "\n")
    rows: list[str] = []
    for line in raw.split("\n"):
        normalized = _normalize_text(line)
        if normalized:
            rows.append(normalized)
    return rows


def _looks_like_short_title(line: str) -> bool:
    words = line.split()
    if len(words) == 0 or len(words) > 12:
        return False
    if len(line) > 90:
        return False
    upper = sum(1 for ch in line if ch.isupper())
    alpha = sum(1 for ch in line if ch.isalpha())
    if alpha == 0:
        return False
    ratio = upper / float(alpha)
    return ratio > 0.65


def _detect_heading(line: str) -> dict[str, Any] | None:
    numbered = _NUMBERED_HEADING_RE.match(line)
    if numbered:
        tail = numbered.group(2).strip()
        if _looks_like_prompt_question_line(tail):
            return None
        return {"level": 1, "title": f"{numbered.group(1)}) {tail}"}

    markdown = _MARKDOWN_HEADING_RE.match(line)
    if markdown:
        return {"level": 1, "title": markdown.group(1).strip()}

    if _looks_like_short_title(line):
        return {"level": 1, "title": line.strip()}

    if line.endswith(":") and len(line.split()) <= 10:
        return {"level": 2, "title": line.strip(": ").strip()}

    return None


def _looks_like_prompt_question_line(line: str) -> bool:
    normalized = _normalize_text(line).rstrip(".")
    if not normalized:
        return False
    if normalized.endswith("?"):
        return True
    return bool(_PROMPT_LEAD_RE.match(normalized))


def _infer_block_type(text: str) -> str:
    normalized = _normalize_text(text)
    if not normalized:
        return "paragraph"

    lines = [_normalize_text(row) for row in str(text or "").split("\n") if _normalize_text(row)]
    if not lines:
        return "paragraph"

    if len(lines) == 1:
        line = lines[0]
        if _looks_like_short_title(line):
            return "heading"
        if _looks_like_prompt_question_line(line):
            return "prompt_question"

    question_like = 0
    bullet_like = 0
    for line in lines:
        if _looks_like_prompt_question_line(line):
            question_like += 1
        if _BULLET_RE.match(line):
            bullet_like += 1

    line_count = len(lines)
    if line_count > 0 and question_like >= 2 and (question_like / float(line_count)) >= 0.5:
        return "prompt_question"
    if line_count > 0 and bullet_like >= 2 and (bullet_like / float(line_count)) >= 0.5:
        return "bullet_list"
    if "|" in normalized and line_count >= 2:
        return "table"

    return "answer_text"


def extract_section_blocks(
    text: str,
    *,
    source_id: str | None = None,
    base_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Parse freeform text into coherent section blocks using generic heading detection.
    """
    lines = _split_doc_lines(text)
    if not lines:
        return []

    base = dict(base_metadata or {})
    blocks: list[dict[str, Any]] = []
    root_title = "General"
    active_title = "General"
    active_path = "General"
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        joined = "\n".join(buffer).strip()
        if not joined:
            buffer = []
            return
        row = dict(base)
        row["text"] = joined
        if source_id:
            row["source_id"] = source_id
        row["section_title"] = active_title
        row["section_path"] = active_path
        row["chunk_type"] = "section"
        block_type = _infer_block_type(joined)
        row["block_type"] = block_type
        row["is_answer_text"] = block_type in {"answer_text", "bullet_list", "table", "paragraph"}
        blocks.append(row)
        buffer = []

    for line in lines:
        heading = _detect_heading(line)
        if heading:
            flush()
            if heading.get("level") == 1:
                root_title = str(heading["title"])
                active_title = root_title
                active_path = root_title
            else:
                active_title = str(heading["title"])
                active_path = f"{root_title} > {active_title}" if root_title else active_title
            buffer.append(line)
            continue
        buffer.append(line)

    flush()
    return blocks


@dataclass(frozen=True)
class QueryIntentProfile:
    intent: str
    allowed_chunk_types: tuple[str, ...]
    preferred_chunk_types: tuple[str, ...]
    allow_multi_section: bool = True
    disable_label_bonus: bool = True


def classify_query_intent_profile(_query: str) -> QueryIntentProfile:
    """
    Kept for backward compatibility. General mode only.
    """
    return QueryIntentProfile("general", tuple(), tuple())


def section_filter_contexts(
    _query: str,
    contexts: Sequence[dict[str, Any]],
    *,
    max_items: int | None = None,
) -> list[dict[str, Any]]:
    """
    Generic context pass-through kept for compatibility.
    """
    if max_items is None:
        return [dict(c) for c in contexts if isinstance(c, dict)]
    return [dict(c) for c in contexts if isinstance(c, dict)][: max(0, max_items)]
