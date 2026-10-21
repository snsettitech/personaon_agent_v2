"""Walk existing meetings and enqueue extract_memory_candidates jobs for those
without any existing candidates (idempotency via idempotency_key).

Usage:
  cd backend
  .venv/Scripts/python.exe scripts/backfill_memory_candidates.py [--dry-run] [--limit N]
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env", override=False)
load_dotenv(_ROOT / "backend" / ".env", override=False)
load_dotenv(_ROOT / "backend" / ".env.local", override=True)

sys.path.insert(0, str(_ROOT / "backend"))

from modules.observability import supabase  # noqa: E402
from modules.graph_outbox import get_graph_outbox, GraphOperationType  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill_memory_candidates")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enqueue extract_memory_candidates jobs for meetings lacking candidates."
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be enqueued without actually writing.",
    )
    parser.add_argument(
        "--limit", type=int, default=1000,
        help="Max number of meetings to scan (default: 1000).",
    )
    args = parser.parse_args()

    if supabase is None:
        logger.error("Supabase client not initialized — check SUPABASE_URL / SUPABASE_KEY env vars.")
        return 1

    try:
        rows = (
            supabase.table("meetings")
            .select("id, tenant_id, twin_id")
            .not_.is_("recap_extras_json", "null")
            .limit(args.limit)
            .execute()
            .data
        ) or []
    except Exception as exc:
        logger.error("[Backfill] failed to fetch meetings: %s", exc)
        return 1

    logger.info("[Backfill] fetched %d meetings with recap_extras_json", len(rows))

    enqueued = 0
    errors = 0

    for m in rows:
        meeting_id = m.get("id")
        tenant_id = m.get("tenant_id")
        twin_id = m.get("twin_id")

        if not (meeting_id and tenant_id and twin_id):
            logger.debug("[Backfill] skip meeting=%s: missing tenant_id or twin_id", meeting_id)
            continue

        if args.dry_run:
            logger.info("[Backfill][DRY-RUN] would enqueue meeting=%s", meeting_id)
            enqueued += 1
            continue

        try:
            get_graph_outbox().submit(
                tenant_id=tenant_id,
                twin_id=twin_id,
                operation=GraphOperationType.EXTRACT_MEMORY_CANDIDATES,
                idempotency_key=f"extract_memory_candidates:{meeting_id}",
                payload={
                    "tenant_id": tenant_id,
                    "twin_id": twin_id,
                    "meeting_id": meeting_id,
                },
            )
            enqueued += 1
        except Exception as exc:
            logger.warning(
                "[Backfill] submit failed meeting=%s err=%s", meeting_id, type(exc).__name__
            )
            errors += 1

    logger.info(
        "[Backfill] DONE — meetings_scanned=%d enqueued=%d errors=%d%s",
        len(rows),
        enqueued,
        errors,
        " (dry-run)" if args.dry_run else "",
    )
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
