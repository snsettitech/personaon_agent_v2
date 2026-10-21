"""Walk existing meetings and UPSERT commitments from recap_extras_json.

Usage:
  cd backend
  .venv/Scripts/python.exe scripts/backfill_commitments.py [--dry-run] [--limit N]

Idempotent: uses UPSERT on (meeting_id, content_hash, source) so re-running
is safe and preserves user-set done/dismissed status.
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

from modules.observability import supabase  # noqa: E402
from services.commitment_extractor import structured_commitments_from_extras  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_commitments")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="UPSERT meeting_commitments rows from existing recap_extras_json."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be written without actually writing.",
    )
    parser.add_argument(
        "--limit", type=int, default=1000,
        help="Max number of meetings to scan (default: 1000).",
    )
    args = parser.parse_args()

    if supabase is None:
        logger.error("Supabase client not available — check SUPABASE_URL / SUPABASE_KEY env vars.")
        return 1

    try:
        rows = (
            supabase.table("meetings")
            .select("id, tenant_id, twin_id, recap_extras_json")
            .not_.is_("recap_extras_json", "null")
            .limit(args.limit)
            .execute()
            .data
        ) or []
    except Exception as exc:
        logger.error("[Backfill] failed to fetch meetings: %s", exc)
        return 1

    logger.info("[Backfill] fetched %d meetings with recap_extras_json", len(rows))

    # Cache owner_name per tenant to avoid N queries
    tenant_owner: dict[str, str] = {}

    def _owner_for(tid: str) -> str:
        if tid in tenant_owner:
            return tenant_owner[tid]
        try:
            u_rows = (
                supabase.table("users")
                .select("full_name, email")
                .eq("tenant_id", tid)
                .limit(1)
                .execute()
                .data
            ) or []
        except Exception as exc:
            logger.warning("[Backfill] users lookup failed tenant_id=%s err=%s", tid, exc)
            u_rows = []
        u = u_rows[0] if u_rows else {}
        name = (u.get("full_name") or "").strip()
        if not name and u.get("email"):
            name = u["email"].split("@")[0]
        tenant_owner[tid] = name
        return name

    total_written = 0
    upsert_errors = 0

    for m in rows:
        meeting_id = m.get("id")
        tenant_id = m.get("tenant_id")
        twin_id = m.get("twin_id")

        if not (meeting_id and tenant_id and twin_id):
            logger.debug("[Backfill] skip meeting=%s: missing tenant_id or twin_id", meeting_id)
            continue

        structured = structured_commitments_from_extras(
            m.get("recap_extras_json"),
            owner_name=_owner_for(tenant_id),
        )
        if not structured:
            continue

        if args.dry_run:
            logger.info(
                "[Backfill][DRY-RUN] meeting=%s would write %d commitments",
                meeting_id, len(structured),
            )
            total_written += len(structured)
            continue

        payload = [
            {
                "tenant_id": tenant_id,
                "twin_id": twin_id,
                "meeting_id": meeting_id,
                "direction": c["direction"],
                "text": c["text"],
                "assignee_name": c["assignee_name"],
                "due_at": c["due_at"],
                "content_hash": c["content_hash"],
                "source": "recap_extras",
            }
            for c in structured
        ]

        try:
            supabase.table("meeting_commitments").upsert(
                payload, on_conflict="meeting_id,content_hash,source"
            ).execute()
            total_written += len(payload)
        except Exception as exc:
            logger.warning("[Backfill] upsert failed meeting=%s err=%s", meeting_id, type(exc).__name__)
            upsert_errors += 1

    logger.info(
        "[Backfill] DONE — meetings_processed=%d commitments_written=%d errors=%d%s",
        len(rows),
        total_written,
        upsert_errors,
        " (dry-run)" if args.dry_run else "",
    )
    return 0 if upsert_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
