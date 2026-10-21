"""
One-shot backfill: extract people from existing completed meetings' recaps and
upsert them as no-email contacts on the People surface.

Usage:
  cd backend
  .venv/Scripts/python.exe scripts/_backfill_recap_people.py [--dry-run] [--limit N]

LOCAL DEV ONLY. Skips meetings missing both recap_extras_json and summary_json.
Idempotent — safe to run more than once.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env", override=False)
load_dotenv(_ROOT / "backend" / ".env", override=False)
load_dotenv(_ROOT / "backend" / ".env.local", override=True)

sys.path.insert(0, str(_ROOT / "backend"))

from modules.observability import get_supabase_client  # noqa: E402
from services.meeting_people_extractor import extract_people_from_recap  # noqa: E402
from services.contact_resolver import upsert_name_only_contacts  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_recap_people")


async def amain() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill recap-people into no-email contacts."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be upserted without writing to DB.")
    parser.add_argument("--limit", type=int, default=200,
                        help="Max number of completed meetings to scan (default 200).")
    args = parser.parse_args()

    sb = get_supabase_client()
    if sb is None:
        logger.error("Supabase client not available — check SUPABASE_URL / SUPABASE_SERVICE_KEY")
        return 1

    resp = (
        sb.table("meetings")
        .select("id, tenant_id, twin_id, title, meeting_start, recap_extras_json, summary_json")
        .eq("status", "completed")
        .limit(args.limit)
        .execute()
    )
    meetings = getattr(resp, "data", None) or []
    logger.info("Scanned %d completed meetings", len(meetings))

    scanned = upserted = skipped_no_recap = skipped_no_twin = errors = 0

    for m in meetings:
        scanned += 1
        meeting_id = m["id"]
        tenant_id = m["tenant_id"]
        twin_id = m.get("twin_id")
        extras = m.get("recap_extras_json")
        summary = m.get("summary_json")

        if not (extras or summary):
            skipped_no_recap += 1
            continue

        # Resolve twin if missing (desktop_sdk recordings)
        if not twin_id:
            try:
                t_resp = (
                    sb.table("twins")
                    .select("id")
                    .eq("tenant_id", tenant_id)
                    .eq("status", "active")
                    .order("created_at")
                    .limit(1)
                    .execute()
                )
                twin_id = (getattr(t_resp, "data", None) or [{}])[0].get("id")
            except Exception:
                twin_id = None
        if not twin_id:
            skipped_no_twin += 1
            continue

        # Resolve owner display name from public.users (full_name, email).
        owner_name = ""
        try:
            u = (
                sb.table("users")
                .select("full_name, email")
                .eq("tenant_id", tenant_id)
                .limit(1)
                .execute()
            )
            row = (getattr(u, "data", None) or [{}])[0] or {}
            owner_name = (row.get("full_name") or "").strip()
            if not owner_name and row.get("email"):
                owner_name = row["email"].split("@")[0]
        except Exception:
            owner_name = ""

        people = await extract_people_from_recap(
            title=m.get("title"),
            owner_name=owner_name or "the owner",
            recap_extras=extras,
            summary_json=summary,
        )
        if not people:
            continue

        if args.dry_run:
            logger.info(
                "[dry-run] meeting=%s would upsert %d people: %s",
                meeting_id, len(people), [p["name"] for p in people],
            )
            upserted += len(people)
            continue

        try:
            counts = upsert_name_only_contacts(
                tenant_id=tenant_id,
                twin_id=twin_id,
                people=people,
                meeting_id=m["id"],
                meeting_started_iso=m.get("meeting_start"),
            )
            upserted += counts["created"] + counts["updated"]
            logger.info(
                "meeting=%s created=%d updated=%d skipped=%d names=%s",
                meeting_id,
                counts["created"],
                counts["updated"],
                counts["skipped"],
                [p["name"] for p in people],
            )
        except Exception:
            logger.exception("upsert failed meeting=%s", meeting_id)
            errors += 1

    logger.info(
        "DONE scanned=%d upserted_total=%d no_recap=%d no_twin=%d errors=%d",
        scanned, upserted, skipped_no_recap, skipped_no_twin, errors,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(amain()))
