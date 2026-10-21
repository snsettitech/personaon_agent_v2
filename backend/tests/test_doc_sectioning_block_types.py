from modules.doc_sectioning import extract_section_blocks


def test_numbered_questionnaire_block_tagged_as_prompt_question():
    text = "\n".join(
        [
            "1) Who are you (short bio used in the twin)",
            "2) What are your core expertise areas?",
            "3) What outcomes should users expect?",
        ]
    )

    blocks = extract_section_blocks(text)

    assert blocks
    assert blocks[0].get("block_type") == "prompt_question"
    assert blocks[0].get("is_answer_text") is False


def test_numbered_non_question_heading_still_parses_as_section():
    text = "\n".join(
        [
            "1) Owner identity and credibility",
            "I am an operator focused on pragmatic founder support.",
            "I prioritize fast decisions over theory.",
        ]
    )

    blocks = extract_section_blocks(text)

    assert blocks
    assert blocks[0].get("section_title") == "1) Owner identity and credibility"
    assert blocks[0].get("block_type") in {"answer_text", "bullet_list"}
    assert blocks[0].get("is_answer_text") is True
