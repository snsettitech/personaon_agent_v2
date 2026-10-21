"""Centralized state key registry for ADK session state.

All state keys used across agents, tools, callbacks, and runtime are defined
here as string constants. This eliminates magic strings and makes typos into
import errors.

ADK state prefixes:
  session: — identity/routing data, persisted in adk_sessions
  app:     — application constants/artifacts, injectible via templates
  temp:    — transient per-turn data, persisted for template injection
"""

from __future__ import annotations


class SessionKey:
    """Keys scoped to the current session/request identity."""

    TENANT_ID = "session:tenant_id"
    USER_ID = "session:user_id"
    TWIN_ID = "session:twin_id"
    RUN_ID = "session:run_id"
    CONVERSATION_ID = "session:conversation_id"
    SURFACE = "session:surface"
    CLIENT_CONTEXT_JSON = "session:client_context_json"
    RESEARCH_ARTIFACT_JSON = "session:research_artifact_json"


class AppKey:
    """Keys for application-level constants and artifacts."""

    PERSONA_ARTIFACT_JSON = "app:persona_artifact_json"
    PERSONA_PROMPT_BLOCK = "app:persona_prompt_block"
    PERSONA_VERSION = "app:persona_version"
    QUOTE_PACK_JSON = "app:quote_pack_json"
    GROUNDING_LEVEL = "app:grounding_level"
    SUBJECT_NAME = "app:subject_name"
    RESEARCH_LOCATION = "app:research_location"
    RESEARCH_COMPANY = "app:research_company"
    RESEARCH_WEBSITE = "app:research_website"
    LINKEDIN_ANCHOR = "app:linkedin_anchor"
    SEED_URLS_JSON = "app:seed_urls_json"
    PERSONA_SEED_JSON = "app:persona_seed_json"
    PRELOADED_SOURCES_JSON = "app:preloaded_sources_json"


class TempKey:
    """Keys for transient per-turn data."""

    FACT_CONTEXT_JSON = "temp:fact_context_json"
    QUOTE_CONTEXT_JSON = "temp:quote_context_json"
    RECENT_CONVERSATION_JSON = "temp:recent_conversation_json"
    FACT_CITATIONS_JSON = "temp:fact_citations_json"
    QUOTE_CITATIONS_JSON = "temp:quote_citations_json"
    ACTIVE_CITATIONS_JSON = "temp:active_citations_json"
    MERGED_CITATIONS_JSON = "temp:merged_citations_json"
    COORDINATOR_BRIEF = "temp:coordinator_brief"
    SEARCH_RESULTS_JSON = "temp:search_results_json"
    SCRAPED_SOURCES_JSON = "temp:scraped_sources_json"
    RESEARCH_WARNINGS_JSON = "temp:research_warnings_json"


# Tuple of all citation state keys (used for batch operations)
CITATION_STATE_KEYS = (
    TempKey.FACT_CITATIONS_JSON,
    TempKey.QUOTE_CITATIONS_JSON,
    TempKey.ACTIVE_CITATIONS_JSON,
    TempKey.MERGED_CITATIONS_JSON,
)
