"""Shared chained MagicMock builder for Supabase client tests.

Usage:
  from tests._supabase_mock import fluent, result
"""
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock


def result(data: Any) -> SimpleNamespace:
    return SimpleNamespace(data=data, count=len(data) if isinstance(data, list) else None)


def fluent(return_data: Any) -> MagicMock:
    m = MagicMock()
    for name in (
        "table", "select", "eq", "neq", "ilike", "in_", "is_", "not_",
        "lt", "order", "limit", "insert", "update", "delete", "single",
        "maybe_single", "upsert", "rpc",
    ):
        getattr(m, name).return_value = m
    m.execute.return_value = result(return_data)
    return m
