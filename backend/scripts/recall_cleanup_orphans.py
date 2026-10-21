"""One-off: clean up orphan Recall V2 calendars.

Two orphan classes are addressed:

1. ``disconnected`` calendars: any calendar whose latest status is
   ``disconnected`` is dead weight and safe to delete.

2. ``dupes-by-twin``: a bug in ``calendar_booking.py`` created a brand-new
   Recall calendar on every OAuth callback. For each ``metadata.twin_id``,
   keep only the most recent calendar and delete the older ones.

Both rules are evaluated independently, then the union is deleted.

Usage:
    python backend/scripts/recall_cleanup_orphans.py              # dry-run
    python backend/scripts/recall_cleanup_orphans.py --yes        # delete
    python backend/scripts/recall_cleanup_orphans.py --status connecting --yes
        (legacy: delete by exact status only)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import httpx


def _load_env(path: Path) -> None:
    """Minimal .env loader (no python-dotenv dep). Skips already-set env vars."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _bootstrap_env() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    _load_env(repo_root / "backend" / ".env.local")
    _load_env(repo_root / "backend" / ".env")


async def _list_calendars(
    client: httpx.AsyncClient, base: str, headers: dict[str, str]
) -> list[dict]:
    results: list[dict] = []
    url: str | None = f"{base}/calendars/"
    while url:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            page = data.get("results", [])
            if isinstance(page, list):
                results.extend(page)
            nxt = data.get("next")
            url = nxt if isinstance(nxt, str) else None
        elif isinstance(data, list):
            results.extend(data)
            url = None
        else:
            url = None
    return results


async def _delete_calendar(
    client: httpx.AsyncClient, base: str, headers: dict[str, str], cal_id: str
) -> tuple[bool, str]:
    resp = await client.delete(f"{base}/calendars/{cal_id}/", headers=headers)
    if resp.is_success or resp.status_code == 404:
        return True, f"{resp.status_code}"
    return False, f"{resp.status_code} {resp.text[:200]}"


def _classify(all_cals: list[dict], status_filter: str | None) -> list[dict]:
    """Return calendars to delete.

    If ``status_filter`` is given, behaves like the legacy script: deletes all
    calendars whose ``status`` matches. Otherwise: deletes all ``disconnected``
    calendars plus per-twin duplicates (keep newest, drop older).
    """
    if status_filter:
        return [c for c in all_cals if (c.get("status") or "").lower() == status_filter.lower()]

    to_delete: list[dict] = []

    # Rule A: every disconnected calendar is orphan.
    disconnected = [c for c in all_cals if (c.get("status") or "").lower() == "disconnected"]
    to_delete.extend(disconnected)
    disconnected_ids = {c.get("id") for c in disconnected}

    # Rule B: per-twin dupes among the remaining (non-disconnected).
    by_twin: dict[str, list[dict]] = {}
    for c in all_cals:
        if c.get("id") in disconnected_ids:
            continue
        twin_id = (c.get("metadata") or {}).get("twin_id")
        if not twin_id:
            continue
        by_twin.setdefault(twin_id, []).append(c)

    for twin_id, cals in by_twin.items():
        if len(cals) <= 1:
            continue
        # Newest by created_at wins; drop older ones.
        cals_sorted = sorted(cals, key=lambda c: c.get("created_at") or "", reverse=True)
        to_delete.extend(cals_sorted[1:])

    # Dedup the to_delete list by id (a calendar could theoretically be
    # caught by both rules; not currently possible since Rule B excludes
    # disconnected, but defensive).
    seen: set[str] = set()
    unique: list[dict] = []
    for c in to_delete:
        cid = c.get("id")
        if cid and cid not in seen:
            seen.add(cid)
            unique.append(c)
    return unique


async def main(args: argparse.Namespace) -> int:
    _bootstrap_env()
    api_key = os.environ.get("RECALL_API_KEY", "").strip()
    region = os.environ.get("RECALL_API_REGION", "us-east-1").strip() or "us-east-1"
    if not api_key:
        print("ERROR: RECALL_API_KEY not set in backend/.env or backend/.env.local", file=sys.stderr)
        return 2

    base = f"https://{region}.recall.ai/api/v2"
    headers = {"Authorization": f"Token {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        all_cals = await _list_calendars(client, base, headers)
        target = _classify(all_cals, args.status)

        mode = f"status={args.status!r}" if args.status else "smart (disconnected + per-twin dupes)"
        print(f"Recall region={region} total={len(all_cals)} mode={mode} to-delete={len(target)}")

        if not target:
            return 0

        for c in target:
            twin = (c.get("metadata") or {}).get("twin_id")
            print(
                f"  {c.get('id')}  status={c.get('status')}  "
                f"twin={twin}  created={c.get('created_at')}"
            )

        if not args.yes:
            print("\nDry run. Pass --yes to delete.")
            return 0

        ok, fail = 0, 0
        for c in target:
            cal_id = c.get("id")
            if not cal_id:
                continue
            success, info = await _delete_calendar(client, base, headers, cal_id)
            if success:
                print(f"  deleted {cal_id} ({info})")
                ok += 1
            else:
                print(f"  FAILED {cal_id} ({info})")
                fail += 1

        print(f"\nDone: deleted={ok} failed={fail}")
        return 0 if fail == 0 else 1


def _parse() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--status",
        default=None,
        help=(
            "Legacy mode: delete only calendars with this exact status. "
            "If omitted, runs smart cleanup (disconnected + per-twin dupes)."
        ),
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete. Without this flag, dry-run only.",
    )
    return p.parse_args()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(_parse())))
