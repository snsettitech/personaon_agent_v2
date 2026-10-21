from __future__ import annotations

import argparse
from typing import Any

from modules.observability import supabase
from modules.public_profile_pack import (
    build_existing_profile_projection,
    build_research_profile_projection,
    merge_materialized_profile_settings,
)


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _load_latest_name_first_result(twin_id: str) -> dict[str, Any] | None:
    try:
        response = (
            supabase.table("name_deep_research_runs")
            .select("result_json, created_at")
            .eq("twin_id", twin_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        print(f"[backfill] warning: could not query name_deep_research_runs for {twin_id}: {exc}")
        return None

    row = (response.data or [{}])[0] if response.data else {}
    result_json = row.get("result_json")
    return result_json if isinstance(result_json, dict) else None


def _load_twins(*, twin_id: str | None, limit: int) -> list[dict[str, Any]]:
    def _run_query(select_clause: str):
        query = supabase.table("twins").select(select_clause)
        if twin_id:
            query = query.eq("id", twin_id)
        else:
            query = query.limit(limit)
        return query.execute()

    try:
        response = _run_query("id, tenant_id, name, description, settings, status, is_active")
    except Exception as exc:
        if "is_active" not in str(exc):
            raise
        print("[backfill] warning: twins.is_active missing; retrying without that column")
        response = _run_query("id, tenant_id, name, description, settings, status")
    return list(response.data or [])


def _build_projection(twin: dict[str, Any]) -> dict[str, Any]:
    settings = _safe_dict(twin.get("settings"))
    creation_mode = str(settings.get("creation_mode") or "").strip().lower()
    if creation_mode == "name_first":
        result_json = _load_latest_name_first_result(str(twin.get("id") or ""))
        if isinstance(result_json, dict) and result_json:
            return build_research_profile_projection(twin, result_json, source_flow="backfill")
    return build_existing_profile_projection(twin, source_flow="backfill")


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill canonical persona profiles into twins.settings.")
    parser.add_argument("--twin-id", help="Backfill a single twin by id")
    parser.add_argument("--limit", type=int, default=50, help="Max twins to process when --twin-id is not set")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without writing")
    args = parser.parse_args()

    twins = _load_twins(twin_id=args.twin_id, limit=max(1, int(args.limit or 50)))
    if not twins:
        print("[backfill] no twins found")
        return 0

    updated = 0
    for twin in twins:
        twin_id = str(twin.get("id") or "")
        settings = _safe_dict(twin.get("settings"))
        projection = _build_projection(twin)
        merged_settings = merge_materialized_profile_settings(settings, projection)
        meta = _safe_dict(merged_settings.get("public_profile_meta"))
        print(
            f"[backfill] twin={twin_id} "
            f"name={twin.get('name')!r} "
            f"source_flow={meta.get('source_flow')} "
            f"image_status={meta.get('image_status')} "
            f"completeness={meta.get('completeness_score')}"
        )
        if args.dry_run:
            continue
        supabase.table("twins").update({"settings": merged_settings}).eq("id", twin_id).execute()
        updated += 1

    print(f"[backfill] completed updated={updated} dry_run={args.dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
