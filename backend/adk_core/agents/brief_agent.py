"""Pre-meeting brief agent — ReAct loop over KB, past meetings, and web sources."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool

from adk_core.tools.search_tools import news_search, scrape_page, web_search

logger = logging.getLogger(__name__)


def _build_search_kb_tool(twin_id: str) -> FunctionTool:
    """Build a KB search tool scoped to the given twin's knowledge base."""

    async def search_knowledge_base(query: str) -> str:
        """Search the user's personal knowledge base for context relevant to
        the meeting topic or participant.

        Args:
            query: Topic, person name, or concept to search for.
        """
        from adk_core.services.vector_store import search as kb_search

        try:
            chunks = await kb_search(
                query=query,
                twin_id=twin_id,
                top_k=5,
                allowed_tiers=["public", "team"],
            )
            if not chunks:
                return "No relevant knowledge base entries found."
            lines = [f"[{i + 1}] {c.get('text', '').strip()}" for i, c in enumerate(chunks)]
            return "\n".join(lines)
        except Exception as exc:
            logger.warning("[BriefAgent] KB search failed query=%r: %s", query[:40], exc)
            return "Knowledge base search unavailable."

    return FunctionTool(search_knowledge_base)


def _build_past_meetings_tool(twin_id: str, tenant_id: str) -> FunctionTool:
    """Build a tool that queries past meeting transcripts for a participant."""

    async def search_past_meetings(participant_name: str) -> str:
        """Search past meeting transcripts and summaries for interactions with
        a specific participant.

        Args:
            participant_name: Full name (or partial name) of the participant.
        """
        from modules.observability import get_supabase_client

        sb = get_supabase_client()
        try:
            # Salvage note: PR #125 selected `attendees` but our schema column
            # is `attendees_json` (set by the calendar sync handler). Without
            # this fix the tool would silently return "no past meetings" for
            # every participant. See docs/superpowers/plans/2026-05-21-salvage-from-pr-125.md.
            # AUDIT FIX (W9d): include `id` in the SELECT. The previous shape
            # dropped meeting_id, so when the deep-research agent emitted
            # previous_interactions[] it had no `meeting_id` to populate.
            # The heads_up engine cites previous interactions via source.ref
            # (which expects a meeting_id), so without this the deep brief's
            # citations would be empty for every action_item_pending /
            # prior_topic_tension caution.
            resp = await asyncio.to_thread(
                lambda: sb.table("meetings")
                .select("id, title, summary, meeting_start, attendees_json")
                .eq("twin_id", twin_id)
                .eq("tenant_id", tenant_id)
                .eq("status", "completed")
                .order("meeting_start", desc=True)
                .limit(20)
                .execute()
            )
            meetings = resp.data or []

            # attendees_json is a list of dicts ({email, displayName, name, ...})
            # OR plain strings. Match against displayName + name + email
            # explicitly — previously this used `str(dict).lower()` which
            # matched against the literal "email"/"displayname" key names
            # and produced false positives (e.g. searching "on" matched
            # "personaon" in email keys).
            def _attendee_match_text(a: Any) -> str:
                if isinstance(a, dict):
                    return " ".join(
                        str(a.get(k, "")) for k in ("displayName", "name", "email")
                    ).lower()
                if isinstance(a, str):
                    return a.lower()
                return ""

            name_lower = participant_name.lower()
            matches = [
                m for m in meetings
                if any(
                    name_lower in _attendee_match_text(a)
                    for a in (m.get("attendees_json") or [])
                )
            ][:5]

            if not matches:
                return f"No past meetings found with {participant_name}."

            lines = []
            for m in matches:
                date = (m.get("meeting_start") or "")[:10]
                title = m.get("title") or "Untitled meeting"
                summary = (m.get("summary") or "No summary available.")[:300]
                # AUDIT FIX (W9d): surface meeting_id so the LLM can include
                # it in the JSON output for previous_interactions[]. The
                # system prompt at line 167 already documents this field;
                # without the id in the tool output, the model would have
                # to invent it (or leave it empty).
                meeting_id_val = m.get("id") or ""
                lines.append(
                    f"[{date}] meeting_id={meeting_id_val} {title}: {summary}"
                )
            return "\n".join(lines)
        except Exception as exc:
            logger.warning(
                "[BriefAgent] past meetings search failed participant=%r: %s",
                participant_name[:40],
                exc,
            )
            return "Past meetings search unavailable."

    return FunctionTool(search_past_meetings)


def build_brief_agent(
    *,
    model: Any,
    twin_id: str,
    tenant_id: str,
    title: str,
    participants: list[str],
    goal: str,
    notes: str = "",
) -> LlmAgent:
    """Build the pre-meeting brief ReAct agent.

    The agent searches the KB, past meetings, and web sources for each
    participant, then synthesises everything into a structured JSON brief.
    """
    participants_str = ", ".join(participants) if participants else "unspecified"
    notes_section = f"\nAdditional context: {notes}" if notes else ""

    return LlmAgent(
        name="pre_meeting_brief",
        model=model,
        instruction=f"""You are preparing a pre-meeting brief for a professional.

Meeting: {title}
Participants: {participants_str}
Goal: {goal}{notes_section}

RESEARCH STRATEGY:
1. Search the knowledge base for context about the meeting topic and each participant.
2. Search past meetings for prior interactions with each participant.
3. For each named participant, do a web search to find their role, background, and recent activities.
4. Optionally scrape 1-2 high-value pages per participant for richer context.
5. Search news for any recent coverage of the participants or the meeting topic.

RULES:
- Use search_knowledge_base before web searching — internal context is highest priority.
- Use search_past_meetings for EACH named participant.
- Limit web scraping to 2 pages per participant max.
- Stop after researching all participants — do not over-search.
- If you find very little on a participant, say so honestly.

OUTPUT FORMAT (JSON only — no surrounding text):
{{
  "talking_points": [
    {{"topic": "string", "rationale": "string"}}
  ],
  "participant_insights": [
    {{
      "name": "string",
      "role": "string",
      "background": "string",
      "recent_activities": ["string"],
      "web_sources": ["url"]
    }}
  ],
  "previous_interactions": [
    {{
      "date": "YYYY-MM-DD",
      "meeting_title": "string",
      "summary": "string",
      "open_items": ["string"]
    }}
  ],
  "suggested_agenda": ["string"],
  "caution_notes": ["string"],
  "sources_used": {{
    "kb_chunks": 0,
    "web_results": 0,
    "past_meetings": 0
  }}
}}
""".strip(),
        tools=[
            _build_search_kb_tool(twin_id),
            _build_past_meetings_tool(twin_id, tenant_id),
            web_search,
            news_search,
            scrape_page,
        ],
        output_key="brief_result",
    )
