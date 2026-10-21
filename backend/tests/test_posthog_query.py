"""Tests for modules/posthog_query.py — graceful degradation + parsing."""
from __future__ import annotations

import modules.posthog_query as pq


def test_not_configured_returns_none(monkeypatch) -> None:
    monkeypatch.delenv("POSTHOG_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("POSTHOG_PROJECT_ID", raising=False)
    assert pq.is_configured() is False
    assert pq.run_hogql("SELECT 1") is None
    assert pq.get_dau() is None


def test_scalar_parsing() -> None:
    assert pq._scalar([[123]]) == 123
    assert pq._scalar(None) is None
    assert pq._scalar([[]]) is None
    assert pq._scalar([["not-a-number"]]) is None


def test_get_active_users_uses_run_hogql(monkeypatch) -> None:
    monkeypatch.setattr(pq, "run_hogql", lambda q: [[42]])
    assert pq.get_active_users(30) == 42
