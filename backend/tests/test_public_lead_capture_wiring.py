"""PR1 wiring tests — public-page conversational lead capture (surface=public_lead).

Guards the OFF-by-default inertness and the new public-capture wiring:
- _surface_class('public_lead') maps to its own class; other surfaces unchanged.
- _get_or_create_lead(key_id=None) omits api_key_id (public lead = NULL), while a
  real key_id (widget) still sets it.
- _public_capture_enabled is fail-safe OFF (missing/non-bool/error -> False).
- generate_system_prompt fires the offer block for public_lead (and not for the
  capture-disabled 'visitor' surface that public maps to when the flag is off).
"""
from unittest.mock import MagicMock, patch


# ── _surface_class ────────────────────────────────────────────────────────────

def test_surface_class_public_lead():
    from adk_core.services.agent_service import _surface_class
    assert _surface_class("public_lead") == "public_lead"
    # Capture-disabled / other surfaces are unchanged.
    assert _surface_class("public") == "visitor"
    assert _surface_class("widget") == "visitor"
    assert _surface_class("widget_lead") == "widget_lead"
    assert _surface_class("owner") == "owner"
    assert _surface_class("assistant") == "assistant"


# ── _get_or_create_lead: public leads omit api_key_id ─────────────────────────

def _mock_insert_sb(returned_row):
    sb = MagicMock()
    sb.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[returned_row])
    return sb


def test_get_or_create_lead_public_omits_api_key():
    sb = _mock_insert_sb({"id": "lead-pub", "offer_state": "not_yet_offered", "turn_count": 1})
    with patch("routers.widget.get_supabase_client", return_value=sb):
        from routers.widget import _get_or_create_lead
        row = _get_or_create_lead(
            twin_id="twin-1", key_id=None, conversation_id="conv-1",
            lead_id=None, visitor_id="vis-1", source_domain="example.com",
            utm_source=None, utm_medium=None, utm_campaign=None, utm_content=None,
        )
    inserted = sb.table.return_value.insert.call_args[0][0]
    assert "api_key_id" not in inserted  # public lead -> NULL api_key_id
    assert inserted["twin_id"] == "twin-1"
    assert row["id"] == "lead-pub"
    assert row["lead_capture_enabled"] is True


def test_get_or_create_lead_widget_keeps_api_key():
    sb = _mock_insert_sb({"id": "lead-w", "offer_state": "not_yet_offered", "turn_count": 1})
    with patch("routers.widget.get_supabase_client", return_value=sb):
        from routers.widget import _get_or_create_lead
        _get_or_create_lead(
            twin_id="twin-1", key_id="key-1", conversation_id="conv-1",
            lead_id=None, visitor_id="vis-1", source_domain="example.com",
            utm_source=None, utm_medium=None, utm_campaign=None, utm_content=None,
        )
    inserted = sb.table.return_value.insert.call_args[0][0]
    assert inserted["api_key_id"] == "key-1"  # widget lead -> api key set


def test_get_or_create_lead_increment_uses_atomic_rpc():
    """A returning lead (lead_id set) increments via the atomic RPC, not a
    SELECT-then-UPDATE, and never touches .insert()."""
    sb = MagicMock()
    sb.rpc.return_value.execute.return_value = MagicMock(
        data=[{"id": "lead-x", "offer_state": "already_offered", "turn_count": 5, "visitor_email": None}]
    )
    with patch("routers.widget.get_supabase_client", return_value=sb):
        from routers.widget import _get_or_create_lead
        row = _get_or_create_lead(
            twin_id="twin-1", key_id=None, conversation_id="conv-1",
            lead_id="lead-x", visitor_id="vis-1", source_domain="example.com",
            utm_source=None, utm_medium=None, utm_campaign=None, utm_content=None,
        )
    fn, params = sb.rpc.call_args[0]
    assert fn == "increment_widget_lead_turn"
    assert params == {"p_lead_id": "lead-x", "p_twin_id": "twin-1"}
    assert row["turn_count"] == 5  # DB already applied +1; 5 is the stored post-increment value
    assert row["visitor_email"] is None  # column is forwarded straight from the RPC row
    assert row["lead_capture_enabled"] is True
    sb.table.return_value.insert.assert_not_called()  # no insert on the return path


# ── _public_capture_enabled: fail-safe OFF ────────────────────────────────────

def _mock_settings_sb(settings_value):
    sb = MagicMock()
    (
        sb.table.return_value.select.return_value.eq.return_value
        .single.return_value.execute.return_value
    ) = MagicMock(data={"settings": settings_value})
    return sb


def test_public_capture_enabled_default_off():
    sb = _mock_settings_sb({})  # no flag present
    with patch("routers.chat.get_supabase_client", return_value=sb):
        from routers.chat import _public_capture_enabled
        assert _public_capture_enabled("twin-1") is False


def test_public_capture_enabled_true():
    sb = _mock_settings_sb({"lead_capture_enabled": True})
    with patch("routers.chat.get_supabase_client", return_value=sb):
        from routers.chat import _public_capture_enabled
        assert _public_capture_enabled("twin-1") is True


def test_public_capture_enabled_nonbool_off():
    sb = _mock_settings_sb({"lead_capture_enabled": "yes"})  # truthy but not True
    with patch("routers.chat.get_supabase_client", return_value=sb):
        from routers.chat import _public_capture_enabled
        assert _public_capture_enabled("twin-1") is False


def test_public_capture_enabled_failsafe_on_error():
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("db down")
    with patch("routers.chat.get_supabase_client", return_value=sb):
        from routers.chat import _public_capture_enabled
        assert _public_capture_enabled("twin-1") is False  # never raises -> OFF


# ── generate_system_prompt offer block for public_lead ────────────────────────

def test_generate_system_prompt_public_lead_fires_offer():
    from adk_core.services.prompts import generate_system_prompt
    profile = {"name": "Sainath", "bio": "founder"}
    lead_context = {
        "lead_capture_enabled": True, "offer_state": "not_yet_offered",
        "turn_count": 4, "persona_name": "Sainath",
    }
    prompt = generate_system_prompt(profile, surface_class="public_lead", lead_context=lead_context)
    assert "capture_lead_contact" in prompt
    assert "WHEN TO OFFER" in prompt


def test_generate_system_prompt_public_off_path_unchanged():
    """Capture OFF -> public maps to 'visitor' surface_class -> no capture wiring."""
    from adk_core.services.prompts import generate_system_prompt
    profile = {"name": "Sainath", "bio": "founder"}
    prompt = generate_system_prompt(profile, surface_class="visitor")
    assert "capture_lead_contact" not in prompt
