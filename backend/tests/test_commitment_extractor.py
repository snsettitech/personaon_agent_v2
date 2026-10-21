from services.commitment_extractor import structured_commitments_from_extras, content_hash


def test_simple_commitment_you_owe():
    extras = {
        "commitments": [
            {"text": "Send the deck to Maria by Friday", "assignee": "owner", "due_at": "2026-05-31"},
            {"text": "Maria will share the contract", "assignee": "Maria", "due_at": None},
        ]
    }
    out = structured_commitments_from_extras(extras, owner_name="Sainath")
    assert len(out) == 2
    assert out[0]["direction"] == "you_owe"
    assert out[0]["assignee_name"] is None
    assert out[0]["due_at"] == "2026-05-31"
    assert out[1]["direction"] == "they_owe"
    assert out[1]["assignee_name"] == "Maria"


def test_string_commitments_fallback_to_unknown():
    extras = {"commitments": ["Follow up next week"]}
    out = structured_commitments_from_extras(extras, owner_name="Sainath")
    assert len(out) == 1
    assert out[0]["direction"] == "unknown"
    assert out[0]["text"] == "Follow up next week"


def test_content_hash_is_stable():
    a = content_hash("Send deck", "Maria", "2026-05-31")
    b = content_hash("Send deck", "Maria", "2026-05-31")
    c = content_hash("Send deck", "Maria", "2026-06-01")
    assert a == b and a != c


def test_empty_extras():
    assert structured_commitments_from_extras({}, owner_name="x") == []
    assert structured_commitments_from_extras({"commitments": []}, owner_name="x") == []
