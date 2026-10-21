"""Local-dev Recall.ai recording poller.

WHY THIS EXISTS
---------------
In production, Recall fires an `sdk_upload.complete` webhook to the backend,
which enqueues PROCESS_DESKTOP_SDK_RECORDING -> the worker fetches the
transcript/video from Recall and runs recap extraction.

Recall webhooks cannot reach `localhost`, and a public tunnel (ngrok /
cloudflared) gives a new URL every restart that must be re-registered in the
Recall dashboard by hand. For local dev that's high-friction.

This poller replaces the webhook for local use: it periodically finds meetings
stuck at recording/uploading/processing, asks Recall whether the recording is
done, and when it is, runs the EXACT same processing the webhook would trigger
(_process_desktop_sdk_recording). No tunnel, no dashboard, no webhook secret.

USAGE
-----
Run alongside the backend, from the backend/ directory with the venv:

    cd backend
    .venv/Scripts/python.exe scripts/dev_recall_poller.py

Ctrl+C to stop. It is idempotent — the worker's skip-if-populated guard
(F2.1) means re-processing an already-recapped meeting is a no-op.

LOCAL DEV ONLY. Production uses the real webhook.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

# Load env the same way the backend does.
from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env", override=False)
load_dotenv(_ROOT / "backend" / ".env", override=False)

# Ensure backend package root is importable when run from anywhere.
sys.path.insert(0, str(_ROOT / "backend"))

from modules.graph_outbox_worker import _process_desktop_sdk_recording  # noqa: E402
from modules.observability import get_supabase_client  # noqa: E402
from services.recall_service import get_recording  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("dev_recall_poller")

POLL_INTERVAL_SECONDS = 12
STUCK_STATUSES = ("recording", "uploading", "processing")


async def _poll_once() -> int:
    """One poll cycle. Returns the number of recordings processed."""
    sb = get_supabase_client()
    if sb is None:
        logger.warning("Supabase client unavailable; skipping cycle")
        return 0

    resp = (
        sb.table("meetings")
        .select("id, tenant_id, recall_recording_id, status")
        .eq("source", "desktop_sdk")
        .in_("status", list(STUCK_STATUSES))
        .not_.is_("recall_recording_id", "null")
        .limit(25)
        .execute()
    )
    rows = getattr(resp, "data", None) or []
    if not rows:
        return 0

    processed = 0
    for row in rows:
        recording_id = row.get("recall_recording_id")
        meeting_id = row.get("id")
        tenant_id = row.get("tenant_id")
        if not recording_id:
            continue
        try:
            recording = await get_recording(recording_id)
        except Exception as exc:
            logger.warning("get_recording failed recording=%s: %s", recording_id, exc)
            continue

        status_code = ((recording or {}).get("status") or {}).get("code")
        if status_code != "done":
            logger.info(
                "meeting=%s recall=%s not ready (recall status=%s) — will retry",
                meeting_id, recording_id, status_code,
            )
            continue

        logger.info(
            "meeting=%s recall=%s is done — processing (transcript + recap)",
            meeting_id, recording_id,
        )
        job = {
            "id": f"local-poller:{recording_id}",
            "operation": "process_desktop_sdk_recording",
            "tenant_id": tenant_id,
            "payload": {
                "recall_recording_id": recording_id,
                "meeting_id": meeting_id,
                "tenant_id": tenant_id,
            },
        }
        try:
            ok = await _process_desktop_sdk_recording(job)
            if ok:
                processed += 1
                logger.info("meeting=%s processed OK", meeting_id)
            else:
                logger.warning("meeting=%s processing returned False — will retry", meeting_id)
        except Exception:
            logger.exception("meeting=%s processing crashed — will retry", meeting_id)

    return processed


async def main() -> None:
    logger.info(
        "Recall poller started (every %ss, statuses=%s). Ctrl+C to stop.",
        POLL_INTERVAL_SECONDS, ",".join(STUCK_STATUSES),
    )
    while True:
        try:
            n = await _poll_once()
            if n:
                logger.info("cycle complete: processed %d recording(s)", n)
        except Exception:
            logger.exception("poll cycle failed (continuing)")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("poller stopped")
