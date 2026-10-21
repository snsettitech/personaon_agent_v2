"""Runtime kill-switch env flags (execution-board 0.10 / PRD NFR-3).

These gate the three highest-blast-radius entrypoints — public chat, agent
page-edits, and new-account creation — so an on-call engineer can pause any of
them by flipping an env var on the Cloud Run service, without rebuilding or
redeploying the container image.

CRITICAL: every check here reads `os.getenv(...)` fresh on every call. Do NOT
memoize these into module-level constants (unlike e.g.
`graph_memory_config.SINGLE_PROFILE_SCOPE_ENABLED`, which is a build-time
rollout flag, not an incident-response kill switch) — a cached value would
mean flipping the env var in Cloud Run does nothing until the next cold start,
defeating the entire point of a runtime kill switch.

All three default to enabled (unset -> True) so they are opt-out, not opt-in.

PRECONDITION — Cloud Run traffic must be routed to LATEST, not pinned by
revision name. `gcloud run services update --update-env-vars=...` creates a
NEW revision but does not, by itself, move any live traffic onto it: if the
service's traffic is pinned to a specific revision (e.g. left over from a
`--no-traffic` canary test), 100% of real requests keep hitting the OLD
revision and the env var has zero effect until traffic is repointed. Before
relying on one of these flags in an incident, verify:

    gcloud run services describe personaon-api-v2 --region=us-central1 \
        --format='value(status.traffic)'

If it shows a pinned revision name instead of `LATEST=100`, restore it first:

    gcloud run services update-traffic personaon-api-v2 --region=us-central1 \
        --to-latest

The staging deploy workflow (`.github/workflows/deploy-backend-staging.yml`)
runs `update-traffic --to-latest` after every deploy so this should self-heal
on the next push to `staging`, but don't assume that has already happened
mid-incident — check first.
"""

from __future__ import annotations

import os


def public_chat_enabled() -> bool:
    """PUBLIC_CHAT_ENABLED — gates the public/widget chat endpoints in
    routers/chat.py. When false, those endpoints return a graceful "resting"
    message instead of streaming a response (never a 503/error)."""
    return os.getenv("PUBLIC_CHAT_ENABLED", "true").lower() == "true"


def agent_edits_enabled() -> bool:
    """AGENT_EDITS_ENABLED — gates owner-chat agent tools that mutate the
    persona's live public page (currently: update_persona in
    adk_core/tools/persona_edit_tools.py). When false, the tool declines
    in-character instead of writing or raising.

    Sprint 1 / ADR-001: keep **false** in production until factual edits
    create *proposed* claims instead of writing settings.public_profile
    directly. Set the Cloud Run env explicitly.
    """
    return os.getenv("AGENT_EDITS_ENABLED", "true").lower() == "true"


def signups_enabled() -> bool:
    """SIGNUPS_ENABLED — gates new-account creation: the auto-create twin
    entrypoint (routers/auto_create.py) and the first-login user-provisioning
    branch of /auth/sync-user (routers/auth.py). Does NOT gate login/sync for
    users who already have an account — only new-account creation is paused."""
    return os.getenv("SIGNUPS_ENABLED", "true").lower() == "true"
