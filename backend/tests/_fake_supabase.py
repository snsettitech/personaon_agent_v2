"""Schema-aware Supabase test double.

Why this exists
---------------
The original ``twins.user_id`` 42703 production bug went undetected for weeks
because the unit test mocked ``data = {"user_id": ...}`` even though the column
does not exist on the production schema. Real Supabase raised
``42703 column twins.user_id does not exist`` on every chat; the
``unittest.mock.MagicMock`` cheerfully returned whatever shape the code asked
for, so CI was green while production was silently dropping every metering
increment.

What this provides
------------------
A drop-in fake that validates two things at test time:

1. **Mocked rows** can only contain columns that exist in the production schema
   for that table. Setting ``set_row("twins", {"user_id": "..."})`` raises
   immediately, so a future copy-paste of the original buggy mock fails fast.
2. **SELECT clauses** can only request columns that exist. ``.select("user_id")``
   on ``twins`` raises a ``Postgres42703Error`` that mimics the real DB error.

Schema source-of-truth
----------------------
``PRODUCTION_SCHEMA`` is hand-curated from production REST introspection on
2026-05-01. To refresh, query ``information_schema.columns`` against the
production Supabase project (``<project-ref>``) and update this file —
or add a CI job that diffs this dict against the live schema and fails.

The fake is **opt-in**. Existing tests that use raw ``MagicMock`` keep working
unchanged; new and migrated tests use ``FakeSupabase`` to get column-shape
validation for free.

Usage
-----
::

    from tests._fake_supabase import FakeSupabase

    sb = FakeSupabase()
    sb.table("twins").set_row(twin_id="t1", settings={"owner_user_id": "u1"})

    with patch("modules.observability.get_supabase_client", return_value=sb):
        result = get_twin_owner_id("t1")
    assert result == "u1"

If the code under test does ``select("user_id")`` against ``twins``, the fake
raises ``Postgres42703Error`` — which is exactly what real Supabase does.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Production schema snapshot
# ---------------------------------------------------------------------------
# Snapshot taken 2026-05-01 from production Supabase
# (project <project-ref>) via REST introspection. Refresh by running
# ``select column_name from information_schema.columns where table_name='X'``
# against production and updating this dict.
#
# Tables not listed here can still be used via ``set_row`` / ``select`` but
# without validation — those calls fall back to MagicMock-equivalent behavior.
# Add a table here when you migrate its tests to use FakeSupabase.

PRODUCTION_SCHEMA: dict[str, frozenset[str]] = {
    "twins": frozenset({
        "id",
        "name",
        "description",
        "status",
        "settings",
        "creator_id",
        "tenant_id",
        "creation_mode",
        "is_verified",
        "verification_status",
        "specialization",
        "specialization_id",
        "specialization_version",
        "created_at",
    }),
    "users": frozenset({
        "id",
        "email",
        "plan",
        "tenant_id",
        "role",
        "stripe_customer_id",
        "trial_kind",
        "trial_ends_at",
        "no_card_trial_used_at",
        "messages_this_period",
        "voice_minutes_this_period",
        "period_started_at",
        "avatar_url",
        "invitation_id",
        "invited_at",
        "last_active_at",
        "dashboard_walkthrough_completed_at",
        "created_at",
    }),
    # Production-verified `sources` schema (snapshot 2026-05-01). The
    # historical migrations under backend/database/migrations/ declare
    # additional columns (status, citation_url, created_at, etc.), but the
    # live database only exposes these five — selecting any others raises
    # 42703. See modules/training_metrics.py for the bug this caught.
    "sources": frozenset({
        "id",
        "twin_id",
        "filename",
        "file_url",
        "content_text",
    }),
}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class Postgres42703Error(RuntimeError):
    """Mimics PostgREST's ``42703 column X does not exist``.

    Real Supabase returns this when a SELECT references a missing column.
    Production code typically catches it as a bare Exception (which is part
    of why the original bug stayed silent). The fake raises it eagerly so
    tests fail at the SELECT call site instead of returning a happy answer
    that lies.
    """


class FakeSupabaseSchemaError(AssertionError):
    """Raised when a test sets a row containing a non-existent column.

    Distinct from ``Postgres42703Error`` so test authors can tell whether
    the failure came from the code under test (42703) or from their own
    test fixture (schema error).
    """


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------


@dataclass
class _ExecuteResult:
    """Mimics the ``execute()`` return shape from supabase-py."""

    data: Any = None
    count: int | None = None


# ---------------------------------------------------------------------------
# Query builder (chainable)
# ---------------------------------------------------------------------------


def _parse_columns(select_arg: str | None) -> list[str]:
    """Split a select clause like 'a, b, c' into ['a', 'b', 'c']. '*' → []."""
    if not select_arg or select_arg.strip() == "*":
        return []
    return [c.strip() for c in select_arg.split(",") if c.strip()]


@dataclass
class _Query:
    """Chainable query builder over a single table's rows.

    Implements the surface used in production code:
    ``.select().eq().neq().in_().limit().single().maybe_single().execute()``.
    Order is not enforced — calls accumulate state, ``execute()`` resolves.
    """

    table_name: str
    rows: list[dict[str, Any]]
    schema: frozenset[str] | None
    _select_columns: list[str] = field(default_factory=list)
    _filters: list[tuple[str, str, Any]] = field(default_factory=list)
    _limit: int | None = None
    _single: bool = False
    _maybe_single: bool = False

    # SELECT validation
    def select(self, columns: str = "*", **_kwargs: Any) -> "_Query":
        cols = _parse_columns(columns)
        if self.schema is not None and cols:
            unknown = [c for c in cols if c not in self.schema]
            if unknown:
                raise Postgres42703Error(
                    f"column {self.table_name}.{unknown[0]} does not exist "
                    f"(test mock validated against production schema snapshot; "
                    f"unknown columns in select: {unknown})"
                )
        self._select_columns = cols
        return self

    # Filter operators (we don't actually filter; we just track that they were called)
    def eq(self, column: str, value: Any) -> "_Query":
        self._validate_column(column)
        self._filters.append(("eq", column, value))
        return self

    def neq(self, column: str, value: Any) -> "_Query":
        self._validate_column(column)
        self._filters.append(("neq", column, value))
        return self

    def in_(self, column: str, values: Any) -> "_Query":
        self._validate_column(column)
        self._filters.append(("in_", column, values))
        return self

    def limit(self, n: int) -> "_Query":
        self._limit = n
        return self

    def single(self) -> "_Query":
        self._single = True
        return self

    def maybe_single(self) -> "_Query":
        self._maybe_single = True
        return self

    # Mutations — not validating writes here, just accepting them silently
    # so tests that don't care about writes don't have to mock them.
    def update(self, _values: dict[str, Any]) -> "_Query":
        return self

    def insert(self, _values: dict[str, Any] | list[dict[str, Any]]) -> "_Query":
        return self

    def upsert(self, _values: dict[str, Any], **_kwargs: Any) -> "_Query":
        return self

    def execute(self) -> _ExecuteResult:
        rows = self._apply_filters()
        if self._select_columns:
            rows = [self._project_row(r) for r in rows]
        if self._single or self._maybe_single:
            return _ExecuteResult(data=rows[0] if rows else None)
        return _ExecuteResult(data=rows)

    # Helpers
    def _validate_column(self, column: str) -> None:
        if self.schema is not None and column not in self.schema:
            raise Postgres42703Error(
                f"column {self.table_name}.{column} does not exist "
                f"(filter on unknown column)"
            )

    def _apply_filters(self) -> list[dict[str, Any]]:
        result = list(self.rows)
        for op, col, val in self._filters:
            if op == "eq":
                result = [r for r in result if r.get(col) == val]
            elif op == "neq":
                result = [r for r in result if r.get(col) != val]
            elif op == "in_":
                result = [r for r in result if r.get(col) in val]
        if self._limit is not None:
            result = result[: self._limit]
        return result

    def _project_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {k: row.get(k) for k in self._select_columns}


# ---------------------------------------------------------------------------
# Table accessor
# ---------------------------------------------------------------------------


@dataclass
class _Table:
    """Per-table accessor — holds rows + schema, hands out _Query builders."""

    name: str
    schema: frozenset[str] | None
    _rows: list[dict[str, Any]] = field(default_factory=list)

    def set_row(self, **fields: Any) -> dict[str, Any]:
        """Add (or upsert by ``id``) a row. Validates fields against schema.

        Convenience wrapper for the common case of "I want one row in this
        table." Pass column values as kwargs. Raises ``FakeSupabaseSchemaError``
        if any field isn't in the table's schema (when validation is enabled).
        """
        if self.schema is not None:
            unknown = [k for k in fields if k not in self.schema]
            if unknown:
                raise FakeSupabaseSchemaError(
                    f"test set_row on '{self.name}' with unknown columns "
                    f"{unknown}; production schema only allows "
                    f"{sorted(self.schema)}. If this column is real, update "
                    f"PRODUCTION_SCHEMA in tests/_fake_supabase.py."
                )
        row_id = fields.get("id")
        if row_id is not None:
            for i, existing in enumerate(self._rows):
                if existing.get("id") == row_id:
                    self._rows[i] = dict(fields)
                    return self._rows[i]
        new_row = dict(fields)
        self._rows.append(new_row)
        return new_row

    def set_rows(self, rows: list[dict[str, Any]]) -> None:
        """Replace all rows in this table."""
        if self.schema is not None:
            for r in rows:
                unknown = [k for k in r if k not in self.schema]
                if unknown:
                    raise FakeSupabaseSchemaError(
                        f"test set_rows on '{self.name}' with unknown "
                        f"columns {unknown} in row {r}"
                    )
        self._rows = [dict(r) for r in rows]

    # Forward query-builder calls so test code that drives the mock the same
    # way production code drives Supabase still works.
    def select(self, columns: str = "*", **kwargs: Any) -> _Query:
        return self._query().select(columns, **kwargs)

    def update(self, values: dict[str, Any]) -> _Query:
        return self._query().update(values)

    def insert(self, values: dict[str, Any] | list[dict[str, Any]]) -> _Query:
        return self._query().insert(values)

    def upsert(self, values: dict[str, Any], **kwargs: Any) -> _Query:
        return self._query().upsert(values, **kwargs)

    def _query(self) -> _Query:
        return _Query(table_name=self.name, rows=list(self._rows), schema=self.schema)


# ---------------------------------------------------------------------------
# Top-level fake client
# ---------------------------------------------------------------------------


class FakeSupabase:
    """Drop-in stand-in for ``supabase.Client`` in tests.

    Each ``.table(name)`` returns a stateful per-table accessor that can hold
    rows. SELECTs and column-name filters are validated against
    ``PRODUCTION_SCHEMA``; setting rows with non-existent columns raises.

    For a one-off test, just instantiate, set rows, and patch
    ``modules.observability.get_supabase_client`` (or whatever your code calls
    to obtain the client) to return the fake.
    """

    def __init__(self, schema: dict[str, frozenset[str]] | None = None) -> None:
        self._schema = schema if schema is not None else PRODUCTION_SCHEMA
        self._tables: dict[str, _Table] = {}

    def table(self, name: str) -> _Table:
        if name not in self._tables:
            self._tables[name] = _Table(
                name=name,
                schema=self._schema.get(name),  # None → validation disabled
            )
        return self._tables[name]

    def from_(self, name: str) -> _Table:
        # supabase-py exposes both `.table()` and `.from_()`; alias for parity.
        return self.table(name)
