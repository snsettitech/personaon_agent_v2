"""Tests for services.recap_sanitizer — RED first, then GREEN after implementation."""


def test_pick_returns_only_whitelisted_keys():
    from services.recap_sanitizer import pick, PUBLIC_EXTRAS_KEYS
    out = pick({"intent": "x", "secret": "y", "what_happened": "z"}, PUBLIC_EXTRAS_KEYS)
    assert "intent" in out
    assert "what_happened" in out
    assert "secret" not in out


def test_sanitize_action_items_excludes_assignee_email():
    from services.recap_sanitizer import sanitize_action_items
    out = sanitize_action_items([{
        "text": "send invoice",
        "assignee": "Maria",
        "assignee_email": "maria@example.com",
        "context": "from meeting",
        "due_at": "2026-06-01",
        "completed": False,
    }])
    assert len(out) == 1
    assert "assignee_email" not in out[0]
    assert out[0]["text"] == "send invoice"
    assert out[0]["assignee"] == "Maria"


def test_sanitize_meeting_shape():
    from services.recap_sanitizer import sanitize_meeting
    meeting = {
        "title": "Product sync",
        "summary_json": {"tldr": "discussed roadmap", "topics": ["auth"], "key_questions": ["when?"], "action_items": []},
        "recap_extras_json": {"intent": "align on Q3", "what_happened": "agreed on scope", "commitments": []},
    }
    out = sanitize_meeting(meeting)
    assert out["title"] == "Product sync"
    assert out["summary"]["tldr"] == "discussed roadmap"
    assert out["extras"]["intent"] == "align on Q3"
    assert "action_items" in out
