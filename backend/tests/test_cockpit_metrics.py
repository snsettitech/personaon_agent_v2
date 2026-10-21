"""Tests for modules/cockpit_metrics.py — summary assembly."""
from __future__ import annotations

import modules.cockpit_metrics as cm


def test_get_summary_structure(monkeypatch) -> None:
    monkeypatch.setattr(cm, "get_supabase_client", lambda: object())
    monkeypatch.setattr(cm, "_count", lambda sb, table, **kw: 5)

    s = cm.get_summary()
    assert s["users"]["total"] == 5
    assert s["twins"]["active"] == 5
    assert set(s.keys()) == {"users", "twins", "conversations", "leads"}


def test_plan_distribution(monkeypatch) -> None:
    monkeypatch.setattr(cm, "get_supabase_client", lambda: object())
    monkeypatch.setattr(cm, "_count", lambda sb, table, **kw: 3)

    dist = cm.get_plan_distribution()
    assert dist == {"free": 3, "pro": 3, "business": 3, "believer": 3}
