"""Unit tests for three-bucket system prompt generation."""


# Minimal profile for tests
_PROFILE = {"name": "Alice Test", "bio": "A test persona."}


def test_generate_system_prompt_contains_three_buckets():
    from adk_core.services.prompts import generate_system_prompt

    output = generate_system_prompt(_PROFILE, surface_class="visitor")
    assert "RESPONSE PROTOCOL" in output
    assert "BUCKET 1" in output
    assert "BUCKET 2" in output
    assert "BUCKET 3" in output


def test_generate_system_prompt_session_context_owner():
    from adk_core.services.prompts import generate_system_prompt

    output = generate_system_prompt(_PROFILE, surface_class="owner")
    assert "SESSION CONTEXT" in output
    assert "OWNER" in output
    assert "capture_knowledge" in output


def test_generate_system_prompt_session_context_visitor():
    from adk_core.services.prompts import generate_system_prompt

    output = generate_system_prompt(_PROFILE, surface_class="visitor")
    assert "SESSION CONTEXT" in output
    assert "VISITOR" in output
    assert "queue_question" in output


def test_generate_system_prompt_default_is_visitor():
    from adk_core.services.prompts import generate_system_prompt

    output = generate_system_prompt(_PROFILE)
    assert "VISITOR" in output


def test_generate_system_prompt_no_longer_includes_actions():
    # Actions / slash-command block removed 2026-06-26 — not rendered even when passed.
    from adk_core.services.prompts import generate_system_prompt

    actions = [
        {
            "label": "Coffee",
            "type": "booking_link",
            "trigger": "/coffee",
            "is_active": True,
        }
    ]
    output = generate_system_prompt(_PROFILE, actions=actions, surface_class="owner")
    assert "AVAILABLE ACTIONS" not in output


def test_generate_system_prompt_no_old_fallback():
    from adk_core.services.prompts import generate_system_prompt

    output = generate_system_prompt(_PROFILE, surface_class="visitor")
    assert "fall back to reasoning from the persona's background" not in output
