"""Persistence for ADK conversations and message logs."""

from __future__ import annotations

from typing import Any

from adk_core.repositories.base import BaseRepository, _extract_list, _extract_one, utc_now_iso


class ConversationRepository(BaseRepository):
    """Stores chat turns independently of ADK session state."""

    table_name = "adk_conversations"

    def create_conversation(
        self,
        *,
        twin_id: str,
        tenant_id: str | None,
        user_id: str | None,
        surface: str,
        share_token: str | None = None,
        metadata: dict[str, Any] | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        return self.insert_one({
            "id": conversation_id,
            "twin_id": twin_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "surface": surface,
            "share_token": share_token,
            "metadata": metadata or {},
        })

    def get_conversation(self, *, conversation_id: str) -> dict[str, Any] | None:
        return self.get_one(id=conversation_id)

    def get_conversation_for_tenant(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
    ) -> dict[str, Any] | None:
        """Get conversation and verify tenant ownership."""
        conv = self.get_one(id=conversation_id)
        if not conv:
            return None
        if conv.get("tenant_id") and str(conv.get("tenant_id")) != str(tenant_id):
            return None
        return conv

    def list_conversations(
        self,
        *,
        tenant_id: str,
        twin_id: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List conversations for a tenant, optionally filtered by twin.

        When twin_id is provided, returns ALL conversations for that twin
        (owner, public, widget) — not just tenant-scoped ones. The caller
        must verify twin ownership before calling.
        """
        if twin_id:
            # Show all conversations for this twin (all surfaces)
            query = (
                self._client()
                .select("*")
                .eq("twin_id", twin_id)
            )
        else:
            # No twin filter — show only tenant's own conversations
            query = self._client().select("*").eq("tenant_id", tenant_id)
        query = query.order("updated_at", desc=True).range(offset, offset + limit - 1)
        conversations = _extract_list(query.execute())

        # Enrich with first user message preview
        conv_ids = [c["id"] for c in conversations]
        if conv_ids:
            from modules.observability import supabase
            first_msgs_resp = (
                supabase.table("adk_messages")
                .select("conversation_id, content")
                .in_("conversation_id", conv_ids)
                .eq("role", "user")
                .order("created_at", desc=False)
                .execute()
            )
            first_msgs: dict[str, str] = {}
            for row in (first_msgs_resp.data or []):
                cid = row["conversation_id"]
                if cid not in first_msgs:
                    first_msgs[cid] = (row.get("content") or "")[:120]
            for conv in conversations:
                conv["first_message_preview"] = first_msgs.get(conv["id"], "")

        return conversations

    def touch_conversation(self, conversation_id: str) -> None:
        self.update_one("id", conversation_id)

    def add_message(
        self,
        *,
        conversation_id: str,
        twin_id: str,
        tenant_id: str | None,
        role: str,
        content: str,
        citations: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from modules.observability import supabase
        payload = {
            "conversation_id": conversation_id,
            "twin_id": twin_id,
            "tenant_id": tenant_id,
            "role": role,
            "content": content,
            "citations": citations or [],
            "metadata": metadata or {},
            "created_at": utc_now_iso(),
        }
        response = supabase.table("adk_messages").insert(payload).execute()
        self.touch_conversation(conversation_id)
        return _extract_one(response)

    def list_messages(self, *, conversation_id: str) -> list[dict[str, Any]]:
        from modules.observability import supabase
        return _extract_list(
            supabase.table("adk_messages")
            .select("*")
            .eq("conversation_id", conversation_id)
            .order("created_at", desc=False)
            .execute()
        )
