"""PR2 tests — public_lead intent-aware/framed offer block, value_frame resolution,
and inferred-intent persistence. Also guards that the widget_lead block is unchanged.
"""
import pytest
from unittest.mock import MagicMock, patch

PROFILE = {"name": "Sainath", "bio": "founder"}


def _ctx(**kw):
    base = {
        "lead_capture_enabled": True, "offer_state": "not_yet_offered",
        "turn_count": 1, "value_frame": "lead", "persona_name": "Sainath",
    }
    base.update(kw)
    return base


# ── public_lead offer block ───────────────────────────────────────────────────

def test_public_lead_offer_is_intent_gated_no_turn_floor():
    from adk_core.services.prompts import generate_system_prompt
    # turn 1 — below the widget turn-3 floor; public_lead still emits offer guidance.
    prompt = generate_system_prompt(PROFILE, surface_class="public_lead", lead_context=_ctx(turn_count=1))
    assert "capture_lead_contact" in prompt
    assert "WHEN TO OFFER" in prompt
    assert "NO turn-count gate" in prompt


def test_public_lead_anti_creepy_and_consent_present():
    from adk_core.services.prompts import generate_system_prompt
    prompt = generate_system_prompt(PROFILE, surface_class="public_lead", lead_context=_ctx())
    assert "FORBIDDEN" in prompt              # never state inference as fact (P1)
    assert "pass that to Sainath" in prompt   # consent disclosure (P3)
    assert "newsletter" in prompt             # explicit never-newsletter/marketing


def test_public_lead_value_frame_varies():
    from adk_core.services.prompts import generate_system_prompt
    opp = generate_system_prompt(PROFILE, surface_class="public_lead", lead_context=_ctx(value_frame="opportunity"))
    lead = generate_system_prompt(PROFILE, surface_class="public_lead", lead_context=_ctx(value_frame="lead"))
    assert "as an OPPORTUNITY" in opp
    assert "conversation about working together" in lead
    assert opp != lead


def test_public_lead_already_offered_no_repeat():
    from adk_core.services.prompts import generate_system_prompt
    prompt = generate_system_prompt(PROFILE, surface_class="public_lead", lead_context=_ctx(offer_state="already_offered"))
    assert "Do NOT offer again" in prompt


def test_public_lead_disabled_falls_back_to_visitor():
    from adk_core.services.prompts import generate_system_prompt
    prompt = generate_system_prompt(PROFILE, surface_class="public_lead", lead_context={"lead_capture_enabled": False})
    assert "capture_lead_contact" not in prompt


def test_widget_lead_block_unchanged():
    """The widget block must NOT pick up the public-only intent-gating text."""
    from adk_core.services.prompts import generate_system_prompt
    wctx = {"lead_capture_enabled": True, "offer_state": "not_yet_offered", "turn_count": 4, "persona_name": "Sainath"}
    prompt = generate_system_prompt(PROFILE, surface_class="widget_lead", lead_context=wctx)
    assert "WIDGET VISITOR" in prompt
    assert "NO turn-count gate" not in prompt  # widget keeps its turn-3 floor


# ── _infer_value_frame ────────────────────────────────────────────────────────

def test_infer_value_frame():
    from routers.chat import _infer_value_frame
    assert _infer_value_frame({"occupation": "MBA student"}) == "opportunity"
    assert _infer_value_frame({"occupation": "Founder & CEO"}) == "lead"
    assert _infer_value_frame({"role": "Realtor"}) == "inquiry"
    assert _infer_value_frame({"occupation": "Music creator"}) == "collaboration"
    assert _infer_value_frame({"occupation": "Chef"}) == "interest"


# ── _public_capture_config ────────────────────────────────────────────────────

def test_public_capture_config_returns_frame():
    sb = MagicMock()
    (
        sb.table.return_value.select.return_value.eq.return_value
        .single.return_value.execute.return_value
    ) = MagicMock(data={"settings": {"lead_capture_enabled": True, "value_frame": "opportunity"}})
    with patch("routers.chat.get_supabase_client", return_value=sb):
        from routers.chat import _public_capture_config
        cfg = _public_capture_config("twin-1")
    assert cfg["enabled"] is True
    assert cfg["value_frame"] == "opportunity"


def test_public_capture_config_failsafe():
    sb = MagicMock()
    sb.table.side_effect = RuntimeError("db down")
    with patch("routers.chat.get_supabase_client", return_value=sb):
        from routers.chat import _public_capture_config
        cfg = _public_capture_config("twin-1")
    assert cfg["enabled"] is False


# ── capture_lead_contact persists inferred fields ─────────────────────────────

@pytest.mark.asyncio
async def test_capture_lead_contact_persists_inferred_fields():
    mock_sb = MagicMock()
    mock_sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[{"id": "lead-1"}])
    with (
        patch("adk_core.tools.capture_tools.get_supabase_client", return_value=mock_sb),
        patch("services.lifecycle_email_service.enqueue_hot_lead_alert"),
    ):
        from adk_core.tools.capture_tools import _make_capture_lead_tool
        tool = _make_capture_lead_tool(twin_id="twin-1", lead_id="lead-1")
        result = await tool.func(
            email="jo@fund.vc", inferred_visitor_type="investor", inferred_intent="seed round",
        )
    assert result["status"] == "captured"
    payload = mock_sb.table.return_value.update.call_args[0][0]
    assert payload["inferred_visitor_type"] == "investor"
    assert payload["inferred_intent"] == "seed round"
