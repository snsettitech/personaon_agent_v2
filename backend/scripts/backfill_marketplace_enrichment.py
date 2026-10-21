#!/usr/bin/env python3
"""Backfill marketplace enrichment for all existing compiled personas.

Reads active persona artifacts from adk_persona_artifacts, parses them,
and runs the post-compile enrichment pipeline (claims → topics → scores)
to populate person_claims, person_topic_profiles, and person_answerability_scores.

Usage:
    cd backend
    python scripts/backfill_marketplace_enrichment.py [--dry-run] [--twin-id UUID]

Options:
    --dry-run     Show what would be enriched without writing to DB
    --twin-id     Enrich a single twin (for testing)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

# Ensure backend root is on sys.path
backend_root = str(Path(__file__).resolve().parent.parent)
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from adk_core.schemas.artifacts import PersonaArtifact, ResearchArtifact
from adk_core.tools.enrichment_tools import post_compile_enrichment

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _get_supabase():
    from modules.observability import supabase
    return supabase


def _fetch_active_artifacts(twin_id: str | None = None):
    """Fetch all active persona artifacts (or one specific twin)."""
    supabase = _get_supabase()
    query = (
        supabase.table("adk_persona_artifacts")
        .select("twin_id, artifact_json")
        .eq("status", "active")
        .order("created_at", desc=True)
    )
    if twin_id:
        query = query.eq("twin_id", twin_id)
    result = query.execute()
    return result.data or []


def _fetch_research_artifact_for_twin(twin_id: str):
    """Try to find the most recent research artifact for a twin via research runs."""
    supabase = _get_supabase()
    # Research runs link twin_id to run_id; artifacts link run_id to artifact_json
    try:
        runs = (
            supabase.table("adk_research_runs")
            .select("id")
            .eq("twin_id", twin_id)
            .eq("status", "completed")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        if not runs.data:
            return None
        run_id = runs.data[0]["id"]
        artifact_row = (
            supabase.table("adk_research_artifacts")
            .select("artifact_json")
            .eq("run_id", run_id)
            .maybe_single()
            .execute()
        )
        if artifact_row and artifact_row.data:
            return artifact_row.data.get("artifact_json")
    except Exception as exc:
        logger.warning("Could not fetch research artifact for twin %s: %s", twin_id, exc)
    return None


def _build_minimal_research_artifact(persona_artifact: PersonaArtifact) -> ResearchArtifact:
    """Build a minimal ResearchArtifact from PersonaArtifact data for scoring.

    When the original research artifact isn't available, we reconstruct
    enough to compute answerability scores from the persona's provenance.
    """
    source_count = (persona_artifact.provenance or {}).get("source_count", 0)
    # Create placeholder sources so coverage formula works
    fake_sources = [
        {"source_id": f"backfill-{i}", "url": "", "title": f"Source {i}"}
        for i in range(int(source_count or 0))
    ]
    return ResearchArtifact(
        source_registry=fake_sources,
        extracted_claims=persona_artifact.claims,
        synthesis_summary=(persona_artifact.provenance or {}).get("research_summary", ""),
    )


async def backfill(twin_id: str | None = None, dry_run: bool = False):
    """Run enrichment on all (or one) compiled persona artifacts."""
    rows = _fetch_active_artifacts(twin_id)

    # Deduplicate by twin_id (keep first = most recent)
    seen_twins: set[str] = set()
    unique_rows = []
    for row in rows:
        tid = row.get("twin_id")
        if tid and tid not in seen_twins:
            seen_twins.add(tid)
            unique_rows.append(row)

    logger.info("Found %d active persona artifact(s) to enrich", len(unique_rows))

    if not unique_rows:
        logger.info("Nothing to enrich")
        return

    success = 0
    failed = 0

    for row in unique_rows:
        tid = row["twin_id"]
        artifact_json = row.get("artifact_json")
        if not artifact_json or not isinstance(artifact_json, dict):
            logger.warning("Skipping twin %s: no artifact_json", tid)
            failed += 1
            continue

        try:
            artifact = PersonaArtifact.model_validate(artifact_json)
        except Exception as exc:
            logger.warning("Skipping twin %s: invalid artifact: %s", tid, exc)
            failed += 1
            continue

        claim_count = len(artifact.claims)
        expertise_count = len(
            artifact.identity_frame.get("expertise_topics", [])
            if isinstance(artifact.identity_frame, dict) else []
        )

        if dry_run:
            logger.info(
                "[DRY RUN] Would enrich twin %s: %d claims, %d expertise topics, subject=%s",
                tid, claim_count, expertise_count, artifact.subject_name,
            )
            success += 1
            continue

        # Try to get the real research artifact; fall back to minimal reconstruction
        research_json = _fetch_research_artifact_for_twin(tid)
        if research_json and isinstance(research_json, dict):
            try:
                research_artifact = ResearchArtifact.model_validate(research_json)
            except Exception as parse_exc:
                logger.warning("Failed to parse research artifact for twin %s, using minimal fallback: %s", tid, parse_exc)
                research_artifact = _build_minimal_research_artifact(artifact)
        else:
            research_artifact = _build_minimal_research_artifact(artifact)

        try:
            result = await post_compile_enrichment(
                twin_id=tid,
                artifact=artifact,
                research_artifact=research_artifact,
            )
            claims_ok = result.get("claims", {}).get("status") == "success"
            topics_ok = result.get("topics", {}).get("status") == "success"
            scores_ok = result.get("answerability", {}).get("status") == "success"

            logger.info(
                "Enriched twin %s (%s): claims=%s topics=%s scores=%s",
                tid,
                artifact.subject_name,
                result.get("claims", {}).get("claims_persisted", "?"),
                result.get("topics", {}).get("topics_extracted", "?"),
                result.get("answerability", {}).get("global_score", "?"),
            )
            if claims_ok and topics_ok and scores_ok:
                success += 1
            else:
                failed += 1
        except Exception as exc:
            logger.error("Failed to enrich twin %s: %s", tid, exc)
            failed += 1

    logger.info("Done: %d success, %d failed out of %d total", success, failed, len(unique_rows))


def main():
    parser = argparse.ArgumentParser(description="Backfill marketplace enrichment")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be enriched")
    parser.add_argument("--twin-id", type=str, help="Enrich a single twin")
    args = parser.parse_args()

    asyncio.run(backfill(twin_id=args.twin_id, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
