"""Persistence for authoritative persona artifacts and quote packs."""

from __future__ import annotations

import logging
from typing import Any

from adk_core.repositories.base import is_empty_lookup_error, utc_now_iso
import asyncio
from modules.embeddings import get_embedding
from modules.observability import supabase

logger = logging.getLogger(__name__)


class PersonaRepository:
    """Stores canonical persona artifacts and supporting quote records."""

    def get_active_artifact(
        self,
        *,
        twin_id: str,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the latest persona artifact, preferring active over draft.

        During onboarding the artifact is created as 'draft' (publish=False)
        and only promoted to 'active' on explicit publish.  The review and
        chat endpoints need access to the artifact in either state so that
        users can preview before publishing.
        """
        # Try active first
        query = (
            supabase.table("adk_persona_artifacts")
            .select("*")
            .eq("twin_id", twin_id)
            .eq("status", "active")
            .order("created_at", desc=True)
            .limit(1)
        )
        if tenant_id:
            query = query.eq("tenant_id", tenant_id)
        response = query.execute()
        response_data = response.data if response else None
        row = (response_data or [None])[0]
        if row:
            return row

        # Fallback to draft (pre-publish onboarding state)
        query = (
            supabase.table("adk_persona_artifacts")
            .select("*")
            .eq("twin_id", twin_id)
            .eq("status", "draft")
            .order("created_at", desc=True)
            .limit(1)
        )
        if tenant_id:
            query = query.eq("tenant_id", tenant_id)
        response = query.execute()
        response_data = response.data if response else None
        return (response_data or [None])[0]

    def list_quotes(
        self,
        *,
        twin_id: str,
        tenant_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = (
            supabase.table("adk_persona_quotes")
            .select("*")
            .eq("twin_id", twin_id)
            .order("confidence", desc=True)
        )
        if tenant_id:
            query = query.eq("tenant_id", tenant_id)
        response = query.execute()
        return (response.data if response else None) or []

    def publish_artifact(
        self,
        *,
        tenant_id: str,
        twin_id: str,
        artifact: dict[str, Any],
        publish: bool = True,
    ) -> dict[str, Any]:
        if publish:
            (
                supabase.table("adk_persona_artifacts")
                .update({"status": "archived", "updated_at": utc_now_iso()})
                .eq("tenant_id", tenant_id)
                .eq("twin_id", twin_id)
                .eq("status", "active")
                .execute()
            )

        payload = {
            "tenant_id": tenant_id,
            "twin_id": twin_id,
            "version": artifact["version"],
            "status": "active" if publish else "draft",
            "artifact_json": artifact,
            "created_at": utc_now_iso(),
            "updated_at": utc_now_iso(),
        }
        response = supabase.table("adk_persona_artifacts").insert(payload).execute()
        response_data = response.data if response else None
        row = (response_data or [None])[0]
        artifact_id = row["id"]

        (
            supabase.table("adk_persona_quotes")
            .delete()
            .eq("tenant_id", tenant_id)
            .eq("twin_id", twin_id)
            .execute()
        )

        quotes = []
        for idx, item in enumerate(artifact.get("quote_pack") or [], start=1):
            quotes.append(
                {
                    "tenant_id": tenant_id,
                    "twin_id": twin_id,
                    "persona_artifact_id": artifact_id,
                    "quote_text": item.get("quote", ""),
                    "source_id": item.get("source_id"),
                    "context": item.get("context", ""),
                    "confidence": item.get("confidence", 0.0),
                    "position": idx,
                    "created_at": utc_now_iso(),
                    "updated_at": utc_now_iso(),
                }
            )
        if quotes:
            supabase.table("adk_persona_quotes").insert(quotes).execute()

        self._mirror_to_legacy_twin_settings(twin_id=twin_id, artifact=artifact)
        self._index_for_retrieval(twin_id=twin_id, artifact=artifact, artifact_id=artifact_id)
        return row

    def update_artifact(
        self,
        *,
        tenant_id: str,
        twin_id: str,
        artifact: dict[str, Any],
    ) -> None:
        """Update the latest persona artifact in place (for user edits).

        Works for both 'active' and 'draft' artifacts — during onboarding
        the artifact is 'draft' until publish.
        """
        row = self.get_active_artifact(twin_id=twin_id, tenant_id=tenant_id)
        if not row:
            return
        (
            supabase.table("adk_persona_artifacts")
            .update({"artifact_json": artifact, "updated_at": utc_now_iso()})
            .eq("id", row["id"])
            .execute()
        )
        self._mirror_to_legacy_twin_settings(twin_id=twin_id, artifact=artifact)

    def _mirror_to_legacy_twin_settings(self, *, twin_id: str, artifact: dict[str, Any]) -> None:
        try:
            twin_result = (
                supabase.table("twins")
                .select("settings")
                .eq("id", twin_id)
                .maybe_single()
                .execute()
            )
        except Exception as exc:
            if is_empty_lookup_error(exc):
                twin_result = None
            else:
                raise
        twin_data = twin_result.data if twin_result else None
        current_settings = dict((twin_data or {}).get("settings") or {})
        current_settings["public_profile"] = artifact.get("public_profile") or {}
        current_settings["persona_identity_pack"] = artifact.get("persona_identity_pack") or {}
        current_settings["adk_persona_version"] = artifact.get("version")
        (
            supabase.table("twins")
            .update({"settings": current_settings, "status": "persona_built"})
            .eq("id", twin_id)
            .execute()
        )

    def _index_for_retrieval(self, *, twin_id: str, artifact: dict[str, Any], artifact_id: str) -> None:
        from adk_core.services.vector_store import upsert_text_chunks

        try:
            texts: list[str] = []

            for claim in artifact.get("claims") or []:
                text = str(claim.get("text") or "").strip()
                if text:
                    texts.append(text)

            for quote in artifact.get("quote_pack") or []:
                text = str(quote.get("quote") or "").strip()
                if text:
                    texts.append(text)

            if texts:
                combined = "\n\n".join(texts)
                asyncio.run(upsert_text_chunks(
                    combined, twin_id=twin_id, source="persona_artifact",
                    metadata={"artifact_id": artifact_id, "type": "persona_artifact"},
                ))
        except Exception as exc:
            logger.warning(
                "Persona retrieval indexing skipped for twin %s artifact %s: %s",
                twin_id,
                artifact_id,
                exc,
            )
