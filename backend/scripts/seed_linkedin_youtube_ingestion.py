#!/usr/bin/env python3
"""
Seed LinkedIn + YouTube ingestion evidence into the configured Supabase project.

This is a dev/proof helper:
- Creates a temporary twin (unless PROOF_TWIN_ID is provided).
- Runs URL ingestion for required proof URLs.
- Prints resulting source IDs so proof scripts can query concrete records.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from modules.ingestion import ingest_url_to_source  # noqa: E402
from modules.observability import supabase  # noqa: E402

YOUTUBE_URL = "https://www.youtube.com/watch?v=HiC1J8a9V1I"
LINKEDIN_URL = "https://www.linkedin.com/in/sainathsetti/"


def _load_env() -> None:
    load_dotenv(REPO_ROOT / ".env")
    load_dotenv(BACKEND_ROOT / ".env")


def _create_proof_twin() -> dict[str, Any]:
    tenant_name = f"Proof Tenant {datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:6]}"
    tenant_res = supabase.table("tenants").insert({"name": tenant_name}).execute()
    if not tenant_res.data:
        raise RuntimeError("Failed to create proof tenant")
    tenant_id = tenant_res.data[0]["id"]

    twin_name = f"Proof Twin {datetime.now(timezone.utc).strftime('%H%M%S')}-{uuid.uuid4().hex[:5]}"
    twin_res = supabase.table("twins").insert(
        {
            "tenant_id": tenant_id,
            "name": twin_name,
            "description": "Temporary proof twin for ingestion diagnostics",
            "specialization": "vanilla",
            "settings": {"proof_seed": True},
        }
    ).execute()
    if not twin_res.data:
        raise RuntimeError("Failed to create proof twin")
    return twin_res.data[0]


async def _run() -> int:
    _load_env()
    result: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "urls": {
            "youtube": YOUTUBE_URL,
            "linkedin": LINKEDIN_URL,
        },
        "ingestions": {},
    }

    proof_twin_id = os.getenv("PROOF_TWIN_ID")
    if proof_twin_id:
        twin_id = proof_twin_id
        result["twin"] = {"id": twin_id, "mode": "existing"}
    else:
        created = _create_proof_twin()
        twin_id = created["id"]
        result["twin"] = {
            "id": twin_id,
            "tenant_id": created.get("tenant_id"),
            "name": created.get("name"),
            "mode": "created",
        }

    for key, url in (("youtube", YOUTUBE_URL), ("linkedin", LINKEDIN_URL)):
        source_id = str(uuid.uuid4())
        correlation_id = f"proof-{key}-{uuid.uuid4().hex[:8]}"
        item = {
            "source_id": source_id,
            "url": url,
            "correlation_id": correlation_id,
        }
        try:
            chunks = await ingest_url_to_source(
                source_id=source_id,
                twin_id=twin_id,
                url=url,
                correlation_id=correlation_id,
            )
            item["status"] = "completed"
            item["chunk_count"] = int(chunks or 0)
        except Exception as exc:
            item["status"] = "error"
            item["error"] = str(exc)
        result["ingestions"][key] = item

    print(json.dumps(result, indent=2))
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
