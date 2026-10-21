"""PR3 tests — D10 queue_question->conversation linkage (FK-safe) + D11 enriched alert."""
import pytest
from unittest.mock import MagicMock, patch


# ── D10: queue_question links only when the adk_conversations row exists ───────

def _queue_sb(conv_exists: bool):
    """sb where table('adk_conversations') existence check resolves per `conv_exists`,
    and queued_questions dedup returns empty (forcing the insert path)."""
    conv_tbl = MagicMock()
    (
        conv_tbl.select.return_value.eq.return_value
        .maybe_single.return_value.execute.return_value
    ) = MagicMock(data={"id": "conv-1"} if conv_exists else None)

    qq_tbl = MagicMock()
    (
        qq_tbl.select.return_value.eq.return_value.eq.return_value.eq.return_value
        .gte.return_value.execute.return_value
    ) = MagicMock(data=[])
    qq_tbl.insert.return_value.execute.return_value = MagicMock(data=[{"id": "qq-1"}])

    sb = MagicMock()
    sb.table.side_effect = lambda name: conv_tbl if name == "adk_conversations" else qq_tbl
    return sb, qq_tbl


@pytest.mark.asyncio
async def test_queue_question_links_when_conversation_exists():
    sb, qq_tbl = _queue_sb(conv_exists=True)
    with patch("adk_core.tools.capture_tools.get_supabase_client", return_value=sb):
        from adk_core.tools.capture_tools import _make_queue_tool
        tool = _make_queue_tool(twin_id="t1", conversation_id="conv-1", visitor_user_id="v1", tenant_id="tn1")
        await tool.func(question="do you do backend?", topic="backend")
    inserted = qq_tbl.insert.call_args[0][0]
    assert inserted["conversation_id"] == "conv-1"


@pytest.mark.asyncio
async def test_queue_question_null_when_conversation_missing():
    sb, qq_tbl = _queue_sb(conv_exists=False)
    with patch("adk_core.tools.capture_tools.get_supabase_client", return_value=sb):
        from adk_core.tools.capture_tools import _make_queue_tool
        tool = _make_queue_tool(twin_id="t1", conversation_id="conv-x", visitor_user_id="v1", tenant_id="tn1")
        await tool.func(question="do you do Y?", topic="Y")
    inserted = qq_tbl.insert.call_args[0][0]
    assert inserted["conversation_id"] is None  # FK-safe fallback, no dangling reference


# ── D11: hot-lead alert carries inferred intent + 'why this matters' ──────────

def test_hot_lead_alert_includes_inferred_intent():
    leads_tbl = MagicMock()
    (
        leads_tbl.select.return_value.eq.return_value.eq.return_value
        .maybe_single.return_value.execute.return_value
    ) = MagicMock(data={
        "id": "lead-1", "twin_id": "t1", "visitor_email": "jo@fund.vc",
        "source_domain": "linkedin.com", "conversation_id": "conv-1",
        "inferred_visitor_type": "investor", "inferred_intent": "seed round",
    })
    twins_tbl = MagicMock()
    (
        twins_tbl.select.return_value.eq.return_value
        .maybe_single.return_value.execute.return_value
    ) = MagicMock(data={"id": "t1", "tenant_id": "tn1", "name": "Sainath"})
    users_tbl = MagicMock()
    (
        users_tbl.select.return_value.eq.return_value.limit.return_value.execute.return_value
    ) = MagicMock(data=[{"id": "u1", "email": "owner@example.com"}])

    sb = MagicMock()
    sb.table.side_effect = lambda name: {
        "widget_leads": leads_tbl, "twins": twins_tbl, "users": users_tbl,
    }.get(name, MagicMock())

    captured = {}
    gob = MagicMock()
    gob.submit.side_effect = lambda **kw: captured.update(kw) or "job-1"

    with (
        patch("modules.observability.get_supabase_client", return_value=sb),
        patch("modules.graph_outbox.get_graph_outbox", return_value=gob),
    ):
        from services.lifecycle_email_service import enqueue_hot_lead_alert
        job = enqueue_hot_lead_alert(twin_id="t1", lead_id="lead-1")

    assert job == "job-1"
    metrics = " ".join(captured["payload"]["payload"]["metrics"])
    assert "investor" in metrics
    assert "seed round" in metrics
    assert "Why this matters" in metrics
    assert "conv-1" in metrics  # transcript reference


# ── D10 dedup: existing pending question increments ask_count (no duplicate row) ──

@pytest.mark.asyncio
async def test_queue_question_dedup_increments_ask_count():
    conv_tbl = MagicMock()
    (
        conv_tbl.select.return_value.eq.return_value
        .maybe_single.return_value.execute.return_value
    ) = MagicMock(data=None)  # no conversation row -> linkage NULL (irrelevant here)
    qq_tbl = MagicMock()
    (
        qq_tbl.select.return_value.eq.return_value.eq.return_value.eq.return_value
        .gte.return_value.execute.return_value
    ) = MagicMock(data=[{"id": "qq-1", "ask_count": 2}])  # existing pending row
    sb = MagicMock()
    sb.table.side_effect = lambda name: conv_tbl if name == "adk_conversations" else qq_tbl

    with patch("adk_core.tools.capture_tools.get_supabase_client", return_value=sb):
        from adk_core.tools.capture_tools import _make_queue_tool
        tool = _make_queue_tool(twin_id="t1", conversation_id="conv-x", visitor_user_id="v1", tenant_id="tn1")
        await tool.func(question="how much again?", topic="pricing")

    qq_tbl.update.assert_called_once()
    assert qq_tbl.update.call_args[0][0]["ask_count"] == 3
    qq_tbl.insert.assert_not_called()  # dedup -> no duplicate pending row
