"""Persistence for ADK Session objects."""

from __future__ import annotations


from google.adk.sessions import Session

from adk_core.repositories.base import BaseRepository, _extract_list
import builtins


class SessionRepository(BaseRepository):
    """Stores the full serialized ADK Session payload."""

    table_name = "adk_sessions"

    def save(
        self,
        *,
        session: Session,
        tenant_id: str | None = None,
        twin_id: str | None = None,
    ) -> dict:
        payload = {
            "app_name": session.app_name,
            "user_id": session.user_id,
            "tenant_id": tenant_id,
            "twin_id": twin_id,
            "session_json": session.model_dump(mode="json"),
        }
        return self.upsert_one(key_col="id", key_val=session.id, payload=payload)

    def get(
        self,
        *,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> Session | None:
        row = self.get_one(id=session_id, app_name=app_name, user_id=user_id)
        if not row:
            return None
        return Session.model_validate(row["session_json"])

    def list(self, *, app_name: str, user_id: str | None = None) -> builtins.list[Session]:
        filters = {"app_name": app_name}
        if user_id:
            filters["user_id"] = user_id
        rows = _extract_list(
            self._client().select("session_json").eq("app_name", app_name).execute()
        ) if not user_id else _extract_list(
            self._client().select("session_json")
            .eq("app_name", app_name).eq("user_id", user_id).execute()
        )
        return [Session.model_validate(row["session_json"]) for row in rows]

    def delete(self, *, app_name: str, user_id: str, session_id: str) -> None:
        self.delete_where(id=session_id, app_name=app_name, user_id=user_id)
