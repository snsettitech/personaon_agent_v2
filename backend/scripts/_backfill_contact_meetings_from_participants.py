"""
One-shot backfill: for any existing meeting_participants rows that have
contact_id set (linked by the email path historically), insert the
corresponding contact_meetings row.

Idempotent via the UNIQUE(contact_id, meeting_id) constraint — safe to run
more than once. Best-effort: errors on individual rows are logged and skipped.

Usage:
  cd backend
  .venv/Scripts/python.exe scripts/_backfill_contact_meetings_from_participants.py [--dry-run] [--limit N]

LOCAL DEV ONLY.
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

from modules.observability import get_supabase_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_contact_meetings_from_participants")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill contact_meetings from meeting_participants.contact_id."
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be inserted without writing to DB.")
    parser.add_argument("--limit", type=int, default=1000,
                        help="Max rows to scan from meeting_participants (default 1000).")
    args = parser.parse_args()

    sb = get_supabase_client()
    if sb is None:
        logger.error("Supabase client not available — check SUPABASE_URL / SUPABASE_SERVICE_KEY")
        return 1

    # Fetch meeting_participants rows that have a contact_id set
    resp = (
        sb.table("meeting_participants")
        .select("id, meeting_id, contact_id")
        .not_.is_("contact_id", "null")
        .limit(args.limit)
        .execute()
    )
    participants = getattr(resp, "data", None) or []
    logger.info("Found %d meeting_participants rows with contact_id set", len(participants))

    inserted = skipped = errors = 0

    for row in participants:
        contact_id = row.get("contact_id")
        meeting_id = row.get("meeting_id")
        if not (contact_id and meeting_id):
            skipped += 1
            continue

        # Look up tenant_id + twin_id from contacts
        try:
            c_resp = (
                sb.table("contacts")
                .select("id, tenant_id, twin_id, deleted_at")
                .eq("id", contact_id)
                .maybe_single()
                .execute()
            )
            contact = getattr(c_resp, "data", None)
        except Exception:
            logger.exception("contacts lookup failed contact_id=%s", contact_id)
            errors += 1
            continue

        if not contact:
            logger.info("contact not found contact_id=%s — skipping", contact_id)
            skipped += 1
            continue

        if contact.get("deleted_at"):
            logger.info("contact soft-deleted contact_id=%s — skipping", contact_id)
            skipped += 1
            continue

        tenant_id = contact["tenant_id"]
        twin_id = contact["twin_id"]

        if args.dry_run:
            logger.info(
                "[dry-run] would insert contact_meetings contact=%s meeting=%s tenant=%s",
                contact_id, meeting_id, tenant_id,
            )
            inserted += 1
            continue

        try:
            sb.table("contact_meetings").insert({
                "tenant_id": tenant_id,
                "twin_id": twin_id,
                "contact_id": contact_id,
                "meeting_id": meeting_id,
                "source": "participant",
            }).execute()
            inserted += 1
        except Exception as exc:
            msg = str(exc).lower()
            if "duplicate" in msg or "unique" in msg or "23505" in msg:
                # Already exists — idempotent
                skipped += 1
            else:
                logger.exception(
                    "insert failed contact=%s meeting=%s err=%s",
                    contact_id, meeting_id, type(exc).__name__,
                )
                errors += 1

    logger.info(
        "DONE inserted=%d skipped=%d errors=%d",
        inserted, skipped, errors,
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
