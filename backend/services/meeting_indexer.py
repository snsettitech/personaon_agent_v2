"""Meeting Indexer Service

Transforms raw Recall.ai transcripts into speaker-turn chunks suitable for
vector indexing, and extracts structured entities (people, companies, topics)
from meeting text.

Public API:
    chunk_transcript_by_turns(transcript_raw, turns_per_chunk=4, max_chunk_chars=900)
    normalize_entity(raw: str) -> str
    extract_entities(transcript_text: str) -> dict[str, list[str]]  (async)
    index_meeting_chunks(meeting_id, twin_id, chunks) -> int  (async)

Scope note (MTG-19): Entity deduplication uses exact-match lowercase only
(via normalize_entity). Co-reference resolution (alias tables, pronoun mapping
such as "Tim" -> "Tim Cook") is deferred to Phase 28+. This is an explicit
scope decision, not an oversight.

All Gemini calls use asyncio.to_thread — NOT asyncio.create_task (Cloud Run constraint).
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import google.genai.types as genai_types

from adk_core.model_names import chat_model_name
from adk_core.services.vector_store import upsert_text_chunks
from modules.observability import get_supabase_client
from services.llm_budget import LlmBudgetExceeded, run_with_budget
from services.meeting_analyzer import _get_genai_client, _strip_markdown_fences

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Entity extraction schema
# ---------------------------------------------------------------------------

ENTITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "people": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Full names of people mentioned",
        },
        "companies": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Company or organization names mentioned",
        },
        "topics": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Key topics, products, or concepts discussed",
        },
    },
    "required": ["people", "companies", "topics"],
}

# Minimum transcript length to bother calling Gemini for entity extraction.
_MIN_ENTITY_TRANSCRIPT_CHARS = 500


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def chunk_transcript_by_turns(
    transcript_raw: list[dict],
    turns_per_chunk: int = 4,
    max_chunk_chars: int = 900,
) -> list[dict]:
    """Split a Recall.ai transcript into speaker-turn chunks.

    Args:
        transcript_raw: List of Recall.ai transcript entries, each with
            ``participant.name`` and ``words`` arrays.
        turns_per_chunk: Maximum number of speaker turns per chunk.
        max_chunk_chars: Flush the current chunk when accumulated text
            exceeds this character limit (before the next entry would push
            it over), irrespective of turn count.

    Returns:
        List of chunk dicts with keys:
            text        — newline-joined "Speaker: words" lines
            speakers    — sorted list of unique speaker names in this chunk
            start_time  — float seconds of the first word (or 0.0)
            end_time    — float seconds of the last word (or 0.0)
            chunk_index — zero-based index
    """
    chunks: list[dict] = []
    current_lines: list[str] = []
    current_speakers: set[str] = set()
    current_start: float = 0.0
    current_end: float = 0.0
    chunk_index: int = 0

    def _flush() -> None:
        nonlocal chunk_index, current_lines, current_speakers, current_start, current_end
        if not current_lines:
            return
        chunks.append({
            "text": "\n".join(current_lines),
            "speakers": sorted(current_speakers),
            "start_time": current_start,
            "end_time": current_end,
            "chunk_index": chunk_index,
        })
        chunk_index += 1
        current_lines = []
        current_speakers = set()
        current_start = 0.0
        current_end = 0.0

    for entry in transcript_raw:
        # Support two transcript shapes:
        #   Recall: {"participant": {"name": str}, "words": [{text, start_time, end_time}]}
        #   ADK:    {"speaker": str, "text": str, "ts": float}
        if "speaker" in entry and "text" in entry and "words" not in entry:
            # ADK shape
            speaker = str(entry.get("speaker") or "Unknown")
            text = str(entry.get("text") or "").strip()
            if not text:
                continue
            ts = float(entry.get("ts") or 0.0)
            entry_start = ts
            entry_end = ts
        else:
            # Recall shape
            speaker = (entry.get("participant") or {}).get("name", "Unknown")
            words = entry.get("words") or []
            if not words:
                continue

            text_parts = [
                w.get("text", "") for w in words if isinstance(w, dict)
            ]
            text = " ".join(text_parts).strip()
            if not text:
                continue

            first_word = next((w for w in words if isinstance(w, dict)), {})
            last_word = next(
                (w for w in reversed(words) if isinstance(w, dict)), {}
            )
            entry_start = _word_start_ts(first_word)
            entry_end = _word_end_ts(last_word)

        line = f"{speaker}: {text}"

        # Check if adding this line would exceed char limit (flush first)
        if current_lines:
            accumulated_chars = sum(len(l) for l in current_lines)
            if accumulated_chars + len(line) >= max_chunk_chars:
                _flush()

        # Set chunk start time on the first line of a new chunk
        if not current_lines:
            current_start = entry_start

        current_lines.append(line)
        current_speakers.add(speaker)
        current_end = entry_end

        # Flush when we've hit the turn limit
        if len(current_lines) >= turns_per_chunk:
            _flush()

    # Flush any remaining lines
    _flush()

    return chunks


def normalize_entity(raw: str) -> str:
    """Normalize an entity name: strip whitespace and lowercase.

    Args:
        raw: Raw entity string from Gemini response.

    Returns:
        Lowercased, whitespace-stripped entity name. Returns "" for empty input.
    """
    return raw.strip().lower()


async def extract_entities(
    transcript_text: str,
    *,
    tenant_id: str | None = None,
) -> dict[str, list[str]]:
    """Extract structured entities from a meeting transcript using Gemini.

    Returns a dict with keys ``people``, ``companies``, ``topics`` — each
    a sorted, deduplicated list of normalized (lowercase) entity names.

    Short transcripts (< 500 chars) return empty arrays without calling Gemini.
    On any Gemini exception, fails-open and returns empty arrays so the
    indexing pipeline is not blocked.

    Args:
        transcript_text: Flat text of the meeting transcript.

    Returns:
        {"people": [...], "companies": [...], "topics": [...]}
    """
    empty: dict[str, list[str]] = {"people": [], "companies": [], "topics": []}

    if len(transcript_text) < _MIN_ENTITY_TRANSCRIPT_CHARS:
        return empty

    prompt = (
        "Extract entities from this meeting transcript. "
        "Only include entities explicitly named in the transcript. "
        "Return empty arrays rather than guessing.\n\n"
        f"Transcript:\n{transcript_text[:50_000]}"
    )

    try:
        client = _get_genai_client()
        model = chat_model_name()

        response = await run_with_budget(
            tenant_id=tenant_id or "unknown",
            operation="index_chunk",
            user_id=tenant_id,
            model=model,
            call=lambda: client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=ENTITY_SCHEMA,
                ),
            ),
        )

        raw = _strip_markdown_fences(response.text or "")
        data: dict[str, list[str]] = json.loads(raw)

    except LlmBudgetExceeded:
        logger.warning(
            "[MeetingIndexer] LLM budget exceeded tenant=%s; failing open",
            tenant_id,
        )
        return empty
    except Exception as exc:
        logger.warning(
            "[MeetingIndexer] entity extraction failed — failing open: %s", exc
        )
        return empty

    def _normalize_list(values: list[str]) -> list[str]:
        normalized = [normalize_entity(v) for v in (values or [])]
        return sorted({v for v in normalized if v})

    return {
        "people": _normalize_list(data.get("people", [])),
        "companies": _normalize_list(data.get("companies", [])),
        "topics": _normalize_list(data.get("topics", [])),
    }


async def index_meeting_chunks(
    meeting_id: str,
    twin_id: str,
    chunks: list[dict],
) -> int:
    """Upsert speaker-turn chunks into the vector store for a twin.

    Each chunk is stored with source key ``meeting:{meeting_id}:chunk:{i}``
    and metadata that identifies it as a meeting chunk (for downstream
    source_type weighting in search results).

    Args:
        meeting_id: Unique meeting identifier (UUID string).
        twin_id: Twin whose namespace receives these chunks.
        chunks: List of chunk dicts produced by ``chunk_transcript_by_turns``.

    Returns:
        Total number of vector chunks upserted across all input chunks.
    """
    # chunks.source_id is NOT NULL on this schema. Meetings don't already have
    # a sources row (they aren't a file upload or scraped URL), so create one
    # before inserting any chunk. Using meeting_id as the source row's id keeps
    # the link deterministic: re-indexing the same meeting is a no-op on the
    # sources row and updates the chunks cleanly.
    sb = get_supabase_client()
    try:
        meeting_row = (
            sb.table("meetings")
            .select("title")
            .eq("id", meeting_id)
            .single()
            .execute()
        ).data or {}
        filename = f"Meeting: {meeting_row.get('title') or meeting_id[:8]}"
        await asyncio.to_thread(
            lambda: sb.table("sources").upsert(
                {
                    "id": meeting_id,
                    "twin_id": twin_id,
                    "filename": filename[:255],
                    "status": "live",
                    "is_verified_content": False,
                },
                on_conflict="id",
            ).execute()
        )
    except Exception as exc:
        logger.warning(
            "[MeetingIndexer] sources upsert failed meeting_id=%s: %s — "
            "downstream chunk insert will raise NotNullViolationError",
            meeting_id, exc,
        )
        raise

    total_upserted = 0

    for chunk in chunks:
        i = chunk["chunk_index"]
        source = f"meeting:{meeting_id}:chunk:{i}"
        metadata: dict[str, Any] = {
            "source_type": "meeting",
            "meeting_id": meeting_id,
            "speakers": chunk["speakers"],
            "start_time": chunk["start_time"],
            "end_time": chunk["end_time"],
        }

        logger.info(
            "[MeetingIndexer] upserting chunk meeting_id=%s chunk_index=%d twin_id=%s",
            meeting_id, i, twin_id,
        )

        # Meeting transcripts contain discussion between the twin owner and
        # external participants. Tag `team` so they're excluded from the
        # public marketplace search but remain available for future meeting
        # context prep (owner's own meetings). source_id points at the
        # sources row we upserted above.
        upserted = await upsert_text_chunks(
            text=chunk["text"],
            twin_id=twin_id,
            source=source,
            metadata=metadata,
            source_id=meeting_id,
            privacy_level="team",
        )
        total_upserted += upserted

    logger.info(
        "[MeetingIndexer] indexed %d chunk(s) for meeting_id=%s twin_id=%s",
        len(chunks), meeting_id, twin_id,
    )

    return total_upserted


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _word_start_ts(word: dict) -> float:
    """Extract start time (seconds) from a word dict.

    Handles Recall.ai format (start_timestamp.relative) and legacy test format (start).
    """
    ts = word.get("start_timestamp")
    if isinstance(ts, dict):
        return float(ts.get("relative") or 0.0)
    val = word.get("start")
    return float(val) if val is not None else 0.0


def _word_end_ts(word: dict) -> float:
    """Extract end time (seconds) from a word dict.

    Handles Recall.ai format (end_timestamp.relative) and legacy test format (end).
    Returns 0.0 if absent.
    """
    ts = word.get("end_timestamp")
    if isinstance(ts, dict):
        val = ts.get("relative")
        return float(val) if val is not None else 0.0
    val = word.get("end")
    return float(val) if val is not None else 0.0
