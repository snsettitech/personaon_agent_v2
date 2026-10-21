import pytest

from modules import verified_qna


def _mock_qna_entry(qna_id: str, question: str, answer: str = "answer"):
    return {
        "id": qna_id,
        "question": question,
        "answer": answer,
        "question_embedding": "[0.1, 0.2, 0.3]",
        "is_active": True,
    }


@pytest.mark.asyncio
async def test_semantic_match_requires_lexical_grounding(monkeypatch):
    entries = [_mock_qna_entry("q1", "How's your day going so far?", "I'm good.")]

    monkeypatch.setattr(verified_qna, "_fetch_verified_qna_entries", lambda twin_id, group_id=None: entries)
    monkeypatch.setattr(verified_qna, "get_embedding", lambda _text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(verified_qna, "cosine_similarity", lambda _a, _b: 0.89)
    monkeypatch.setattr(
        verified_qna,
        "_format_match_result",
        lambda best_match, best_score: {"id": best_match["id"], "similarity_score": best_score},
    )

    result = await verified_qna.match_verified_qna(
        query="who are you?",
        twin_id="twin-1",
        use_exact=False,
        use_semantic=True,
        semantic_threshold=0.75,
    )

    assert result is None


@pytest.mark.asyncio
async def test_semantic_match_rejects_high_similarity_without_overlap(monkeypatch):
    entries = [_mock_qna_entry("q1", "How's your day going so far?", "I'm good.")]

    monkeypatch.setattr(verified_qna, "_fetch_verified_qna_entries", lambda twin_id, group_id=None: entries)
    monkeypatch.setattr(verified_qna, "get_embedding", lambda _text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(verified_qna, "cosine_similarity", lambda _a, _b: 0.99)
    monkeypatch.setattr(
        verified_qna,
        "_format_match_result",
        lambda best_match, best_score: {"id": best_match["id"], "similarity_score": best_score},
    )

    result = await verified_qna.match_verified_qna(
        query="who are you?",
        twin_id="twin-1",
        use_exact=False,
        use_semantic=True,
        semantic_threshold=0.75,
    )

    assert result is None


@pytest.mark.asyncio
async def test_semantic_match_with_overlap_is_allowed(monkeypatch):
    entries = [_mock_qna_entry("q2", "Do you know antler?", "Yes, I know Antler.")]

    monkeypatch.setattr(verified_qna, "_fetch_verified_qna_entries", lambda twin_id, group_id=None: entries)
    monkeypatch.setattr(verified_qna, "get_embedding", lambda _text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(verified_qna, "cosine_similarity", lambda _a, _b: 0.86)
    monkeypatch.setattr(
        verified_qna,
        "_format_match_result",
        lambda best_match, best_score: {"id": best_match["id"], "similarity_score": best_score},
    )

    result = await verified_qna.match_verified_qna(
        query="do you know antler",
        twin_id="twin-1",
        use_exact=False,
        use_semantic=True,
        semantic_threshold=0.75,
    )

    assert result is not None
    assert result["id"] == "q2"
    assert result["match_type"] == "semantic"


@pytest.mark.asyncio
async def test_exact_and_semantic_thresholds_are_enforced_independently(monkeypatch):
    entries = [_mock_qna_entry("q3", "what is antler", "Antler is a VC firm.")]

    monkeypatch.setattr(verified_qna, "_fetch_verified_qna_entries", lambda twin_id, group_id=None: entries)
    monkeypatch.setattr(verified_qna, "get_embedding", lambda _text: [0.1, 0.2, 0.3])
    monkeypatch.setattr(verified_qna, "cosine_similarity", lambda _a, _b: 0.83)
    monkeypatch.setattr(
        verified_qna,
        "_format_match_result",
        lambda best_match, best_score: {"id": best_match["id"], "similarity_score": best_score},
    )

    # Semantic score passes 0.80 but should fail when semantic_threshold=0.90.
    result = await verified_qna.match_verified_qna(
        query="what is antler",
        twin_id="twin-1",
        use_exact=False,
        use_semantic=True,
        semantic_threshold=0.90,
    )
    assert result is None

    # Exact should still pass independently with a lower exact threshold.
    exact_result = await verified_qna.match_verified_qna(
        query="what is antler",
        twin_id="twin-1",
        use_exact=True,
        use_semantic=False,
        exact_threshold=0.80,
    )
    assert exact_result is not None
    assert exact_result["match_type"] == "exact"
