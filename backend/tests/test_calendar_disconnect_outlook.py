"""Tests for the generalized disconnect_calendar endpoint (provider param)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeSupabaseChain:
    """Minimal chain mock that records every .eq() call so we can verify scoping."""

    def __init__(self, execute_results: list[Any]) -> None:
        self._execute_results = list(execute_results)
        self.eq_calls: list[tuple] = []
        self.deleted: bool = False

    def table(self, _name: str) -> "_FakeSupabaseChain":
        return self

    def select(self, *_args: Any, **_kwargs: Any) -> "_FakeSupabaseChain":
        return self

    def update(self, _payload: dict) -> "_FakeSupabaseChain":
        return self

    def delete(self) -> "_FakeSupabaseChain":
        self.deleted = True
        return self

    def eq(self, *args: Any, **_kwargs: Any) -> "_FakeSupabaseChain":
        self.eq_calls.append(args)
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> "_FakeSupabaseChain":
        return self

    def execute(self) -> Any:
        if not self._execute_results:
            return MagicMock(data=None)
        return self._execute_results.pop(0)


@pytest.mark.asyncio
async def test_disconnect_outlook_selects_microsoft_outlook_connector() -> None:
    """provider='microsoft' must query connector_type='microsoft_outlook'."""
    from routers import calendar_booking

    fake_sb = _FakeSupabaseChain(execute_results=[
        MagicMock(data=[{"id": "row-1", "recall_calendar_id": "cal_msft"}]),
        MagicMock(data=None),
    ])

    with (
        patch.object(calendar_booking, "get_supabase_client", return_value=fake_sb),
        patch.object(calendar_booking, "verify_twin_ownership"),
        patch(
            "services.recall_calendar_v2.disconnect_calendar",
            new_callable=AsyncMock,
        ) as mock_disconnect,
    ):
        result = await calendar_booking.disconnect_calendar(
            twin_id="twin-abc",
            provider="microsoft",
            user={"user_id": "u1", "tenant_id": "t1"},
        )

    # SELECT must have been scoped to microsoft_outlook, not google_calendar.
    flat_eq = [a for entry in fake_sb.eq_calls for a in entry]
    assert "microsoft_outlook" in flat_eq, (
        f"disconnect must SELECT connector_type=microsoft_outlook when "
        f"provider='microsoft'; got eq calls: {fake_sb.eq_calls}"
    )
    assert "google_calendar" not in flat_eq, (
        f"google_calendar must not appear in the eq calls when disconnecting Outlook; "
        f"got: {fake_sb.eq_calls}"
    )

    # Recall side still gets the disconnect call.
    mock_disconnect.assert_awaited_once_with("cal_msft")
    assert fake_sb.deleted is True
    assert result["status"] == "disconnected"
    assert result["provider"] == "microsoft_outlook"


@pytest.mark.asyncio
async def test_disconnect_rejects_unknown_provider() -> None:
    """provider='xyz' (typo or future provider) must 400."""
    from fastapi import HTTPException
    from routers import calendar_booking

    with patch.object(calendar_booking, "verify_twin_ownership"):
        with pytest.raises(HTTPException) as exc:
            await calendar_booking.disconnect_calendar(
                twin_id="twin-abc",
                provider="dropbox-paper",
                user={"user_id": "u1", "tenant_id": "t1"},
            )

    assert exc.value.status_code == 400
    assert "provider" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_disconnect_provider_aliases_accepted() -> None:
    """Alias provider values are normalized to canonical connector_type."""
    from routers import calendar_booking

    # Test each alias by invoking disconnect and checking the SELECT scope.
    cases = [
        ("google", "google_calendar"),
        ("google_calendar", "google_calendar"),
        ("microsoft", "microsoft_outlook"),
        ("outlook", "microsoft_outlook"),
        ("microsoft_outlook", "microsoft_outlook"),
    ]

    for alias, expected_connector_type in cases:
        fake_sb = _FakeSupabaseChain(execute_results=[
            MagicMock(data=[{"id": "row-1", "recall_calendar_id": None}]),
            MagicMock(data=None),
        ])

        with (
            patch.object(calendar_booking, "get_supabase_client", return_value=fake_sb),
            patch.object(calendar_booking, "verify_twin_ownership"),
            patch(
                "services.recall_calendar_v2.disconnect_calendar",
                new_callable=AsyncMock,
            ),
        ):
            await calendar_booking.disconnect_calendar(
                twin_id="twin-abc",
                provider=alias,
                user={"user_id": "u1", "tenant_id": "t1"},
            )

        flat_eq = [a for entry in fake_sb.eq_calls for a in entry]
        assert expected_connector_type in flat_eq, (
            f"alias {alias!r} must resolve to connector_type "
            f"{expected_connector_type!r}; got eq calls: {fake_sb.eq_calls}"
        )
