"""
Meeting Analyzer Service

Provides all analysis logic for meeting transcripts:
  - Speaker analytics: talk time, WPM, filler words (pure Python, no AI)
  - Transcript segmentation for map-reduce (15-min windows)
  - Gemini structured summary generation (short and map-reduce paths)
  - Per-speaker sentiment analysis via Gemini

Entry point for worker handler (Plan 02):
    summary, analytics = await analyze_meeting(meeting_dict)

All Gemini calls use asyncio.to_thread — NOT asyncio.create_task (Cloud Run constraint).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from adk_core.model_names import chat_model_name
from collections import defaultdict
from typing import Any

import google.genai as genai
import google.genai.types as genai_types

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FILLER_WORDS = {
    "um", "uh", "like", "you know", "basically", "literally",
    "actually", "so", "right", "okay", "well",
}

SEGMENT_WINDOW_SECONDS = 900       # 15 minutes
MAP_REDUCE_THRESHOLD_SECONDS = 1800  # 30 minutes


# ---------------------------------------------------------------------------
# Gemini client
# ---------------------------------------------------------------------------


def _get_genai_client() -> genai.Client:
    """Return a native google.genai Client using the project's API key."""
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not configured")
    return genai.Client(api_key=api_key)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "recap": {
            "type": "string",
            "description": "1-3 sentence narrative of what happened in the meeting.",
        },
        "intent_vs_outcome": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "description": "User's stated goal entering the meeting.",
                },
                "outcome": {
                    "type": "string",
                    "description": "What actually happened relative to the goal.",
                },
            },
            "required": ["intent", "outcome"],
        },
        "action_items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "owner": {
                        "type": "string",
                        "description": "'me', 'them', or a participant name.",
                    },
                    "description": {"type": "string"},
                    "due": {
                        "type": "string",
                        "nullable": True,
                        "description": "ISO date or null.",
                    },
                },
                "required": ["owner", "description"],
            },
        },
        "commitments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "by": {
                        "type": "string",
                        "description": "Who is committing.",
                    },
                    "to": {
                        "type": "string",
                        "description": "Beneficiary of the commitment.",
                    },
                    "what": {"type": "string"},
                    "due": {"type": "string", "nullable": True},
                },
                "required": ["by", "to", "what"],
            },
        },
        "decisions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Decisions made in the meeting.",
        },
        "topics": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Key topics discussed.",
        },
        "unanswered_questions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Open questions left unresolved.",
        },
        "people_observed": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role_hint": {"type": "string", "nullable": True},
                },
                "required": ["name"],
            },
        },
        "my_positions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "subject": {
                        "type": "string",
                        "description": "Topic the user took a position on.",
                    },
                    "stance": {
                        "type": "string",
                        "description": "The user's first-person view or preference.",
                    },
                    "supersedes": {
                        "type": "string",
                        "nullable": True,
                        "description": "claim_id of prior position this supersedes, if any.",
                    },
                },
                "required": ["subject", "stance"],
            },
        },
        "style_sample": {
            "type": "string",
            "description": "One representative quote from the user.",
        },
    },
    "required": [
        "recap",
        "intent_vs_outcome",
        "action_items",
        "commitments",
        "decisions",
        "topics",
        "unanswered_questions",
        "people_observed",
        "my_positions",
        "style_sample",
    ],
}

SENTIMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "label": {
            "type": "string",
            "enum": ["positive", "neutral", "negative"],
        },
        "score": {"type": "number"},
    },
    "required": ["label", "score"],
}

# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

SUMMARY_PROMPT_TEMPLATE = """You are a meeting analyst. Analyze this meeting transcript and return a JSON object matching the schema.

Meeting title: {title}
Duration: {duration_min} minutes
Participants: {participants}

User's stated goal entering the meeting: {user_goal}
User's free-text context: {user_context}

{prior_recaps_section}

Transcript:
{transcript_text}

Return JSON matching the schema. Field guidance:
- recap: 1-3 sentence narrative of what happened, plain English.
- intent_vs_outcome: compare user's stated goal vs what actually happened.
- action_items: concrete tasks with owner ('me', 'them', or name) + description + optional due date.
- commitments: explicit promises (by -> to -> what), e.g. "I committed to send the proposal by Friday".
- decisions: concrete decisions made (not topics discussed -- actual yes/no choices).
- topics: key topics discussed (1 sentence each, max 8).
- unanswered_questions: open questions raised but not resolved (max 5).
- people_observed: every non-user participant by name, with role_hint if inferable.
- my_positions: first-person views the user stated ("I think X" or "I prefer Y"). Distinct from facts -- these are opinions or preferences that the user expressed.
- style_sample: one representative quote from the user showing their voice/tone.

Focus on concrete outcomes and the user's perspective. Ignore greetings and small talk."""

# REDUCE_PROMPT_TEMPLATE intentionally lacks {prior_recaps_section} and
# {user_context} — those are baked into the segment summaries during the map
# phase (_summarize_segments) before being passed here. The reduce step only
# needs to deduplicate and synthesize across segments; reintroducing the prior
# context here would be redundant and could double-weight it in the final recap.
REDUCE_PROMPT_TEMPLATE = """You are a meeting analyst. You have summaries from multiple segments of one meeting.
Merge them into a single coherent summary matching the schema.

Meeting title: {title}
User's stated goal: {user_goal}

Segment summaries (JSON):
{segment_summaries_json}

Return one final JSON object that:
- Deduplicates action_items, commitments, decisions, topics, unanswered_questions, people_observed, my_positions across segments
- recap: synthesizes a single 1-3 sentence narrative covering the whole meeting
- intent_vs_outcome: aggregates outcome relative to the stated goal
- style_sample: picks the single best representative quote from any segment
"""


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------


def _strip_markdown_fences(text: str) -> str:
    """Strip ```json ... ``` or ``` ... ``` wrapping from Gemini responses.

    Gemini occasionally wraps JSON in markdown fences even when
    response_mime_type is set to application/json.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    # Split on first ``` and take everything after the opening fence line
    parts = stripped.split("```", 2)
    if len(parts) < 2:
        return stripped
    inner = parts[1]
    # Remove language tag if present (e.g. "json\n...")
    if inner.startswith("json"):
        inner = inner[4:]
    # Remove trailing ``` if present
    if inner.endswith("```"):
        inner = inner[:-3]
    return inner.strip()


def _word_start(word: dict) -> float:
    """Extract start time (seconds) from a word dict.

    Handles both formats:
      - New: word["start_timestamp"]["relative"] (Recall.ai diarized-processed1.1)
      - Legacy: word["start"] (used in unit tests / older API)
    """
    ts = word.get("start_timestamp")
    if isinstance(ts, dict):
        return float(ts.get("relative") or 0.0)
    val = word.get("start")
    return float(val) if val is not None else 0.0


def _word_end(word: dict) -> float | None:
    """Extract end time (seconds) from a word dict, or None if absent."""
    ts = word.get("end_timestamp")
    if isinstance(ts, dict):
        val = ts.get("relative")
        return float(val) if val is not None else None
    val = word.get("end")
    return float(val) if val is not None else None


def _is_adk_transcript(transcript_entries: list[dict]) -> bool:
    """Return True if entries are the ADK shape {"speaker", "text", "ts"}.

    ADK entries have a top-level "ts" float; Recall entries have "participant"
    and "words" nested keys.
    """
    if not transcript_entries:
        return False
    first = transcript_entries[0]
    return "ts" in first and "speaker" in first and "participant" not in first


def _estimate_duration_from_transcript(transcript_entries: list[dict]) -> float:
    """Derive meeting duration from transcript timestamps.

    Handles both Recall shape (word end timestamps) and ADK shape (entry ts).
    Returns 0.0 if no timestamps are present.
    Used as fallback when duration_seconds is null on the meeting row.
    """
    if not transcript_entries:
        return 0.0

    if _is_adk_transcript(transcript_entries):
        # ADK shape: {"speaker": ..., "text": ..., "ts": float}
        timestamps = [
            float(e["ts"]) for e in transcript_entries
            if isinstance(e.get("ts"), (int, float))
        ]
        if len(timestamps) >= 2:
            return timestamps[-1] - timestamps[0]
        return 0.0

    # Recall shape: entries with words arrays containing timestamps
    max_end = 0.0
    for entry in transcript_entries:
        for word in entry.get("words") or []:
            if not isinstance(word, dict):
                continue
            end = _word_end(word)
            if end is not None and end > max_end:
                max_end = end
    return max_end


def _split_transcript_into_segments(transcript_entries: list[dict]) -> list[str]:
    """Split diarized transcript into 15-min wall-clock segments.

    Handles both Recall shape (entries with words[]) and ADK shape
    (entries with speaker/text/ts). Returns list of flat text segments.
    """
    if not transcript_entries:
        return []

    segments: list[list[str]] = [[]]
    current_window_end = SEGMENT_WINDOW_SECONDS

    if _is_adk_transcript(transcript_entries):
        # ADK shape: {"speaker": str, "text": str, "ts": float}
        first_ts = float(transcript_entries[0].get("ts") or 0.0)
        for entry in transcript_entries:
            speaker = str(entry.get("speaker") or "Unknown")
            text = str(entry.get("text") or "").strip()
            if not text:
                continue
            offset = float(entry.get("ts") or 0.0) - first_ts
            while offset >= current_window_end:
                segments.append([])
                current_window_end += SEGMENT_WINDOW_SECONDS
            segments[-1].append(f"{speaker}: {text}")
        return ["\n".join(seg) for seg in segments if seg]

    # Recall shape: entries with participant + words arrays
    for entry in transcript_entries:
        participant = entry.get("participant") or {}
        speaker = participant.get("name", "Unknown")
        words = entry.get("words") or []
        if not words:
            continue

        first_word = words[0] if isinstance(words[0], dict) else {}
        start_time = _word_start(first_word)

        while start_time >= current_window_end:
            segments.append([])
            current_window_end += SEGMENT_WINDOW_SECONDS

        text = " ".join(
            w.get("text", "") for w in words if isinstance(w, dict)
        )
        if text.strip():
            segments[-1].append(f"{speaker}: {text.strip()}")

    return ["\n".join(seg) for seg in segments if seg]


def compute_speaker_analytics(
    transcript_entries: list[dict],
    total_duration_seconds: float,
) -> list[dict]:
    """Compute per-speaker analytics from diarized transcript.

    Handles both Recall shape (participant + words arrays) and ADK shape
    (speaker/text/ts entries).

    Args:
        transcript_entries: transcript_raw entries from the meetings table.
        total_duration_seconds: Total meeting duration for percentage calculation.

    Returns:
        List of analytics dicts with keys:
          participant_name, talk_time_seconds, talk_time_pct,
          word_count, words_per_minute, filler_word_count
    """
    speakers: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "word_count": 0,
        "talk_time_seconds": 0.0,
        "filler_count": 0,
    })

    if _is_adk_transcript(transcript_entries):
        # ADK shape: {"speaker": str, "text": str, "ts": float}
        # Estimate per-speaker talk time from ts gaps between consecutive entries
        for i, entry in enumerate(transcript_entries):
            name = str(entry.get("speaker") or "Unknown")
            text = str(entry.get("text") or "")
            words_in_entry = text.split()
            speakers[name]["word_count"] += len(words_in_entry)

            # Approximate talk time: gap to next entry (or 0 for last)
            if i + 1 < len(transcript_entries):
                next_ts = float(transcript_entries[i + 1].get("ts") or 0.0)
                curr_ts = float(entry.get("ts") or 0.0)
                gap = max(0.0, next_ts - curr_ts)
                speakers[name]["talk_time_seconds"] += gap

            for word_text in words_in_entry:
                if word_text.lower().strip(".,!?") in FILLER_WORDS:
                    speakers[name]["filler_count"] += 1
    else:
        # Recall shape: entries with participant + words arrays
        for entry in transcript_entries:
            name = (entry.get("participant") or {}).get("name", "Unknown")
            words = entry.get("words") or []
            for word in words:
                if not isinstance(word, dict):
                    continue

                text = word.get("text", "").lower().strip(".,!?")
                speakers[name]["word_count"] += 1

                start = _word_start(word)
                end = _word_end(word)
                if end is not None:
                    word_duration = max(0.0, end - start)
                    speakers[name]["talk_time_seconds"] += word_duration

                if text in FILLER_WORDS:
                    speakers[name]["filler_count"] += 1

    results = []
    for name, data in speakers.items():
        talk_time = data["talk_time_seconds"]
        word_count = data["word_count"]

        talk_pct = (
            (talk_time / total_duration_seconds * 100)
            if total_duration_seconds > 0
            else 0.0
        )
        wpm = (
            (word_count / (talk_time / 60.0))
            if talk_time > 0
            else 0.0
        )

        results.append({
            "participant_name": name,
            "talk_time_seconds": round(talk_time, 1),
            "talk_time_pct": round(talk_pct, 1),
            "word_count": word_count,
            "words_per_minute": round(wpm, 1),
            "filler_word_count": data["filler_count"],
        })

    return results


# ---------------------------------------------------------------------------
# Gemini summary generation
# ---------------------------------------------------------------------------


async def _fetch_prior_recaps_with_same_people(meeting: dict[str, Any]) -> str:
    """Fetch up to 5 prior meetings sharing at least one attendee.

    Returns a formatted text block for injection into the recap prompt, or
    empty string if there's no prior context. Format intentionally compact —
    we're not trying to dump full transcripts into the prompt, just enough
    that the LLM can reference 'last time you discussed X with Alex'.
    """
    from modules.observability import get_supabase_client

    twin_id = meeting.get("twin_id")
    attendees = meeting.get("attendees_json") or []
    if not twin_id or not attendees:
        return ""

    # Best-effort: get up to 5 prior meetings for the twin that overlap on attendee
    # email/name. attendees_json shape is freeform; we treat any string match as a hit.
    attendee_keys: list[str] = []
    for a in attendees:
        if isinstance(a, dict):
            if a.get("email"):
                attendee_keys.append(a["email"].lower())
            if a.get("name"):
                attendee_keys.append(a["name"].lower())
        elif isinstance(a, str):
            attendee_keys.append(a.lower())

    if not attendee_keys:
        return ""

    try:
        supabase = get_supabase_client()
        # TODO(graduation): client-side attendee intersection over a 20-row recency window
        # can miss matches for high-volume twins where recent meetings don't overlap with
        # the current attendee set. Move the intersection into SQL (JSONB containment on
        # attendees_json) once meeting volume justifies it.
        # Pull recent recaps for this twin (filter to our attendee intersection client-side)
        resp = await asyncio.to_thread(
            lambda: (
                supabase.table("meetings")
                .select("id, title, created_at, recap, attendees_json")
                .eq("twin_id", twin_id)
                .neq("id", meeting["id"])
                .not_.is_("recap", "null")
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
        )
    except Exception as exc:
        logger.warning("[Recap] prior recaps fetch failed twin=%s: %s", twin_id, exc)
        return ""

    matches: list[str] = []
    for row in (resp.data or []):
        row_attendees = row.get("attendees_json") or []
        row_keys: list[str] = []
        for a in row_attendees:
            if isinstance(a, dict):
                if a.get("email"):
                    row_keys.append(a["email"].lower())
                if a.get("name"):
                    row_keys.append(a["name"].lower())
            elif isinstance(a, str):
                row_keys.append(a.lower())
        if any(k in attendee_keys for k in row_keys):
            recap_text = (row.get("recap") or "").strip()
            if recap_text:
                title = row.get("title") or "Untitled meeting"
                date = (row.get("created_at") or "")[:10]
                matches.append(f"- {date} · {title}: {recap_text[:300]}")
        if len(matches) >= 5:
            break

    if not matches:
        return ""

    return "Prior meetings with overlapping attendees:\n" + "\n".join(matches) + "\n"


async def _summarize_text(
    transcript_text: str,
    title: str,
    duration_min: float,
    participants: list[str],
    user_goal: str = "",
    user_context: str = "",
    prior_recaps_section: str = "",
) -> dict:
    """Generate a structured meeting summary via Gemini.

    Uses asyncio.to_thread since client.models.generate_content is synchronous.
    Strips markdown fences before JSON parsing (Pitfall 3 defense).
    """
    prompt = SUMMARY_PROMPT_TEMPLATE.format(
        title=title,
        duration_min=round(duration_min, 1),
        participants=", ".join(participants) if participants else "Unknown",
        user_goal=user_goal or "(not provided)",
        user_context=user_context or "(not provided)",
        prior_recaps_section=prior_recaps_section or "",
        transcript_text=transcript_text[:50_000],  # cap to avoid runaway cost
    )

    client = _get_genai_client()
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=chat_model_name(),
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SUMMARY_SCHEMA,
        ),
    )

    raw = _strip_markdown_fences(response.text or "")
    return json.loads(raw)


async def _summarize_segments(
    segments: list[str],
    title: str,
    user_goal: str = "",
    user_context: str = "",
    prior_recaps_section: str = "",
) -> list[dict]:
    """Summarize each segment sequentially to avoid Gemini rate limits.

    Returns list of per-segment summary dicts (same shape as SUMMARY_SCHEMA).
    """
    summaries = []
    for i, segment_text in enumerate(segments):
        logger.info(
            "[Recap] summarizing segment %d/%d title=%s",
            i + 1, len(segments), title,
        )
        summary = await _summarize_text(
            transcript_text=segment_text,
            title=f"{title} (Part {i + 1})",
            duration_min=SEGMENT_WINDOW_SECONDS / 60.0,
            participants=[],
            user_goal=user_goal,
            user_context=user_context,
            prior_recaps_section=prior_recaps_section,
        )
        summaries.append(summary)
    return summaries


async def _reduce_summaries(
    segment_summaries: list[dict],
    title: str,
    user_goal: str = "",
) -> dict:
    """Merge multiple segment summaries into one final summary via Gemini.

    Single Gemini call with SUMMARY_SCHEMA to produce the merged result.
    """
    prompt = REDUCE_PROMPT_TEMPLATE.format(
        title=title,
        user_goal=user_goal or "(not provided)",
        segment_summaries_json=json.dumps(segment_summaries, indent=2),
    )

    client = _get_genai_client()

    response = await asyncio.to_thread(
        client.models.generate_content,
        model=chat_model_name(),
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=SUMMARY_SCHEMA,
        ),
    )

    raw = _strip_markdown_fences(response.text or "")
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Sentiment analysis
# ---------------------------------------------------------------------------


async def _analyze_speaker_sentiment(
    speaker_text: str,
    speaker_name: str,
) -> dict:
    """Analyze sentiment for a speaker's combined text.

    Returns {"label": str, "score": float}.
    On failure, returns neutral default to avoid blocking the pipeline.
    """
    if not speaker_text.strip():
        return {"label": "neutral", "score": 0.5}

    prompt = (
        f"Analyze the sentiment of the following text spoken by {speaker_name} in a meeting.\n\n"
        f"Text: {speaker_text[:5000]}\n\n"
        "Return JSON with:\n"
        "- label: one of 'positive', 'neutral', or 'negative'\n"
        "- score: float 0.0-1.0 (confidence / intensity)"
    )

    try:
        client = _get_genai_client()

        response = await asyncio.to_thread(
            client.models.generate_content,
            model=chat_model_name(),
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=SENTIMENT_SCHEMA,
            ),
        )

        raw = _strip_markdown_fences(response.text or "")
        result = json.loads(raw)

        label = result.get("label", "neutral")
        if label not in ("positive", "neutral", "negative"):
            label = "neutral"
        score = float(result.get("score", 0.5))
        score = max(0.0, min(1.0, score))  # clamp to [0, 1]

        return {"label": label, "score": score}

    except Exception as exc:
        logger.warning(
            "[Recap] sentiment analysis failed speaker=%s: %s",
            speaker_name, exc,
        )
        return {"label": "neutral", "score": 0.5}


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


async def analyze_meeting(meeting: dict) -> tuple[dict, list[dict]]:
    """Analyze a meeting record and produce structured summary + speaker analytics.

    Args:
        meeting: Dict from the meetings table with keys:
            title, transcript_raw, transcript_text, duration_seconds,
            user_goal (optional), user_context (optional),
            attendees_json (optional, used for prior-recap carry-forward).

    Returns:
        (summary_dict, analytics_list_with_sentiment)

        summary_dict has the 11-field RecapContract shape: recap,
        intent_vs_outcome, action_items, commitments, decisions, topics,
        unanswered_questions, people_observed, my_positions, style_sample.
        analytics_list has one dict per speaker with analytics + sentiment_label/score.
    """
    transcript_raw: list[dict] = meeting.get("transcript_raw") or []
    transcript_text: str = meeting.get("transcript_text") or ""
    title: str = meeting.get("title") or "Meeting"
    user_goal: str = meeting.get("user_goal") or ""
    user_context: str = meeting.get("user_context") or ""

    # Derive duration — prefer explicit value, fall back to transcript timestamps
    duration = float(
        meeting.get("duration_seconds")
        or _estimate_duration_from_transcript(transcript_raw)
        or 0.0
    )

    # Compute speaker analytics (pure Python, no AI)
    analytics = compute_speaker_analytics(transcript_raw, duration)

    # Extract participant names for prompt context
    participants = [a["participant_name"] for a in analytics]

    # Fetch prior-meeting carry-forward (best-effort, empty on any failure)
    prior_recaps_section = await _fetch_prior_recaps_with_same_people(meeting)

    # Choose summary strategy based on meeting duration
    duration_min = duration / 60.0

    if duration >= MAP_REDUCE_THRESHOLD_SECONDS:
        logger.info(
            "[Recap] using map-reduce strategy duration_min=%.1f title=%s",
            duration_min, title,
        )
        segments = _split_transcript_into_segments(transcript_raw)
        if segments:
            segment_summaries = await _summarize_segments(
                segments,
                title=title,
                user_goal=user_goal,
                user_context=user_context,
                prior_recaps_section=prior_recaps_section,
            )
            summary = await _reduce_summaries(
                segment_summaries,
                title=title,
                user_goal=user_goal,
            )
        else:
            # Fallback: no segments found despite long duration — single call
            summary = await _summarize_text(
                transcript_text=transcript_text,
                title=title,
                duration_min=duration_min,
                participants=participants,
                user_goal=user_goal,
                user_context=user_context,
                prior_recaps_section=prior_recaps_section,
            )
    else:
        logger.info(
            "[Recap] using single-call strategy duration_min=%.1f title=%s",
            duration_min, title,
        )
        summary = await _summarize_text(
            transcript_text=transcript_text,
            title=title,
            duration_min=duration_min,
            participants=participants,
            user_goal=user_goal,
            user_context=user_context,
            prior_recaps_section=prior_recaps_section,
        )

    # Enrich analytics with per-speaker sentiment
    # Build speaker → text map from transcript_raw for sentiment analysis
    speaker_texts: dict[str, list[str]] = defaultdict(list)
    for entry in transcript_raw:
        if _is_adk_transcript([entry]):
            name = str(entry.get("speaker") or "Unknown")
            text = str(entry.get("text") or "").strip()
        else:
            name = (entry.get("participant") or {}).get("name", "Unknown")
            words = entry.get("words") or []
            text = " ".join(w.get("text", "") for w in words if isinstance(w, dict)).strip()
        if text:
            speaker_texts[name].append(text)

    enriched_analytics = []
    for item in analytics:
        name = item["participant_name"]
        combined_text = " ".join(speaker_texts.get(name, []))
        sentiment = await _analyze_speaker_sentiment(combined_text, name)
        enriched_analytics.append({
            **item,
            "sentiment_label": sentiment["label"],
            "sentiment_score": sentiment["score"],
        })

    logger.info(
        "[Recap] completed title=%s speakers=%d topics=%d",
        title,
        len(enriched_analytics),
        len(summary.get("topics", [])),
    )

    return summary, enriched_analytics
