"""Persistence for research runs and research artifacts."""

from __future__ import annotations

from typing import Any

from adk_core.repositories.base import BaseRepository, _extract_list, _extract_one, compact_dict, utc_now_iso


class ResearchRepository(BaseRepository):
    """Stores authoritative research runs and artifacts."""

    table_name = "adk_research_runs"

    def create_run(
        self,
        *,
        tenant_id: str,
        user_id: str,
        subject_name: str,
        twin_id: str | None = None,
        hints: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        if idempotency_key:
            existing = _extract_list(
                self._client()
                .select("*")
                .eq("tenant_id", tenant_id)
                .eq("idempotency_key", idempotency_key)
                .limit(1)
                .execute()
            )
            if existing:
                return existing[0]

        return self.insert_one(compact_dict({
            "tenant_id": tenant_id,
            "user_id": user_id,
            "twin_id": twin_id,
            "subject_name": subject_name,
            "hints": hints or {},
            "idempotency_key": idempotency_key,
            "status": "queued",
        }))

    def get_run(self, *, run_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        filters = {"id": run_id}
        if tenant_id:
            filters["tenant_id"] = tenant_id
        return self.get_one(**filters)

    def update_run(self, run_id: str, **updates: Any) -> dict[str, Any] | None:
        return self.update_one("id", run_id, **updates)

    def save_artifact(
        self,
        *,
        run_id: str,
        tenant_id: str,
        twin_id: str | None,
        artifact: dict[str, Any],
    ) -> dict[str, Any]:
        from modules.observability import supabase
        art_table = supabase.table("adk_research_artifacts")
        payload = {
            "run_id": run_id,
            "tenant_id": tenant_id,
            "twin_id": twin_id,
            "artifact_json": artifact,
        }
        from adk_core.repositories.base import is_empty_lookup_error
        try:
            existing = art_table.select("id").eq("run_id", run_id).maybe_single().execute()
        except Exception as exc:
            if is_empty_lookup_error(exc):
                existing = None
            else:
                raise
        existing_data = (existing.data if existing else None) or None
        now = utc_now_iso()
        if existing_data:
            return _extract_one(
                art_table.update({**payload, "updated_at": now}).eq("run_id", run_id).execute()
            )
        return _extract_one(
            art_table.insert({**payload, "created_at": now, "updated_at": now}).execute()
        )

    def get_artifact(self, *, run_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        from modules.observability import supabase
        query = supabase.table("adk_research_artifacts").select("*").eq("run_id", run_id)
        if tenant_id:
            query = query.eq("tenant_id", tenant_id)
        from adk_core.repositories.base import is_empty_lookup_error
        try:
            response = query.maybe_single().execute()
        except Exception as exc:
            if is_empty_lookup_error(exc):
                return None
            raise
        return (response.data if response else None) or None
