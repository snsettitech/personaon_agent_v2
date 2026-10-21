"""
One-shot backfill: enqueue link_meeting_contacts for completed meetings whose
participants haven't been linked to contacts yet.

Usage:
  cd backend
  .venv/Scripts/python.exe scripts/_backfill_link_meeting_contacts.py [--dry-run] [--limit N]

Reads .env / .env.local just like the backend (backfill_canonical_persona_profiles pattern).
Safe to run multiple times — already-linked participants are skipped at enqueue time,
and the contact_resolver itself is idempotent (BUG-1 fix guards against double-counting).
LOCAL DEV ONLY (production backfill should be a controlled migration).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env", override=False)
load_dotenv(_ROOT / "backend" / ".env", override=False)
load_dotenv(_ROOT / "backend" / ".env.local", override=True)

sys.path.insert(0, str(_ROOT / "backend"))

from modules.graph_outbox import GraphOperationType, get_graph_outbox  # noqa: E402
from modules.observability import supabase  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_link_meeting_contacts")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enqueue link_meeting_contacts jobs for completed meetings with unlinked participants."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be enqueued without actually enqueuing.",
    )
    parser.add_argument(
        "--limit", type=int, default=500,
        help="Max number of completed meetings to scan (default: 500).",
    )
    args = parser.parse_args()

    if supabase is None:
        logger.error("Supabase client not available — check SUPABASE_URL / SUPABASE_KEY env vars.")
        return 1

    # 1. Fetch completed meetings with twin_id
    try:
        resp = (
            supabase.table("meetings")
            .select("id, tenant_id, twin_id")
            .eq("status", "completed")
            .not_.is_("twin_id", "null")
            .limit(args.limit)
            .execute()
        )
        meetings = getattr(resp, "data", None) or []
    except Exception as exc:
        logger.error("Failed to fetch completed meetings: %s", exc)
        return 1

    logger.info("Scanned %d completed meetings (limit=%d)", len(meetings), args.limit)

    enqueued = 0
    skipped_no_participants = 0
    skipped_already_linked = 0
    enqueue_errors = 0

    outbox = get_graph_outbox()

    for m in meetings:
        meeting_id = m.get("id")
        tenant_id = m.get("tenant_id")
        twin_id = m.get("twin_id")
        if not (meeting_id and tenant_id and twin_id):
            logger.debug("Skip meeting=%s: missing tenant_id or twin_id", meeting_id)
            continue

        # Fetch participants with email to check whether any are unlinked
        try:
            p_resp = (
                supabase.table("meeting_participants")
                .select("id, participant_email, contact_id")
                .eq("meeting_id", meeting_id)
                .execute()
            )
            participants = getattr(p_resp, "data", None) or []
        except Exception as exc:
            logger.warning(
                "Skip meeting=%s: participants fetch failed (%s)", meeting_id, type(exc).__name__
            )
            continue

        emailed = [p for p in participants if (p.get("participant_email") or "").strip()]
        if not emailed:
            skipped_no_participants += 1
            continue

        unlinked = [p for p in emailed if not p.get("contact_id")]
        if not unlinked:
            skipped_already_linked += 1
            continue

        if args.dry_run:
            logger.info(
                "[dry-run] would enqueue meeting=%s unlinked_participants=%d",
                meeting_id, len(unlinked),
            )
            enqueued += 1
            continue

        try:
            outbox.submit(
                tenant_id=tenant_id,
                twin_id=twin_id,
                operation=GraphOperationType.LINK_MEETING_CONTACTS,
                idempotency_key=f"link_meeting_contacts:{meeting_id}",
                payload={
                    "meeting_id": meeting_id,
                    "tenant_id": tenant_id,
                    "twin_id": twin_id,
                },
            )
            logger.info("Enqueued meeting=%s unlinked_participants=%d", meeting_id, len(unlinked))
            enqueued += 1
        except Exception as exc:
            logger.warning("Enqueue failed meeting=%s err=%s", meeting_id, type(exc).__name__)
            enqueue_errors += 1

    logger.info(
        "DONE — scanned=%d enqueued=%d skipped_no_participants=%d "
        "skipped_already_linked=%d errors=%d%s",
        len(meetings),
        enqueued,
        skipped_no_participants,
        skipped_already_linked,
        enqueue_errors,
        " (dry-run)" if args.dry_run else "",
    )
    return 0 if enqueue_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
