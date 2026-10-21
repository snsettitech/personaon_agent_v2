#!/usr/bin/env python3
"""One-time cleanup: merge duplicate meeting rows created by the booking flow vs
calendar sync (the "two nikhil rows" bug, fixed forward by stamping ical_uid on
booking rows — see docs/product/meetings-spec-and-plan.md, Phase A).

A duplicate pair is:
  * a BOT row  — ``ical_uid IS NULL`` with a ``recall_bot_id`` and/or ``booking_id``
                 (created by the booking flow before the fix), and
  * a CAL row  — ``ical_uid IS NOT NULL`` (the same event synced from Recall),
matched by ``meet_link`` (preferred) or by ``(meeting_start, lower(title))``.

For each pair we KEEP the calendar row (it owns the stable ``ical_uid``), copy the
bot row's attendance/bot fields onto it, then DELETE the bot row.

Usage (dry-run prints the plan; nothing is written without --yes):
    DATABASE_URL='postgresql://...pooler...:6543/postgres' \\
        python backend/scripts/dedup_booking_calendar_meetings.py
    DATABASE_URL='...' python backend/scripts/dedup_booking_calendar_meetings.py --yes
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg2
import psycopg2.extras

# Bot row (no ical_uid, has a bot/booking) that matches a calendar row (has ical_uid)
# for the same twin and same underlying meeting.
_FIND_PAIRS_SQL = """
SELECT
    b.id            AS bot_id,
    c.id            AS cal_id,
    b.twin_id       AS twin_id,
    c.title         AS title,
    b.recall_bot_id AS bot_recall_bot_id,
    b.twin_attends  AS bot_twin_attends,
    b.booking_id    AS bot_booking_id,
    b.mode          AS bot_mode,
    c.recall_bot_id AS cal_recall_bot_id,
    c.booking_id    AS cal_booking_id
FROM meetings b
JOIN meetings c
  ON  c.twin_id = b.twin_id
  AND c.id <> b.id
  AND c.ical_uid IS NOT NULL
  AND b.ical_uid IS NULL
  AND (
        (b.meet_link IS NOT NULL AND b.meet_link <> '' AND b.meet_link = c.meet_link)
     OR (b.meeting_start IS NOT NULL
         AND b.meeting_start = c.meeting_start
         AND lower(coalesce(b.title, '')) = lower(coalesce(c.title, '')))
      )
  AND (b.recall_bot_id IS NOT NULL OR b.booking_id IS NOT NULL)
ORDER BY b.twin_id, c.meeting_start;
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="commit the merge (default: dry-run)")
    parser.add_argument("--db-url", default=os.getenv("DATABASE_URL"), help="Postgres connection string")
    args = parser.parse_args()

    if not args.db_url:
        print("ERROR: set DATABASE_URL or pass --db-url", file=sys.stderr)
        return 2

    conn = psycopg2.connect(args.db_url)
    conn.autocommit = False
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(_FIND_PAIRS_SQL)
            rows = cur.fetchall()

            # A bot row could (rarely) match multiple calendar rows — keep the first.
            seen_bot: set[str] = set()
            pairs = []
            for r in rows:
                if r["bot_id"] in seen_bot:
                    continue
                seen_bot.add(r["bot_id"])
                pairs.append(r)

            if not pairs:
                print("No duplicate booking/calendar meeting pairs found. Nothing to do.")
                return 0

            print(f"Found {len(pairs)} duplicate pair(s):\n")
            for r in pairs:
                print(f"  twin={r['twin_id']}  '{r['title']}'")
                print(f"    KEEP cal row {r['cal_id']}  (has ical_uid)")
                print(f"    MERGE+DELETE bot row {r['bot_id']}  "
                      f"(bot={r['bot_recall_bot_id']}, attends={r['bot_twin_attends']}, booking={r['bot_booking_id']})")

            if not args.yes:
                print("\nDRY RUN — re-run with --yes to apply.")
                return 0

            for r in pairs:
                # Carry the bot row's attendance/bot fields onto the calendar row,
                # only filling what the calendar row is missing.
                cur.execute(
                    """
                    UPDATE meetings SET
                        twin_attends  = COALESCE(twin_attends, false) OR %(bot_attends)s,
                        recall_bot_id = COALESCE(recall_bot_id, %(bot_recall)s),
                        booking_id    = COALESCE(booking_id, %(bot_booking)s),
                        mode          = COALESCE(mode, %(bot_mode)s)
                    WHERE id = %(cal_id)s
                    """,
                    {
                        "bot_attends": bool(r["bot_twin_attends"]),
                        "bot_recall": r["bot_recall_bot_id"],
                        "bot_booking": r["bot_booking_id"],
                        "bot_mode": r["bot_mode"],
                        "cal_id": r["cal_id"],
                    },
                )
                cur.execute("DELETE FROM meetings WHERE id = %(bot_id)s", {"bot_id": r["bot_id"]})

            conn.commit()
            print(f"\nMerged + deleted {len(pairs)} bot row(s). Done.")
            return 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
