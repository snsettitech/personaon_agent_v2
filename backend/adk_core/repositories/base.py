"""Shared repository helpers and base class for Supabase CRUD."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact_dict(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def is_empty_lookup_error(exc: Exception) -> bool:
    code = str(getattr(exc, "code", "") or "").strip()
    message = str(exc)
    return code in {"204", "404", "406"} or "Missing response" in message


def _extract_one(response: Any) -> dict[str, Any] | None:
    """Extract a single row from a Supabase response, or None."""
    data = response.data if response else None
    return (data or [None])[0]


def _extract_list(response: Any) -> list[dict[str, Any]]:
    """Extract a list of rows from a Supabase response."""
    return (response.data if response else None) or []


class BaseRepository:
    """Generic Supabase CRUD operations to reduce boilerplate.

    Subclasses set `table_name` and add domain-specific methods.
    """

    table_name: str = ""

    def _client(self):
        from modules.observability import supabase
        return supabase.table(self.table_name)

    def get_one(self, **filters: Any) -> dict[str, Any] | None:
        """Single-record lookup with standardized error handling."""
        query = self._client().select("*")
        for col, val in filters.items():
            if val is not None:
                query = query.eq(col, val)
        try:
            resp = query.maybe_single().execute()
        except Exception as exc:
            if is_empty_lookup_error(exc):
                return None
            raise
        return (resp.data if resp else None) or None

    def get_one_fields(self, fields: str, **filters: Any) -> dict[str, Any] | None:
        """Single-record lookup with specific fields."""
        query = self._client().select(fields)
        for col, val in filters.items():
            if val is not None:
                query = query.eq(col, val)
        try:
            resp = query.maybe_single().execute()
        except Exception as exc:
            if is_empty_lookup_error(exc):
                return None
            raise
        return (resp.data if resp else None) or None

    def list_many(
        self,
        *,
        filters: dict[str, Any] | None = None,
        order_by: str = "created_at",
        desc: bool = True,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List records with optional filters, ordering, and limit."""
        query = self._client().select("*")
        for col, val in (filters or {}).items():
            if val is not None:
                query = query.eq(col, val)
        return _extract_list(query.order(order_by, desc=desc).limit(limit).execute())

    def insert_one(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Insert a single row with automatic timestamps."""
        now = utc_now_iso()
        row = compact_dict({**payload, "created_at": now, "updated_at": now})
        return _extract_one(self._client().insert(row).execute())

    def update_one(self, key_col: str, key_val: Any, **updates: Any) -> dict[str, Any] | None:
        """Update a single row by key with automatic updated_at."""
        payload = compact_dict({**updates, "updated_at": utc_now_iso()})
        return _extract_one(
            self._client().update(payload).eq(key_col, key_val).execute()
        )

    def upsert_one(self, *, key_col: str, key_val: Any, payload: dict[str, Any]) -> dict[str, Any]:
        """Upsert: check existence, then insert or update."""
        existing = self.get_one_fields("id", **{key_col: key_val})
        if existing:
            return self.update_one(key_col, key_val, **payload)
        return self.insert_one({key_col: key_val, **payload})

    def delete_where(self, **filters: Any) -> None:
        """Delete rows matching all filters."""
        query = self._client().delete()
        for col, val in filters.items():
            query = query.eq(col, val)
        query.execute()
