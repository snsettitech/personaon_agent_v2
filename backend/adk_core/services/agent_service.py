"""Single-agent chat service with surface-keyed runner cache.

Runners are cached per (twin_id, surface_class) pair. Owner sessions get
capture_knowledge tool; visitor sessions get queue_question tool.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import OrderedDict
from collections.abc import AsyncGenerator

from google.adk.agents import Agent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.adk.tools import FunctionTool
from google.genai import types

from adk_core.services.prompts import generate_system_prompt
from adk_core.services.vector_store import search as vector_search
from adk_core.tools.capture_tools import _make_capture_tool, _make_queue_tool
from adk_core.tools.respond_tools import _make_followup_draft_tool
from adk_core.tools.persona_edit_tools import _make_update_persona_tool
from modules.llm_safety import sanitize_for_llm

logger = logging.getLogger(__name__)

APP_NAME = "personaon"

# MTG-20: Down-weight meeting chunks so persona content dominates chat context
_MEETING_CHUNK_WEIGHT = float(os.getenv("MEETING_CHUNK_WEIGHT", "0.7"))


def _apply_source_weights(results: list[dict]) -> list[dict]:
    """Down-weight meeting chunks so persona content dominates chat context.

    Treats null/missing source_type as 'persona' (not down-weighted).
    """
    weighted = []
    for row in results:
        source_type = row.get("source_type")
        if source_type == "meeting":
            weighted.append({**row, "score": row["score"] * _MEETING_CHUNK_WEIGHT})
        else:
            weighted.append(row)
    return sorted(weighted, key=lambda r: r.get("score", 0), reverse=True)

_session_service: DatabaseSessionService | None = None

# Runner cache keyed by "{twin_id}:{surface_class}"
_runner_cache: OrderedDict[str, Runner] = OrderedDict()
_MAX_CACHE_SIZE = 100


def _get_session_service() -> DatabaseSessionService:
    global _session_service
    if _session_service is None:
        db_url = os.getenv("ADK_SESSION_DB_URL", "sqlite+aiosqlite:///adk_sessions.db")
        connect_args = (
            {
                "statement_cache_size": 0,
                "prepared_statement_cache_size": 0,
            }
            if db_url.startswith(("postgresql", "postgresql+asyncpg"))
            else None
        )
        kwargs = {"db_url": db_url}
        if connect_args is not None:
            kwargs["connect_args"] = connect_args
        _session_service = DatabaseSessionService(**kwargs)
    return _session_service


def _surface_class(surface: str) -> str:
    """Map surface string to binary surface class for cache keying.

    widget_lead is a distinct surface with its own runner, capture_lead_contact
    tool, and per-turn offer_state injected into the system prompt. public_lead is
    the same conversational-capture flow ported to the public /p persona page
    (the surface with 100% of real traffic); it gets the same lead tool + offer
    block. All other non-owner surfaces (including plain "widget"/"public" from
    chat.py, i.e. capture disabled) map to "visitor" (queue_question only).
    """
    if surface == "owner":
        return "owner"
    if surface == "assistant":
        return "assistant"
    if surface == "widget_lead":
        return "widget_lead"
    if surface == "public_lead":
        return "public_lead"
    return "visitor"


def _retrieval_tiers_for_surface(surface_class: str) -> list[str] | None:
    """Privacy tiers allowed for KB retrieval on this surface.

    Owner/assistant may read all tiers (None = no SQL filter).
    Every public/visitor surface is restricted to ``public`` chunks only
    (ADR-001 / PON-11 — private-by-default for non-owner chat).
    """
    if surface_class in ("owner", "assistant"):
        return None
    return ["public"]


def _cache_key(twin_id: str, surface_class: str) -> str:
    return f"{twin_id}:{surface_class}"


def _make_search_tool(twin_id: str, surface_class: str = "visitor") -> FunctionTool:
    """Return a FunctionTool that searches the twin's pgvector namespace.

    Uses an async inner function so ADK awaits the coroutine natively,
    avoiding the asyncio.run() crash when an event loop is already running
    (always the case under FastAPI / Cloud Run).
    """
    allowed_tiers = _retrieval_tiers_for_surface(surface_class)

    async def search_knowledge_base(query: str, top_k: int = 5) -> list[dict]:
        """Search the persona's knowledge base (scoped by surface privacy tiers)."""
        logger.info(
            "[TOOL] search_knowledge_base query=%r twin=%s surface=%s tiers=%s",
            query[:80], twin_id, surface_class, allowed_tiers,
        )
        try:
            results = await vector_search(
                query=query,
                twin_id=twin_id,
                top_k=top_k,
                allowed_tiers=allowed_tiers,
            )
        except Exception as _exc:
            logger.warning(
                "[TOOL] search_knowledge_base failed twin=%s error=%r — returning empty",
                twin_id, _exc,
            )
            return []
        logger.info("[TOOL] search_knowledge_base -> %d result(s)", len(results))
        return results

    return FunctionTool(func=search_knowledge_base)


def _build_runner(
    twin_id: str,
    profile_dict: dict,
    surface_class: str = "visitor",
    session_id: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    actions: list[dict] | None = None,
) -> Runner:
    """Return a cached Runner for the given twin and surface class.

    surface_class values:
      "owner"     — chat, capture_knowledge tool
      "visitor"   — chat, queue_question tool
      "interview" — interview mode, no tools, NOT cached (instruction changes each turn)
    """
    model_str = os.getenv("ADK_CHAT_MODEL", "gemini-3.5-flash-lite")
    model = LiteLlm(model=model_str) if "/" in model_str else model_str

    if surface_class == "interview":
        # Interview runners are NOT cached. The gap-aware instruction changes after
        # every Q&A pair is saved, so we build a fresh runner each turn to keep
        # it current. Runner creation cost is negligible vs LLM call time.
        agent = Agent(
            name=f"persona_{twin_id.replace('-', '_')}_interview",
            model=model,
            instruction=profile_dict.get("_interview_instruction", "You are an AI interviewer."),
            tools=[],
        )
        return Runner(
            agent=agent,
            app_name=APP_NAME,
            session_service=_get_session_service(),
        )

    key = _cache_key(twin_id, surface_class)
    if key in _runner_cache:
        _runner_cache.move_to_end(key)
        return _runner_cache[key]

    tools: list[FunctionTool] = [_make_search_tool(twin_id, surface_class)]
    if surface_class in ("owner", "assistant"):
        # owner = persona-preview chat; assistant = chief-of-staff Home chat.
        # Both improve (capture_knowledge) and can draft follow-ups.
        tools.append(_make_capture_tool(twin_id))
        tools.append(_make_followup_draft_tool(twin_id))
        if surface_class == "assistant":
            # Only the chief-of-staff edits the public persona page.
            tools.append(_make_update_persona_tool(twin_id))
    else:
        tools.append(
            _make_queue_tool(
                twin_id=twin_id,
                conversation_id=session_id or "",
                visitor_user_id=user_id or "",
                tenant_id=tenant_id,
            )
        )

    instruction = generate_system_prompt(profile_dict, actions=actions, surface_class=surface_class)
    agent = Agent(
        name=f"persona_{twin_id.replace('-', '_')}_{surface_class}",
        model=model,
        instruction=instruction,
        tools=tools,
    )

    runner = Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=_get_session_service(),
    )

    _runner_cache[key] = runner
    while len(_runner_cache) > _MAX_CACHE_SIZE:
        evicted_key, _ = _runner_cache.popitem(last=False)
        logger.info("[Agent] evicted cached runner %s", evicted_key)

    return runner


def _build_request_runner(
    twin_id: str,
    profile_dict: dict,
    *,
    surface_class: str,
    session_id: str | None,
    user_id: str | None,
    tenant_id: str | None,
    actions: list[dict] | None,
    instruction: str,
    lead_id: str | None = None,
) -> Runner:
    """Build an uncached runner for request-scoped instructions."""
    model_str = os.getenv("ADK_CHAT_MODEL", "gemini-3.5-flash-lite")
    model = LiteLlm(model=model_str) if "/" in model_str else model_str

    tools: list[FunctionTool] = [_make_search_tool(twin_id, surface_class)]
    if surface_class in ("owner", "assistant"):
        # owner = persona-preview chat; assistant = chief-of-staff Home chat.
        # Both improve (capture_knowledge) and can draft follow-ups.
        tools.append(_make_capture_tool(twin_id))
        tools.append(_make_followup_draft_tool(twin_id))
        if surface_class == "assistant":
            # Only the chief-of-staff edits the public persona page.
            tools.append(_make_update_persona_tool(twin_id))
    elif surface_class in ("widget_lead", "public_lead") and lead_id:
        from adk_core.tools.capture_tools import _make_capture_lead_tool
        tools.append(_make_capture_lead_tool(twin_id=twin_id, lead_id=lead_id))
    else:
        tools.append(
            _make_queue_tool(
                twin_id=twin_id,
                conversation_id=session_id or "",
                visitor_user_id=user_id or "",
                tenant_id=tenant_id,
            )
        )

    agent = Agent(
        name=f"persona_{twin_id.replace('-', '_')}_{surface_class}_request",
        model=model,
        instruction=instruction,
        tools=tools,
    )

    return Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=_get_session_service(),
    )


def _build_per_request_instruction(
    profile_dict: dict,
    *,
    surface_class: str,
    actions: list[dict] | None,
    kb_block: str,
    mode_override: str | None,
    include_retry_block: bool = False,
    lead_context: dict | None = None,
    people_block: str = "",
) -> str:
    """Build a request-scoped instruction with optional retrieved context and retry guidance."""
    instruction = generate_system_prompt(
        profile_dict,
        actions=actions,
        surface_class=surface_class,
        lead_context=lead_context,
    )
    if people_block:
        # Per-person meeting memory (Phase 2 — People USP). Injected before the
        # KB block so the persona grounds answers about a named person in real
        # history (open loops, last talked, approved facts).
        instruction += people_block
    if kb_block:
        instruction += kb_block
        instruction += (
            "\n\n[SEARCH ALREADY DONE: The knowledge base was pre-searched for this question. "
            "Do NOT call search_knowledge_base. Respond directly using the RETRIEVED CONTEXT above. "
            "If the context is insufficient for Bucket 1, apply Bucket 2 or Bucket 3 logic as usual.]"
        )
    if mode_override:
        instruction += (
            "\n\n--- ACTIVE MODE OVERRIDE ---\n"
            "The user has activated a special mode. Follow these additional instructions:\n"
            f"{mode_override}\n"
            "--- END MODE OVERRIDE ---"
        )
    if include_retry_block:
        instruction += (
            "\n\n--- TOOL RETRY MODE ---\n"
            "Tool execution is unavailable for this turn.\n"
            "Do not call any tools.\n"
            "Answer directly from the persona profile and any retrieved context above.\n"
            "If the retrieved context is insufficient, answer briefly in character without inventing private facts.\n"
            "You have NOT saved, recorded, or captured anything the visitor just shared (email, phone, name, "
            "or any other detail) - no tool ran. Do not thank them for 'sharing their email/contact info' or "
            "otherwise imply it was recorded. If they just gave you contact details, respond naturally in "
            "character without confirming or acknowledging that it was captured.\n"
            "--- END TOOL RETRY MODE ---"
        )
    return instruction


async def _run_tool_free_retry(
    *,
    twin_id: str,
    profile_dict: dict,
    user_id: str,
    session_id: str,
    safe_message: str,
    surface_class: str,
    actions: list[dict] | None,
    kb_block: str,
    mode_override: str | None,
    agent_timeout: int,
) -> list[str]:
    """Retry a chat turn without tools when the primary ADK pass yields no text."""
    model_str = os.getenv("ADK_CHAT_MODEL", "gemini-3.5-flash-lite")
    model = LiteLlm(model=model_str) if "/" in model_str else model_str
    instruction = _build_per_request_instruction(
        profile_dict,
        surface_class=surface_class,
        actions=actions,
        kb_block=kb_block,
        mode_override=mode_override,
        include_retry_block=True,
    )
    agent = Agent(
        name=f"persona_{twin_id.replace('-', '_')}_{surface_class}_retry",
        model=model,
        instruction=instruction,
        tools=[],
    )
    runner = Runner(
        agent=agent,
        app_name=APP_NAME,
        session_service=_get_session_service(),
    )
    retry_session_id = f"{session_id}:retry"
    session_svc = _get_session_service()
    await _ensure_retry_session(session_svc, user_id=user_id, retry_session_id=retry_session_id)

    return await _stream_agent_text(
        runner,
        user_id=user_id,
        session_id=retry_session_id,
        safe_message=safe_message,
        agent_timeout=agent_timeout,
    )


async def _run_lead_tool_retry(
    *,
    twin_id: str,
    profile_dict: dict,
    user_id: str,
    session_id: str,
    safe_message: str,
    surface_class: str,
    actions: list[dict] | None,
    kb_block: str,
    mode_override: str | None,
    lead_context: dict | None,
    people_block: str,
    lead_id: str,
    tenant_id: str | None,
    agent_timeout: int,
) -> list[str]:
    """Retry a lead-capture turn with capture_lead_contact still available.

    The primary ADK pass sometimes yields an empty final-text event even when a
    function-call round was in flight (a known Gemini/ADK quirk). Falling
    straight to the tools-stripped retry (_run_tool_free_retry) would silently
    abandon the capture attempt and let the model fabricate an "I saved that"
    reply with no tool ever having run. This retry rebuilds the same
    tool-bearing runner on a fresh session so the model gets a genuine second
    chance to actually call capture_lead_contact before we give up.
    """
    instruction = _build_per_request_instruction(
        profile_dict,
        surface_class=surface_class,
        actions=actions,
        kb_block=kb_block,
        mode_override=mode_override,
        lead_context=lead_context,
        people_block=people_block,
    )
    runner = _build_request_runner(
        twin_id,
        profile_dict,
        surface_class=surface_class,
        session_id=session_id,
        user_id=user_id,
        tenant_id=tenant_id,
        actions=actions,
        instruction=instruction,
        lead_id=lead_id,
    )
    retry_session_id = f"{session_id}:retry_tools"
    session_svc = _get_session_service()
    await _ensure_retry_session(session_svc, user_id=user_id, retry_session_id=retry_session_id)

    return await _stream_agent_text(
        runner,
        user_id=user_id,
        session_id=retry_session_id,
        safe_message=safe_message,
        agent_timeout=agent_timeout,
    )


async def _ensure_retry_session(
    session_svc: DatabaseSessionService,
    *,
    user_id: str,
    retry_session_id: str,
) -> None:
    """Get-or-create the retry-scoped ADK session.

    Shared by _run_tool_free_retry and _run_lead_tool_retry - previously
    duplicated inline in both.
    """
    if not await session_svc.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=retry_session_id,
    ):
        await session_svc.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=retry_session_id,
        )


async def _stream_agent_text(
    runner: Runner,
    *,
    user_id: str,
    session_id: str,
    safe_message: str,
    agent_timeout: int,
) -> list[str]:
    """Run one turn against `runner` and collect all yielded text parts.

    Shared by _run_tool_free_retry and _run_lead_tool_retry - previously
    duplicated inline in both.
    """
    chunks: list[str] = []
    user_content = types.Content(
        role="user",
        parts=[types.Part(text=safe_message)],
    )
    async with asyncio.timeout(agent_timeout):
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=user_content,
        ):
            if not event.content or not event.content.parts:
                continue
            for part in event.content.parts:
                if part.text:
                    chunks.append(part.text)
    return chunks


def invalidate_agent(twin_id: str) -> None:
    """Remove cached runners for a twin (both owner and visitor)."""
    for sc in ("owner", "visitor"):
        key = _cache_key(twin_id, sc)
        removed = _runner_cache.pop(key, None)
        if removed:
            logger.info("[Agent] invalidated runner %s", key)


async def chat_stream(
    twin_id: str,
    profile_dict: dict,
    user_id: str,
    session_id: str,
    message: str,
    surface: str = "visitor",
    tenant_id: str | None = None,
    mode_override: str | None = None,
    actions: list[dict] | None = None,
    lead_id: str | None = None,
    lead_context: dict | None = None,
    people_block: str = "",
) -> AsyncGenerator[str, None]:
    """Stream agent response tokens as an async generator of text chunks.

    people_block: optional per-person meeting-memory context (Phase 2). When
    present it is injected into a request-scoped instruction so the persona can
    answer "what do I owe / discuss with X?" from real history. Empty by
    default — all existing callers are unaffected.
    """
    # Sanitize user input to defend against prompt injection / invisible-char abuse.
    # Non-strict mode: warns but doesn't reject — false positives on legitimate
    # user phrasing would be worse than letting suspicious patterns through and
    # relying on the system-prompt to anchor persona behavior.
    try:
        from modules.llm_safety import sanitize_for_llm
        _sanitization = sanitize_for_llm(message, strict_mode=False)
        if _sanitization.warnings:
            logger.warning(
                "[agent_service] llm_safety warnings twin=%s warnings=%s",
                twin_id, _sanitization.warnings[:3],
            )
        message = _sanitization.sanitized_text
    except Exception as _safe_exc:
        logger.warning("[agent_service] llm_safety failed twin=%s error=%r — using raw message", twin_id, _safe_exc)

    # Quota: charge the twin owner for all surfaces (owner, visitor, widget)
    from modules.quota import check_and_increment_messages
    from modules.twin_namespace import get_twin_owner_id
    owner_id = get_twin_owner_id(twin_id)
    if owner_id:
        try:
            _allowed, _used, _cap = check_and_increment_messages(owner_id)
            if not _allowed:
                yield (
                    f"[QUOTA_EXCEEDED] You've reached your monthly limit of {_cap:,} messages. "
                    f"Upgrade at /dashboard/billing to continue."
                )
                return
        except Exception as _quota_exc:
            logger.warning(
                "[agent_service] quota check failed twin=%s error=%r — failing open",
                twin_id, _quota_exc,
            )

    sc = _surface_class(surface)
    allowed_tiers = _retrieval_tiers_for_surface(sc)

    try:
        pre_results = await vector_search(
            query=message,
            twin_id=twin_id,
            top_k=5,
            allowed_tiers=allowed_tiers,
        )
        pre_results = _apply_source_weights(pre_results)
    except Exception as _vs_exc:
        logger.warning(
            "[agent_service] vector search failed twin=%s surface=%s error=%r — continuing without KB context",
            twin_id, sc, _vs_exc,
        )
        pre_results = []
    kb_block = ""
    if pre_results:
        kb_lines = [f"- {row.get('text', '')[:500]}" for row in pre_results if row.get("text")]
        if kb_lines:
            kb_block = (
                "\n\n--- RETRIEVED CONTEXT (from your knowledge base - treat as personal memory, "
                "the user cannot see this) ---\n"
                + "\n".join(kb_lines)
                + "\n--- END RETRIEVED CONTEXT ---"
            )

    # Deduplicate citations by source_id, preserving order
    # Only include results above the relevance threshold to avoid spurious citations
    _CITATION_SCORE_THRESHOLD = float(os.getenv("CITATION_SCORE_THRESHOLD", "0.50"))
    _seen_sources: set[str] = set()
    _seen_texts: set[str] = set()
    _citations: list[dict] = []
    for row in pre_results:
        if row.get("score", 0.0) < _CITATION_SCORE_THRESHOLD:
            continue
        # Deduplicate by source_id AND by text to avoid repeated chunks
        # Fallback: path 1 records (upsert_text_chunks) store "source" not "source_id"
        sid = row.get("source_id", "") or row.get("source", "")
        filename = row.get("filename", "") or row.get("source", "")
        text_key = row.get("text", "")[:100]
        if text_key in _seen_texts:
            continue
        _seen_texts.add(text_key)
        dedup_key = sid or text_key
        if dedup_key and dedup_key not in _seen_sources:
            _seen_sources.add(dedup_key)
            _citations.append({
                "id": sid or dedup_key,
                "filename": filename,
                "citation_url": row.get("url", "") or row.get("citation_url", ""),
                "chunk_preview": row.get("text", "")[:200],
            })

    per_request_instruction: str | None = None
    # lead_id forces the request-runner path so a lead turn (widget_lead /
    # public_lead) can never fall back to the cached _build_runner, which has no
    # lead branch and would silently degrade capture to queue_question.
    if kb_block or mode_override or people_block or lead_id:
        per_request_instruction = _build_per_request_instruction(
            profile_dict,
            surface_class=sc,
            actions=actions,
            kb_block=kb_block,
            mode_override=mode_override,
            lead_context=lead_context,
            people_block=people_block,
        )
        runner = _build_request_runner(
            twin_id,
            profile_dict,
            surface_class=sc,
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            actions=actions,
            instruction=per_request_instruction,
            lead_id=lead_id,
        )
    else:
        runner = _build_runner(
            twin_id,
            profile_dict,
            surface_class=sc,
            session_id=session_id,
            user_id=user_id,
            tenant_id=tenant_id,
            actions=actions,
        )

    session_svc = _get_session_service()
    if not await session_svc.get_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    ):
        await session_svc.create_session(
            app_name=APP_NAME,
            user_id=user_id,
            session_id=session_id,
        )

    try:
        sanitized = sanitize_for_llm(message, strict_mode=False)
        safe_message = sanitized.sanitized_text
    except Exception:
        safe_message = message

    user_content = types.Content(
        role="user",
        parts=[types.Part(text=safe_message)],
    )

    yielded_text = False
    event_count = 0
    agent_timeout = int(os.getenv("ADK_CHAT_TIMEOUT_SECONDS", "120"))
    # Retry budget: each retry (_run_lead_tool_retry, _run_tool_free_retry) gets
    # its own asyncio.timeout window. Giving both a full agent_timeout stacks up
    # to ~3x agent_timeout worst-case (primary + lead retry + tool-free retry)
    # before the client gets any response - enough to exceed upstream proxy /
    # Cloud Run idle timeouts. Halve the budget for retries (floor 15s so a
    # short agent_timeout doesn't starve the retry entirely).
    retry_timeout = max(15, agent_timeout // 2)

    try:
        async with asyncio.timeout(agent_timeout):
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=user_content,
            ):
                event_count += 1
                if not event.content or not event.content.parts:
                    logger.warning("[AGENT] event #%d no content/parts author=%s", event_count, getattr(event, "author", "?"))
                    continue
                for part in event.content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        logger.warning("[AGENT] tool_call name=%s", part.function_call.name)
                    if hasattr(part, "function_response") and part.function_response:
                        response_payload = part.function_response.response
                        result_keys = (
                            list(response_payload.keys())
                            if isinstance(response_payload, dict)
                            else []
                        )
                        logger.warning(
                            "[AGENT] tool_response name=%s result_keys=%s",
                            part.function_response.name,
                            result_keys,
                        )
                    if part.text:
                        yielded_text = True
                        yield part.text
    except asyncio.TimeoutError:
        logger.error("[AGENT] timeout after %ds for twin %s", agent_timeout, twin_id)
        yield "I'm taking too long to respond. Please try again."
        return
    except Exception as exc:
        logger.error("[AGENT] runner error twin=%s events_before_error=%d error=%r", twin_id, event_count, exc, exc_info=True)
        if not yielded_text:
            if sc in ("widget_lead", "public_lead") and lead_id:
                try:
                    from modules.posthog_analytics import ph_capture
                    ph_capture(
                        user_id=f"twin:{twin_id}",
                        event="lead_tool_retry_attempted",
                        properties={"twin_id": twin_id, "lead_id": lead_id},
                    )
                except Exception as _lead_retry_tel_exc:
                    logger.warning(
                        "[AGENT] lead_tool_retry_attempted analytics failed twin=%s lead=%s: %s",
                        twin_id, lead_id, _lead_retry_tel_exc,
                    )
                try:
                    lead_retry_chunks = await _run_lead_tool_retry(
                        twin_id=twin_id,
                        profile_dict=profile_dict,
                        user_id=user_id,
                        session_id=session_id,
                        safe_message=safe_message,
                        surface_class=sc,
                        actions=actions,
                        kb_block=kb_block,
                        mode_override=mode_override,
                        lead_context=lead_context,
                        people_block=people_block,
                        lead_id=lead_id,
                        tenant_id=tenant_id,
                        agent_timeout=retry_timeout,
                    )
                except Exception as lead_retry_exc:
                    logger.error(
                        "[AGENT] lead tool retry error twin=%s lead=%s session=%s error=%r",
                        twin_id, lead_id, session_id, lead_retry_exc, exc_info=True,
                    )
                else:
                    if lead_retry_chunks:
                        logger.warning("[AGENT] lead tool retry succeeded twin=%s chunks=%d", twin_id, len(lead_retry_chunks))
                        for chunk in lead_retry_chunks:
                            yield chunk
                        return
            try:
                retry_chunks = await _run_tool_free_retry(
                    twin_id=twin_id,
                    profile_dict=profile_dict,
                    user_id=user_id,
                    session_id=session_id,
                    safe_message=safe_message,
                    surface_class=sc,
                    actions=actions,
                    kb_block=kb_block,
                    mode_override=mode_override,
                    agent_timeout=retry_timeout,
                )
            except Exception as retry_exc:
                logger.error("[AGENT] retry error twin=%s error=%r", twin_id, retry_exc, exc_info=True)
            else:
                if retry_chunks:
                    logger.warning("[AGENT] retry succeeded twin=%s chunks=%d", twin_id, len(retry_chunks))
                    for chunk in retry_chunks:
                        yield chunk
                    return
        yield "I'm having trouble formulating a response right now. Could you try rephrasing your question?"
        return

    # Emit citations after successful stream
    if _citations and yielded_text:
        yield f"\n[CITATIONS_JSON:{json.dumps(_citations)}]"

    logger.warning("[AGENT] run complete twin=%s events=%d yielded_text=%s", twin_id, event_count, yielded_text)
    if not yielded_text:
        logger.warning("[AGENT] empty response for twin %s - attempting tool-free retry", twin_id)
        if sc in ("widget_lead", "public_lead") and lead_id:
            try:
                from modules.posthog_analytics import ph_capture
                ph_capture(
                    user_id=f"twin:{twin_id}",
                    event="lead_tool_retry_attempted",
                    properties={"twin_id": twin_id, "lead_id": lead_id},
                )
            except Exception as _lead_retry_tel_exc:
                logger.warning(
                    "[AGENT] lead_tool_retry_attempted analytics failed twin=%s lead=%s: %s",
                    twin_id, lead_id, _lead_retry_tel_exc,
                )
            try:
                lead_retry_chunks = await _run_lead_tool_retry(
                    twin_id=twin_id,
                    profile_dict=profile_dict,
                    user_id=user_id,
                    session_id=session_id,
                    safe_message=safe_message,
                    surface_class=sc,
                    actions=actions,
                    kb_block=kb_block,
                    mode_override=mode_override,
                    lead_context=lead_context,
                    people_block=people_block,
                    lead_id=lead_id,
                    tenant_id=tenant_id,
                    agent_timeout=retry_timeout,
                )
            except Exception as lead_retry_exc:
                logger.error(
                    "[AGENT] lead tool retry error twin=%s lead=%s session=%s error=%r",
                    twin_id, lead_id, session_id, lead_retry_exc, exc_info=True,
                )
            else:
                if lead_retry_chunks:
                    logger.warning("[AGENT] lead tool retry succeeded twin=%s chunks=%d", twin_id, len(lead_retry_chunks))
                    for chunk in lead_retry_chunks:
                        yield chunk
                    return
        try:
            retry_chunks = await _run_tool_free_retry(
                twin_id=twin_id,
                profile_dict=profile_dict,
                user_id=user_id,
                session_id=session_id,
                safe_message=safe_message,
                surface_class=sc,
                actions=actions,
                kb_block=kb_block,
                mode_override=mode_override,
                agent_timeout=retry_timeout,
            )
        except Exception as retry_exc:
            logger.error("[AGENT] retry error twin=%s error=%r", twin_id, retry_exc, exc_info=True)
        else:
            if retry_chunks:
                logger.warning("[AGENT] retry succeeded twin=%s chunks=%d", twin_id, len(retry_chunks))
                for chunk in retry_chunks:
                    yield chunk
                return
        yield "I'm having trouble formulating a response right now. Could you try rephrasing your question?"
