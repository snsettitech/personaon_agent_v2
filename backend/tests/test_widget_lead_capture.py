"""Tests for capture_lead_contact tool — email normalisation and DB write."""
import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_capture_lead_contact_clean_email():
    """Standard email address is stored lowercased."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "lead-1"}])

    with (
        patch("adk_core.tools.capture_tools.get_supabase_client", return_value=mock_sb),
        patch("services.lifecycle_email_service.enqueue_hot_lead_alert") as mock_enqueue,
    ):
        from adk_core.tools.capture_tools import _make_capture_lead_tool
        tool = _make_capture_lead_tool(twin_id="twin-1", lead_id="lead-1")
        fn = tool.func
        result = await fn(email="John@Acme.com")

    assert result["status"] == "captured"
    update_call = mock_sb.table.return_value.update.call_args[0][0]
    assert update_call["visitor_email"] == "john@acme.com"
    assert update_call["offer_state"] == "email_captured"
    mock_enqueue.assert_called_once_with(twin_id="twin-1", lead_id="lead-1")


@pytest.mark.asyncio
async def test_capture_lead_contact_spelled_out_email():
    """Spelled-out email variants are normalised before storing."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "lead-1"}])

    with (
        patch("adk_core.tools.capture_tools.get_supabase_client", return_value=mock_sb),
        patch("services.lifecycle_email_service.enqueue_hot_lead_alert"),
    ):
        from adk_core.tools.capture_tools import _make_capture_lead_tool
        tool = _make_capture_lead_tool(twin_id="twin-1", lead_id="lead-1")
        fn = tool.func
        result = await fn(email="john at acme dot com")

    assert result["status"] == "captured"
    update_call = mock_sb.table.return_value.update.call_args[0][0]
    assert update_call["visitor_email"] == "john@acme.com"


@pytest.mark.asyncio
async def test_capture_lead_contact_invalid_email():
    """Invalid email returns error status without writing to DB."""
    mock_sb = MagicMock()

    with (
        patch("adk_core.tools.capture_tools.get_supabase_client", return_value=mock_sb),
        patch("services.lifecycle_email_service.enqueue_hot_lead_alert") as mock_enqueue,
    ):
        from adk_core.tools.capture_tools import _make_capture_lead_tool
        tool = _make_capture_lead_tool(twin_id="twin-1", lead_id="lead-1")
        fn = tool.func
        result = await fn(email="not-an-email")

    assert result["status"] == "invalid"
    mock_sb.table.assert_not_called()
    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_capture_lead_contact_stores_name():
    """Name is stored alongside email when provided."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "lead-1"}])

    with (
        patch("adk_core.tools.capture_tools.get_supabase_client", return_value=mock_sb),
        patch("services.lifecycle_email_service.enqueue_hot_lead_alert"),
    ):
        from adk_core.tools.capture_tools import _make_capture_lead_tool
        tool = _make_capture_lead_tool(twin_id="twin-1", lead_id="lead-1")
        fn = tool.func
        result = await fn(email="sarah@startup.io", name="  Sarah Chen  ")

    assert result["status"] == "captured"
    update_call = mock_sb.table.return_value.update.call_args[0][0]
    assert update_call["visitor_name"] == "Sarah Chen"


# ── Prompt block tests ────────────────────────────────────────────────────────

def test_generate_system_prompt_visitor_unchanged():
    """Visitor surface prompt is identical regardless of lead_context param."""
    from adk_core.services.prompts import generate_system_prompt
    profile = {"name": "Alex", "bio": "engineer"}
    prompt_before = generate_system_prompt(profile, surface_class="visitor")
    prompt_after = generate_system_prompt(profile, surface_class="visitor", lead_context=None)
    assert prompt_before == prompt_after
    assert "capture_lead_contact" not in prompt_before
    assert "WIDGET" not in prompt_before


def test_generate_system_prompt_owner_unchanged():
    """Owner surface prompt is identical regardless of lead_context param."""
    from adk_core.services.prompts import generate_system_prompt
    profile = {"name": "Alex", "bio": "engineer"}
    prompt_before = generate_system_prompt(profile, surface_class="owner")
    prompt_after = generate_system_prompt(profile, surface_class="owner", lead_context=None)
    assert prompt_before == prompt_after
    assert "capture_lead_contact" not in prompt_before


def test_generate_system_prompt_widget_lead_turn_2_no_instructions():
    """Below turn-3 floor: no lead capture instructions emitted."""
    from adk_core.services.prompts import generate_system_prompt
    profile = {"name": "Sainath", "bio": "founder"}
    lead_context = {"lead_capture_enabled": True, "offer_state": "not_yet_offered", "turn_count": 2, "persona_name": "Sainath"}
    prompt = generate_system_prompt(profile, surface_class="widget_lead", lead_context=lead_context)
    assert "capture_lead_contact" not in prompt
    assert "WHEN TO OFFER" not in prompt


def test_generate_system_prompt_widget_lead_turn_4_has_instructions():
    """Turn 4+: full lead capture instructions present."""
    from adk_core.services.prompts import generate_system_prompt
    profile = {"name": "Sainath", "bio": "founder"}
    lead_context = {"lead_capture_enabled": True, "offer_state": "not_yet_offered", "turn_count": 4, "persona_name": "Sainath"}
    prompt = generate_system_prompt(profile, surface_class="widget_lead", lead_context=lead_context)
    assert "capture_lead_contact" in prompt
    assert "WHEN TO OFFER" in prompt
    assert "Sainath" in prompt


def test_generate_system_prompt_widget_lead_already_offered():
    """State injection prevents re-asking after offer was already made."""
    from adk_core.services.prompts import generate_system_prompt
    profile = {"name": "Sainath", "bio": "founder"}
    lead_context = {"lead_capture_enabled": True, "offer_state": "already_offered", "turn_count": 6, "persona_name": "Sainath"}
    prompt = generate_system_prompt(profile, surface_class="widget_lead", lead_context=lead_context)
    assert "Do NOT offer again" in prompt


def test_generate_system_prompt_widget_lead_email_captured():
    """State injection shows email and blocks further asks."""
    from adk_core.services.prompts import generate_system_prompt
    profile = {"name": "Sainath", "bio": "founder"}
    lead_context = {"lead_capture_enabled": True, "offer_state": "email_captured", "email": "john@acme.com", "turn_count": 8, "persona_name": "Sainath"}
    prompt = generate_system_prompt(profile, surface_class="widget_lead", lead_context=lead_context)
    assert "john@acme.com" in prompt
    assert "Do NOT ask for contact info again" in prompt


@pytest.mark.asyncio
async def test_capture_lead_contact_idempotent_when_already_captured():
    """Idempotency guard: if the lead's widget_leads row already has
    offer_state='email_captured', calling capture_lead_contact again is a
    read-only short-circuit - no UPDATE, no notification enqueues, no
    ph_capture telemetry fired a second time."""
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value = MagicMock(
        data={"offer_state": "email_captured"}
    )

    with (
        patch("adk_core.tools.capture_tools.get_supabase_client", return_value=mock_sb),
        patch("services.lifecycle_email_service.enqueue_hot_lead_alert") as mock_hot_lead,
        patch("services.lifecycle_email_service.enqueue_visitor_confirmation") as mock_visitor_confirm,
        patch("modules.posthog_analytics.ph_capture") as mock_ph_capture,
    ):
        from adk_core.tools.capture_tools import _make_capture_lead_tool
        tool = _make_capture_lead_tool(twin_id="twin-1", lead_id="lead-1")
        fn = tool.func
        result = await fn(email="john@acme.com")

    assert result == {"status": "captured", "message": "Contact info saved."}
    mock_sb.table.return_value.update.assert_not_called()
    mock_hot_lead.assert_not_called()
    mock_visitor_confirm.assert_not_called()
    mock_ph_capture.assert_not_called()
