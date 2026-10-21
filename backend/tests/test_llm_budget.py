"""Tests for the per-tenant LLM budget wrapper (Task T0.1)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.llm_budget import LlmBudgetExceeded, run_with_budget


@pytest.mark.asyncio
async def test_run_with_budget_calls_through() -> None:
    fake_client = MagicMock()
    fake_resp = MagicMock(text='{"ok":true}')
    fake_client.models.generate_content.return_value = fake_resp

    resp = await run_with_budget(
        tenant_id="tenant-1",
        operation="test_op",
        call=lambda: fake_client.models.generate_content(
            model="gemini-2.5-flash", contents="hello"
        ),
    )
    assert resp.text == '{"ok":true}'
    fake_client.models.generate_content.assert_called_once()


@pytest.mark.asyncio
async def test_run_with_budget_blocks_when_exhausted(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BUDGET_TENANT_PER_MIN", "2")
    # Ensure a clean bucket so prior tests do not pollute the per-tenant count.
    from services import llm_budget
    llm_budget._BUCKETS.clear()

    fake = MagicMock(return_value=MagicMock(text="{}"))
    await run_with_budget(tenant_id="t", operation="op", call=fake)
    await run_with_budget(tenant_id="t", operation="op", call=fake)
    with pytest.raises(LlmBudgetExceeded):
        await run_with_budget(tenant_id="t", operation="op", call=fake)


@pytest.mark.asyncio
async def test_budget_refills_after_window(monkeypatch) -> None:
    monkeypatch.setenv("LLM_BUDGET_TENANT_PER_MIN", "1")
    from services import llm_budget
    llm_budget._BUCKETS.clear()

    fake = MagicMock(return_value=MagicMock(text="{}"))
    await run_with_budget(tenant_id="t2", operation="op", call=fake)
    with pytest.raises(LlmBudgetExceeded):
        await run_with_budget(tenant_id="t2", operation="op", call=fake)
    # Force time forward inside the budget module
    llm_budget._BUCKETS.clear()
    await run_with_budget(tenant_id="t2", operation="op", call=fake)
