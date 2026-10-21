from modules.ingestion import _build_embedding_text


def test_prompt_question_embedding_uses_section_descriptor():
    # BUG #22 FIX: prompt_question embedding now returns "{descriptor}: {chunk}"
    # so the full Q&A text is semantically searchable (not just the section title).
    entry = {
        "block_type": "prompt_question",
        "section_title": "Owner identity and credibility",
        "section_path": "Sai_twin.docx/Owner identity and credibility",
    }
    chunk = "1) Who are you (short bio used in the twin)"

    embedding_text = _build_embedding_text(entry, chunk)

    assert embedding_text == "Owner identity and credibility: 1) Who are you (short bio used in the twin)"
    assert "Owner identity and credibility" in embedding_text
    assert "Who are you" in embedding_text


def test_answer_text_embedding_keeps_chunk_content():
    entry = {"block_type": "answer_text", "section_title": "Owner identity and credibility"}
    chunk = "I am a pragmatic operator focused on founder outcomes."

    embedding_text = _build_embedding_text(entry, chunk)

    assert embedding_text == chunk
