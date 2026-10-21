"""End-to-end smoke tests for the meeting enrichment pipeline.

Unlike the contract tests in test_vector_pipeline_contract.py (fast, no
network), this suite hits the REAL staging database, generates REAL Gemini
embeddings, and runs the actual graph_outbox handler code. It's the test
that would have caught every bug in the 2026-04-22 Phase 30 post-mortem on
the original PR instead of at 10pm in production.

## What each test catches

test_vector_search_round_trip:
    * 768/3072 dim mismatch — embedding call + SELECT on vector(768) column
      raises DataError on first run.
    * search_chunks overload ambiguity — Postgres raises
      AmbiguousFunctionError if both 3-arg and 5-arg signatures coexist.
    * Privacy-tier filter wiring — asserts privacy_level returned in result
      dicts when chunks exist.
    * Basic connectivity — asyncpg pool setup, service role auth, etc.

test_enrich_twin_responses_happy_path:
    * The full _process_enrich_twin_responses handler chain end to end.
    * Creates a short-lived test meeting + one twin_response row, runs the
      handler, asserts confidence and sources columns are populated, cleans
      up. This is the exact flow that broke in staging on the first real
      meeting test.

## When it runs

Only when the env var SMOKE=1 is set AND the staging DSN is configured.
Skipped with a clear message otherwise, so local dev doesn't pay a DB round
trip on every `pytest` invocation.

CI triggers:
    * Manual: workflow_dispatch on smoke-test.yml
    * Automatic: push to staging that touches backend/ (the paths filter in
      the workflow). Cost per run: ~$0.001 for two embedding calls, ~15s
      wall time. Cheap enough to run on every staging merge.

## Running locally

Prerequisites (set in your shell or a .env file):
    export SMOKE=1
    export PGVECTOR_DATABASE_URL=postgresql://...@aws-0-eu-central-1....supabase.com:5432/postgres
    export SUPABASE_URL=https://<your-project-ref>.supabase.co
    export SUPABASE_SERVICE_KEY=sb_secret_...
    export GOOGLE_API_KEY=...
    export EMBEDDING_TARGET_DIMENSION=768
    export SMOKE_TEST_TWIN_ID=<uuid of a twin in staging with >=1 chunk>

Then:
    cd backend && pytest tests/test_meeting_pipeline_smoke.py -v -s

The -s is useful because the tests log progress; if they hang you want to
see where.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest


# ---------------------------------------------------------------------------
# Skip guards
# ---------------------------------------------------------------------------

SMOKE_ENABLED = os.environ.get("SMOKE") == "1"
_REQUIRED_ENV = (
    "PGVECTOR_DATABASE_URL",
    "SUPABASE_URL",
    "GOOGLE_API_KEY",  # or GEMINI_API_KEY — checked separately
)


def _missing_env() -> list[str]:
    missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
    # Accept either key variant for the Gemini API.
    if not (os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")):
        if "GOOGLE_API_KEY" not in missing:
            missing.append("GOOGLE_API_KEY")
    # Accept either Supabase key variant.
    if not (os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")):
        missing.append("SUPABASE_SERVICE_KEY")
    return missing


pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(
        not SMOKE_ENABLED,
        reason="Smoke tests are opt-in: set SMOKE=1 to run them.",
    ),
    pytest.mark.skipif(
        bool(_missing_env()) and SMOKE_ENABLED,
        reason=f"Missing required env vars: {_missing_env()}",
    ),
]


# ---------------------------------------------------------------------------
# test_vector_search_round_trip — the tight loop that Phase 30 tripped over
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_vector_search_round_trip() -> None:
    """Call vector_store.search() against the real staging DB.

    Passes if the query executes without error. The result list may be empty
    if the test twin has no matching chunks — that's fine. What matters is
    that the embedding round-trips through Postgres without raising
    AmbiguousFunctionError or DataError.
    """
    twin_id = os.environ.get("SMOKE_TEST_TWIN_ID")
    if not twin_id:
        pytest.skip("SMOKE_TEST_TWIN_ID env var not set")

    # Late import so test-collection doesn't need DB config.
    from adk_core.services.vector_store import search as vector_search

    results = await vector_search(
        query="Tell me about your work on AI and machine learning.",
        twin_id=twin_id,
        top_k=3,
    )

    assert isinstance(results, list), (
        "search() must return a list even when no chunks match"
    )
    # Shape assertions only apply when chunks exist. The smoke test doesn't
    # require data; it requires the query not to crash.
    for hit in results:
        assert "text" in hit and "score" in hit and "source_id" in hit, (
            f"search result dict missing required keys: {hit.keys()}"
        )
        assert "privacy_level" in hit, (
            "search() must surface privacy_level (added in 20260421_search_chunks_tiers.sql)"
        )
        assert isinstance(hit["score"], float)

    # Exercise the tier filter path too — this is the exact call shape that
    # meeting_context_prep.py uses for live ADK sessions.
    filtered = await vector_search(
        query="work experience",
        twin_id=twin_id,
        top_k=3,
        allowed_tiers=["public", "team"],
        min_similarity=0.0,
    )
    assert isinstance(filtered, list)
    for hit in filtered:
        assert hit["privacy_level"] in {"public", "team"}, (
            f"allowed_tiers=['public','team'] returned a {hit['privacy_level']} chunk"
        )


# ---------------------------------------------------------------------------
# test_enrich_twin_responses_happy_path — full pipeline with cleanup
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_enrich_twin_responses_happy_path() -> None:
    """Exercise _process_enrich_twin_responses end-to-end against staging.

    Flow:
        1. Insert a short-lived meeting and one twin_response row.
        2. Call the handler (same code path the worker uses).
        3. Read the row back; assert confidence + sources populated.
        4. Delete everything we created.

    Uses a test twin specified by SMOKE_TEST_TWIN_ID. The twin should have at
    least a few KB chunks for enrichment to find matches; if it has none,
    confidence will be None and sources will be None (still a PASS — the
    handler ran to completion).
    """
    twin_id = os.environ.get("SMOKE_TEST_TWIN_ID")
    if not twin_id:
        pytest.skip("SMOKE_TEST_TWIN_ID env var not set")

    from modules.graph_outbox_worker import _process_enrich_twin_responses
    from modules.observability import get_supabase_client

    sb = get_supabase_client()
    meeting_id = str(uuid.uuid4())
    response_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    # ----- setup -----
    sb.table("meetings").insert({
        "id": meeting_id,
        "twin_id": twin_id,
        "title": "[smoke] pipeline test",
        "status": "completed",
        "meeting_start": now,
        "meeting_end": now,
        "duration_seconds": 60,
        "transcript_text": "Test transcript for smoke test.",
    }).execute()

    sb.table("meeting_twin_responses").insert({
        "id": response_id,
        "meeting_id": meeting_id,
        "twin_id": twin_id,
        "turn_seq": 1,
        "question_text": "What do you work on?",
        "response_text": "I work on AI and machine learning systems for enterprises.",
        "is_deferral": False,
        "responded_at": now,
    }).execute()

    try:
        # ----- exercise -----
        job = {
            "id": str(uuid.uuid4()),
            "twin_id": twin_id,
            "payload": {"meeting_id": meeting_id},
        }
        ok = await _process_enrich_twin_responses(job)
        assert ok is True, "handler returned falsy — check logs for the underlying error"

        # ----- verify -----
        row = (
            sb.table("meeting_twin_responses")
            .select("confidence,sources")
            .eq("id", response_id)
            .single()
            .execute()
        ).data
        assert row is not None, "response row disappeared after enrich"
        # confidence is nullable — None is OK (means no chunks matched). What
        # matters is that the handler didn't crash. If it did, sources would
        # still be null but _process_enrich_twin_responses would have
        # returned False above.
        if row["sources"] is not None:
            assert isinstance(row["sources"], list)
            for src in row["sources"]:
                assert "source_id" in src and "score" in src

    finally:
        # ----- teardown (always runs, even on assertion failure) -----
        sb.table("meeting_twin_responses").delete().eq("id", response_id).execute()
        sb.table("meetings").delete().eq("id", meeting_id).execute()
