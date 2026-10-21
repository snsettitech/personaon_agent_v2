"""ADK lifecycle callbacks for grounding enforcement and citation logging."""

from __future__ import annotations

import json
import logging

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmRequest, LlmResponse
from google.genai import types

from adk_core.state_helpers import json_list, merge_citations
from adk_core.state_keys import AppKey, SessionKey, TempKey

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# before_model_callback — Grounding Gate
# ---------------------------------------------------------------------------

def grounding_gate(
    callback_context: CallbackContext,
    llm_request: LlmRequest,
) -> LlmResponse | None:
    """Enforce grounding policy *before* the LLM generates a response."""
    state = callback_context.state
    grounding_level = str(state.get(AppKey.GROUNDING_LEVEL, "moderate")).lower()
    surface = str(state.get(SessionKey.SURFACE, "owner")).lower()
    fact_context = str(state.get(TempKey.FACT_CONTEXT_JSON, "[]")).strip()
    quote_context = str(state.get(TempKey.QUOTE_CONTEXT_JSON, "[]")).strip()

    has_retrieval = fact_context not in ("[]", "", "null") or quote_context not in ("[]", "", "null")

    # Strict grounding + no retrieval -> block generation entirely
    if grounding_level == "strict" and not has_retrieval:
        logger.info("grounding_gate: blocking — strict grounding with no retrieval context")
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[types.Part(text=(
                    "I don't have enough grounded information to answer that question. "
                    "Could you ask something related to my documented expertise?"
                ))],
            ),
        )

    # Public/widget surfaces under strict or moderate grounding: inject reminder
    if surface in ("public", "widget") and grounding_level in ("strict", "moderate"):
        grounding_reminder = (
            "\n\n[SYSTEM: You MUST ground every factual claim in the retrieved knowledge. "
            "Do not speculate or hallucinate. If unsure, say so honestly.]\n"
        )
        if llm_request.config and llm_request.config.system_instruction:
            existing = llm_request.config.system_instruction
            if isinstance(existing, str):
                llm_request.config.system_instruction = existing + grounding_reminder
            elif isinstance(existing, types.Content) and getattr(existing, "parts", None):
                existing.parts.append(types.Part(text=grounding_reminder))
        else:
            logger.warning(
                "grounding_gate: cannot inject grounding reminder — no system_instruction present "
                "(surface=%s grounding=%s)",
                surface,
                grounding_level,
            )

    return None  # Allow LLM call to proceed


# ---------------------------------------------------------------------------
# before_agent_callback — Persona Enforcement Gate
# ---------------------------------------------------------------------------

def persona_enforcement_gate(
    callback_context: CallbackContext,
) -> types.Content | None:
    """Validate that persona state is loaded before the responder runs."""
    persona_prompt = str(callback_context.state.get(AppKey.PERSONA_PROMPT_BLOCK, "")).strip()

    if not persona_prompt or persona_prompt in ("{}", "null"):
        logger.warning("persona_enforcement_gate: persona_prompt_block missing — blocking responder")
        return types.Content(
            role="model",
            parts=[types.Part(text=(
                "I'm still loading my persona context. Please try again in a moment."
            ))],
        )

    return None  # Allow agent to proceed


# ---------------------------------------------------------------------------
# after_agent_callback — Citation Merger & Logger
# ---------------------------------------------------------------------------

def citation_and_logging_callback(
    callback_context: CallbackContext,
) -> types.Content | None:
    """Merge citations from retrieval tools and log metrics after response generation."""
    state = callback_context.state
    fact_citations = json_list(state.get(TempKey.FACT_CITATIONS_JSON))
    quote_citations = json_list(state.get(TempKey.QUOTE_CITATIONS_JSON))
    merged = merge_citations(fact_citations, quote_citations)

    state[TempKey.MERGED_CITATIONS_JSON] = json.dumps(merged)

    # Log metrics
    twin_id = state.get(SessionKey.TWIN_ID, "unknown")
    surface = state.get(SessionKey.SURFACE, "unknown")
    grounding_level = state.get(AppKey.GROUNDING_LEVEL, "moderate")
    logger.info(
        "citation_callback: twin=%s surface=%s grounding=%s citations=%d (fact=%d quote=%d)",
        twin_id,
        surface,
        grounding_level,
        len(merged),
        len(fact_citations),
        len(quote_citations),
    )

    return None  # Don't override the response
