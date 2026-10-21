"""PR5 tests — public_lead offer_state advancement (mark already_offered once the
persona has actually made the offer, detected from its own output)."""
from unittest.mock import MagicMock, patch


def test_looks_like_offer():
    from routers.chat import _looks_like_offer
    assert _looks_like_offer("Happy to help — what's the best email to reach you?") is True
    assert _looks_like_offer("Drop your email and I'll follow up directly.") is True
    assert _looks_like_offer("I've worked on backend systems for years.") is False
    assert _looks_like_offer("") is False


def test_advance_marks_already_offered_on_offer():
    sb = MagicMock()
    with patch("routers.chat.get_supabase_client", return_value=sb):
        from routers.chat import _advance_offer_state_if_offered
        _advance_offer_state_if_offered(
            chat_surface="public_lead", lead_id="lead-1", twin_id="t1",
            lead_context={"offer_state": "not_yet_offered"},
            assistant_response="Glad that helps — what's the best email to reach you?",
        )
    payload = sb.table.return_value.update.call_args[0][0]
    assert payload["offer_state"] == "already_offered"
    # tenant-scoped update (twin_id on the .eq chain)
    sb.table.return_value.update.return_value.eq.return_value.eq.assert_called()


def test_advance_noop_when_already_offered():
    sb = MagicMock()
    with patch("routers.chat.get_supabase_client", return_value=sb):
        from routers.chat import _advance_offer_state_if_offered
        _advance_offer_state_if_offered(
            chat_surface="public_lead", lead_id="lead-1", twin_id="t1",
            lead_context={"offer_state": "already_offered"},
            assistant_response="share your email",
        )
    sb.table.assert_not_called()


def test_advance_noop_when_no_offer_text():
    sb = MagicMock()
    with patch("routers.chat.get_supabase_client", return_value=sb):
        from routers.chat import _advance_offer_state_if_offered
        _advance_offer_state_if_offered(
            chat_surface="public_lead", lead_id="lead-1", twin_id="t1",
            lead_context={"offer_state": "not_yet_offered"},
            assistant_response="Here's a rundown of my background in backend systems.",
        )
    sb.table.assert_not_called()


def test_advance_noop_for_non_public_lead_surface():
    sb = MagicMock()
    with patch("routers.chat.get_supabase_client", return_value=sb):
        from routers.chat import _advance_offer_state_if_offered
        _advance_offer_state_if_offered(
            chat_surface="public", lead_id="lead-1", twin_id="t1",
            lead_context={"offer_state": "not_yet_offered"},
            assistant_response="what's the best email",
        )
    sb.table.assert_not_called()


def test_advance_noop_without_lead_id():
    sb = MagicMock()
    with patch("routers.chat.get_supabase_client", return_value=sb):
        from routers.chat import _advance_offer_state_if_offered
        _advance_offer_state_if_offered(
            chat_surface="public_lead", lead_id=None, twin_id="t1",
            lead_context={"offer_state": "not_yet_offered"},
            assistant_response="what's the best email",
        )
    sb.table.assert_not_called()
