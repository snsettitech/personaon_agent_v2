"""Tests for Phase II notification memory helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


TENANT_ID = "11111111-1111-4111-8111-111111111111"
RUN_ID = "22222222-2222-4222-8222-222222222222"
EVENT_ID = "33333333-3333-4333-8333-333333333333"


class FakeQuery:
    def __init__(self, client: FakeSupabase, table_name: str) -> None:
        self.client = client
        self.table_name = table_name
        self.action = "select"
        self.payload: dict[str, Any] | None = None
        self.filters: list[tuple[str, Any]] = []
        self.limit_count: int | None = None

    def select(self, columns: str) -> FakeQuery:
        self.action = "select"
        self.client.selects.append((self.table_name, columns))
        return self

    def insert(self, payload: dict[str, Any]) -> FakeQuery:
        self.action = "insert"
        self.payload = payload
        return self

    def update(self, payload: dict[str, Any]) -> FakeQuery:
        self.action = "update"
        self.payload = payload
        return self

    def eq(self, column: str, value: Any) -> FakeQuery:
        self.filters.append((column, value))
        return self

    def limit(self, count: int) -> FakeQuery:
        self.limit_count = count
        return self

    def execute(self) -> SimpleNamespace:
        self.client.queries.append(self)
        if self.action == "select":
            return SimpleNamespace(data=self.client.select_rows)
        if self.action == "insert":
            assert self.payload is not None
            row = {"id": "memory-inserted", **self.payload}
            self.client.inserted.append(row)
            return SimpleNamespace(data=[row])
        if self.action == "update":
            assert self.payload is not None
            row = {"id": "memory-updated", **self.payload}
            self.client.updated.append((self.filters, row))
            return SimpleNamespace(data=[row])
        raise AssertionError(f"unexpected action {self.action}")


class FakeRpc:
    def __init__(self, client: FakeSupabase, name: str, params: dict[str, Any]) -> None:
        self.client = client
        self.name = name
        self.params = params

    def execute(self) -> SimpleNamespace:
        self.client.rpc_calls.append((self.name, self.params))
        return SimpleNamespace(data=self.client.rpc_rows)


class FakeSupabase:
    def __init__(
        self,
        *,
        select_rows: list[dict[str, Any]] | None = None,
        rpc_rows: list[dict[str, Any]] | None = None,
    ) -> None:
        self.select_rows = select_rows or []
        self.rpc_rows = rpc_rows or []
        self.selects: list[tuple[str, str]] = []
        self.queries: list[FakeQuery] = []
        self.inserted: list[dict[str, Any]] = []
        self.updated: list[tuple[list[tuple[str, Any]], dict[str, Any]]] = []
        self.rpc_calls: list[tuple[str, dict[str, Any]]] = []

    def table(self, table_name: str) -> FakeQuery:
        return FakeQuery(self, table_name)

    def rpc(self, name: str, params: dict[str, Any]) -> FakeRpc:
        return FakeRpc(self, name, params)


def fake_embedding(text: str) -> list[float]:
    assert text
    return [0.125] * 768


def _outcome():
    from services.notification_memory import NotificationOutcomeMemory

    return NotificationOutcomeMemory(
        tenant_id=TENANT_ID,
        flow_run_id=RUN_ID,
        lifecycle_event_id=EVENT_ID,
        event_type="feature.launched",
        email_type="feature_launch",
        category="announcements",
        audience_label="beta users",
        subject="New timeline view",
        cta_label="Try it now",
        audience_count=100,
        open_count=52,
        click_count=17,
        conversion_count=9,
        open_rate=0.52,
        click_rate=0.17,
        conversion_rate=0.09,
    )


def test_compose_outcome_memory_is_human_readable():
    from services.notification_memory import compose_outcome_memory

    content = compose_outcome_memory(_outcome())

    assert "feature.launched notification" in content
    assert "audience=beta users" in content
    assert "open_rate=52.00%" in content
    assert "counts=52/17/9 of 100" in content


def test_remember_notification_outcome_inserts_agent_memory_row():
    from services.notification_memory import AGENT_SLUG, OUTCOME_KIND, remember_notification_outcome

    sb = FakeSupabase()
    row = remember_notification_outcome(sb, _outcome(), embed=fake_embedding)

    assert row["id"] == "memory-inserted"
    assert sb.inserted
    inserted = sb.inserted[0]
    assert inserted["agent_slug"] == AGENT_SLUG
    assert inserted["kind"] == OUTCOME_KIND
    assert inserted["tenant_id"] == TENANT_ID
    assert inserted["source_run_id"] == RUN_ID
    assert inserted["source_event_id"] == EVENT_ID
    assert inserted["meta"]["flow_run_id"] == RUN_ID
    assert inserted["embedding"] == [0.125] * 768


def test_remember_notification_outcome_updates_existing_source_run():
    from services.notification_memory import remember_notification_outcome

    sb = FakeSupabase(select_rows=[{"id": "existing-memory"}])
    row = remember_notification_outcome(sb, _outcome(), embed=fake_embedding)

    assert row["id"] == "memory-updated"
    assert not sb.inserted
    assert sb.updated
    filters, updated = sb.updated[0]
    assert ("id", "existing-memory") in filters
    assert updated["source_run_id"] == RUN_ID


def test_remember_notification_outcome_rejects_wrong_embedding_dimension():
    from services.notification_memory import remember_notification_outcome

    with pytest.raises(ValueError, match="768 dimensions"):
        remember_notification_outcome(FakeSupabase(), _outcome(), embed=lambda _text: [0.1])


def test_retrieve_prior_outcome_snippets_calls_match_agent_memory_rpc():
    from services.notification_memory import retrieve_prior_outcome_snippets

    sb = FakeSupabase(
        rpc_rows=[
            {
                "id": "memory-1",
                "content": "  Past result   had strong clicks after concise CTA.  ",
                "meta": {"flow_run_id": RUN_ID},
                "similarity": 0.91,
            },
            {
                "id": "memory-2",
                "content": "Second outcome was weaker with a vague subject.",
                "meta": {},
                "similarity": 0.82,
            },
        ],
    )

    snippets = retrieve_prior_outcome_snippets(
        sb,
        tenant_id=TENANT_ID,
        event_type="feature.launched",
        audience_label="beta users",
        category="announcements",
        limit=25,
        max_chars=40,
        embed=fake_embedding,
    )

    assert snippets == [
        "Past result had strong clicks after...",
        "Second outcome was weaker with a...",
    ]
    assert len(sb.rpc_calls) == 1
    name, params = sb.rpc_calls[0]
    assert name == "match_agent_memory"
    assert params["match_agent_slug"] == "notification_agent"
    assert params["match_kind"] == "outcome"
    assert params["match_count"] == 10
    assert params["match_tenant_id"] == TENANT_ID
    assert params["query_embedding"] == [0.125] * 768
