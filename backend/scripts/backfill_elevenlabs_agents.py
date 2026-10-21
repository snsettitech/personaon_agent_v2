"""Backfill ElevenLabs Conversational AI agents for existing twins with voice_id.

Run from backend/:
    python scripts/backfill_elevenlabs_agents.py [--dry-run]

Reads env vars:
    ELEVENLABS_API_KEY        — ElevenLabs API key
    ELEVENLABS_WEBHOOK_SECRET — Webhook secret passed in X-PersonaOn-Token header
    SUPABASE_URL              — Supabase project URL
    SUPABASE_SERVICE_KEY      — Supabase service role key (admin access)
    API_URL                   — PersonaOn backend URL (defaults to production)

What it does:
    1. Queries all twins that have settings.voice_id set
    2. Filters in Python: only those without settings.elevenlabs_agent_id
    3. For each, POSTs to ElevenLabs /v1/convai/agents/create with voice baked in
    4. On success, PATCHes the twin's settings.elevenlabs_agent_id in Supabase
    5. Sleeps 0.5s between creates to avoid rate limits

Use --dry-run to see what would happen without making any API calls.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import httpx
from supabase import create_client

logger = logging.getLogger(__name__)

_ELEVENLABS_API_BASE = "https://api.elevenlabs.io"
_DEFAULT_API_URL = "http://localhost:8000"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill ElevenLabs agents for twins with voice_id but no elevenlabs_agent_id.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would happen without calling ElevenLabs or updating Supabase.",
    )
    return parser.parse_args()


def _load_env() -> dict[str, str]:
    """Load and validate required environment variables."""
    api_key = os.getenv("ELEVENLABS_API_KEY", "")
    webhook_secret = os.getenv("ELEVENLABS_WEBHOOK_SECRET", "")
    supabase_url = os.getenv("SUPABASE_URL", "")
    supabase_service_key = os.getenv("SUPABASE_SERVICE_KEY", "")
    api_url = os.getenv("API_URL", _DEFAULT_API_URL)

    missing = []
    if not api_key:
        missing.append("ELEVENLABS_API_KEY")
    if not supabase_url:
        missing.append("SUPABASE_URL")
    if not supabase_service_key:
        missing.append("SUPABASE_SERVICE_KEY")

    if missing:
        logger.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)

    if not webhook_secret:
        logger.warning("ELEVENLABS_WEBHOOK_SECRET not set — agents will have empty token header")

    return {
        "api_key": api_key,
        "webhook_secret": webhook_secret,
        "supabase_url": supabase_url,
        "supabase_service_key": supabase_service_key,
        "api_url": api_url,
    }


def _fetch_twins_needing_agents(supabase_url: str, supabase_service_key: str) -> list[dict]:
    """Query Supabase for twins with voice_id but no elevenlabs_agent_id.

    Fetches all twins where settings->>'voice_id' IS NOT NULL, then filters
    in Python for those missing settings.elevenlabs_agent_id.
    """
    sb = create_client(supabase_url, supabase_service_key)

    logger.info("[Backfill] querying twins with voice_id set...")
    resp = (
        sb.table("twins")
        .select("id, name, settings")
        .not_.is_("settings->>voice_id", "null")
        .execute()
    )

    all_twins = resp.data or []
    logger.info("[Backfill] found %d twins with voice_id", len(all_twins))

    # Filter in Python: only those missing elevenlabs_agent_id
    needs_agent = [
        twin
        for twin in all_twins
        if not (twin.get("settings") or {}).get("elevenlabs_agent_id")
    ]
    logger.info("[Backfill] %d twins need ElevenLabs agent creation", len(needs_agent))
    return needs_agent


def _build_agent_payload(twin_name: str, voice_id: str, api_url: str, webhook_secret: str) -> dict:
    """Build the ElevenLabs agent creation payload.

    Matches exactly what _create_elevenlabs_agent() in backend/routers/voice.py sends.
    """
    return {
        "name": f"PersonaOn - {twin_name}",
        "conversation_config": {
            "agent": {
                "prompt": {
                    "prompt": (
                        "You are a PersonaOn digital twin. Respond naturally "
                        "and conversationally. Keep responses concise - 1-3 "
                        "sentences for voice. Do not use markdown or bullet points."
                    ),
                    "llm": "custom-llm",
                    "custom_llm": {
                        "url": f"{api_url}/v1/chat/completions",
                        "request_headers": {
                            "X-PersonaOn-Token": webhook_secret,
                        },
                        "api_type": "chat_completions",
                    },
                },
                "language": "en",
            },
            "tts": {
                "model_id": "eleven_turbo_v2",
                "voice_id": voice_id,
            },
            "asr": {
                "quality": "high",
                "user_input_audio_format": "pcm_16000",
            },
            "turn": {
                "turn_timeout": 7,
                "mode": "turn",
            },
        },
    }


def _create_agent(
    twin_id: str,
    twin_name: str,
    voice_id: str,
    api_key: str,
    api_url: str,
    webhook_secret: str,
) -> str | None:
    """POST to ElevenLabs to create a Conversational AI agent.

    Returns agent_id on success, None on failure (non-fatal — caller logs and continues).
    Uses httpx sync client since this is a one-off admin script.
    """
    payload = _build_agent_payload(twin_name, voice_id, api_url, webhook_secret)
    logger.info(
        "[Backfill] creating agent for twin_id=%s name=%r voice_id=%s",
        twin_id,
        twin_name,
        voice_id,
    )
    try:
        resp = httpx.post(
            f"{_ELEVENLABS_API_BASE}/v1/convai/agents/create",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=15.0,
        )
        if resp.status_code == 200:
            agent_id = resp.json().get("agent_id")
            logger.info(
                "[Backfill] created agent_id=%s for twin_id=%s",
                agent_id,
                twin_id,
            )
            return agent_id
        logger.warning(
            "[Backfill] agent create failed twin_id=%s status=%d body=%s",
            twin_id,
            resp.status_code,
            resp.text[:300],
        )
        return None
    except Exception as exc:
        logger.warning("[Backfill] agent create error twin_id=%s: %s", twin_id, exc)
        return None


def _update_twin_agent_id(
    twin_id: str,
    settings: dict,
    agent_id: str,
    supabase_url: str,
    supabase_service_key: str,
) -> bool:
    """PATCH the twin's settings to include the new elevenlabs_agent_id.

    Merges the new agent_id into the existing settings dict to preserve
    all other fields (voice_id, voice_name, etc.).
    Returns True on success, False on failure.
    """
    updated_settings = {**settings, "elevenlabs_agent_id": agent_id}
    try:
        sb = create_client(supabase_url, supabase_service_key)
        sb.table("twins").update({"settings": updated_settings}).eq("id", twin_id).execute()
        logger.info(
            "[Backfill] updated settings.elevenlabs_agent_id=%s for twin_id=%s",
            agent_id,
            twin_id,
        )
        return True
    except Exception as exc:
        logger.warning(
            "[Backfill] failed to update settings for twin_id=%s: %s",
            twin_id,
            exc,
        )
        return False


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    )

    args = _parse_args()
    env = _load_env()

    if args.dry_run:
        logger.info("[Backfill] DRY RUN — no ElevenLabs calls or Supabase writes will be made")

    twins = _fetch_twins_needing_agents(env["supabase_url"], env["supabase_service_key"])

    total = len(twins)
    backfilled = 0
    failed = 0

    for i, twin in enumerate(twins):
        twin_id = twin["id"]
        twin_name = twin.get("name") or "Persona"
        settings = twin.get("settings") or {}
        voice_id: str = settings.get("voice_id", "")

        if not voice_id:
            logger.warning("[Backfill] twin_id=%s has no voice_id in settings, skipping", twin_id)
            continue

        logger.info(
            "[Backfill] processing %d/%d: twin_id=%s name=%r voice_id=%s",
            i + 1,
            total,
            twin_id,
            twin_name,
            voice_id,
        )

        if args.dry_run:
            logger.info(
                "[Backfill] DRY RUN would create agent: name='PersonaOn - %s' voice_id=%s",
                twin_name,
                voice_id,
            )
            backfilled += 1
        else:
            agent_id = _create_agent(
                twin_id=twin_id,
                twin_name=twin_name,
                voice_id=voice_id,
                api_key=env["api_key"],
                api_url=env["api_url"],
                webhook_secret=env["webhook_secret"],
            )
            if agent_id:
                success = _update_twin_agent_id(
                    twin_id=twin_id,
                    settings=settings,
                    agent_id=agent_id,
                    supabase_url=env["supabase_url"],
                    supabase_service_key=env["supabase_service_key"],
                )
                if success:
                    backfilled += 1
                else:
                    failed += 1
            else:
                failed += 1

            # Rate limit: 0.5s between creates
            if i < total - 1:
                time.sleep(0.5)

    dry_prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{dry_prefix}Backfilled {backfilled}/{total} twins with ElevenLabs agents.")
    if failed:
        print(f"Failed: {failed} twin(s) — check logs above for details.")


if __name__ == "__main__":
    main()
