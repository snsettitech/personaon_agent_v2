"""Quick dump: list all Recall V2 calendars with status + key fields."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


async def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    _load_env(repo_root / "backend" / ".env.local")
    _load_env(repo_root / "backend" / ".env")

    api_key = os.environ.get("RECALL_API_KEY", "").strip()
    region = os.environ.get("RECALL_API_REGION", "us-east-1").strip() or "us-east-1"
    if not api_key:
        print("ERROR: RECALL_API_KEY not set", file=sys.stderr)
        return 2

    base = f"https://{region}.recall.ai/api/v2"
    headers = {"Authorization": f"Token {api_key}", "Content-Type": "application/json"}

    async with httpx.AsyncClient(timeout=30.0) as client:
        all_cals: list[dict] = []
        url: str | None = f"{base}/calendars/"
        while url:
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            d = r.json()
            if isinstance(d, dict):
                all_cals.extend(d.get("results", []))
                nxt = d.get("next")
                url = nxt if isinstance(nxt, str) else None
            elif isinstance(d, list):
                all_cals.extend(d)
                url = None
            else:
                url = None

        print(f"region={region} total={len(all_cals)}")
        print()
        for c in all_cals:
            keys = [
                k for k in c.keys()
                if "status" in k.lower()
                or k in ("id", "platform", "created_at", "updated_at", "metadata")
            ]
            line = "  " + "  ".join(f"{k}={c.get(k)!r}" for k in keys)
            print(line)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
