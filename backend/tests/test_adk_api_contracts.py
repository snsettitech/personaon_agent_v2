import pytest
from pydantic import ValidationError

from adk_core.schemas.api import ChatTurnRequest, ResearchRunCreateRequest


def test_chat_turn_request_normalizes_whitespace():
    request = ChatTurnRequest(
        conversation_id="conv-1",
        message="   Tell   me   about   your work   ",
        client_context={"surface": "owner"},
    )

    assert request.message == "Tell me about your work"


def test_chat_turn_request_rejects_blank_message():
    with pytest.raises(ValidationError):
        ChatTurnRequest(message="   ")


def test_research_run_create_request_normalizes_subject_name():
    request = ResearchRunCreateRequest(
        subject_name="  Ada   Lovelace  ",
        hints={"company": "Analytical Engine"},
    )

    assert request.subject_name == "Ada Lovelace"
    assert request.hints["company"] == "Analytical Engine"


def test_research_run_create_request_normalizes_and_dedupes_seed_urls():
    request = ResearchRunCreateRequest(
        subject_name="Ada Lovelace",
        seed_urls=[
            "linkedin.com/in/ada-lovelace",
            "https://www.linkedin.com/in/ada-lovelace/",
            "not-a-url",
            "https://example.com/profile",
        ],
    )

    assert request.seed_urls == [
        "https://www.linkedin.com/in/ada-lovelace",
        "https://example.com/profile",
    ]
