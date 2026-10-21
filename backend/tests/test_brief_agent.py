"""Unit tests for brief_agent — verifies structure without calling LLM or real tools."""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

# LlmAgent.model requires a string or BaseLlm instance — use a real model name string.
_MODEL = "gemini-2.5-flash"


def test_build_brief_agent_returns_llm_agent():
    from adk_core.agents.brief_agent import build_brief_agent

    agent = build_brief_agent(
        model=_MODEL,
        twin_id="twin-123",
        tenant_id="tenant-456",
        title="Intro call with Alex",
        participants=["Alex Chen", "Jamie Liu"],
        goal="Explore co-founder fit",
    )

    from google.adk.agents import LlmAgent
    assert isinstance(agent, LlmAgent)
    assert agent.name == "pre_meeting_brief"
    assert agent.output_key == "brief_result"


def test_build_brief_agent_has_five_tools():
    from adk_core.agents.brief_agent import build_brief_agent

    agent = build_brief_agent(
        model=_MODEL,
        twin_id="twin-123",
        tenant_id="tenant-456",
        title="Q2 planning",
        participants=["Sam"],
        goal="Set OKRs",
        notes="Board presentation follows",
    )

    # 5 tools: search_knowledge_base, search_past_meetings, web_search, news_search, scrape_page
    assert len(agent.tools) == 5


def test_build_brief_agent_instruction_includes_meeting_info():
    from adk_core.agents.brief_agent import build_brief_agent

    agent = build_brief_agent(
        model=_MODEL,
        twin_id="twin-123",
        tenant_id="tenant-456",
        title="Budget review",
        participants=["Morgan Lee"],
        goal="Align on Q3 spend",
        notes="Sensitive — internal only",
    )

    instr = agent.instruction
    assert "Budget review" in instr
    assert "Morgan Lee" in instr
    assert "Align on Q3 spend" in instr
    assert "Sensitive — internal only" in instr


@pytest.mark.asyncio
async def test_search_kb_tool_handles_empty_results():
    """KB tool returns a helpful string when no chunks are found."""
    from adk_core.agents.brief_agent import _build_search_kb_tool

    with patch("adk_core.services.vector_store.search", new=AsyncMock(return_value=[])):
        tool = _build_search_kb_tool("twin-abc")
        fn = tool.func
        result = await fn(query="unknown topic")
        assert "No relevant" in result


@pytest.mark.asyncio
async def test_past_meetings_tool_returns_no_matches():
    """Past meetings tool returns a helpful string when no matching meetings exist."""
    from adk_core.agents.brief_agent import _build_past_meetings_tool

    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value \
        .eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []

    with patch("modules.observability.get_supabase_client", return_value=mock_sb):
        tool = _build_past_meetings_tool("twin-abc", "tenant-123")
        fn = tool.func
        result = await fn(participant_name="Unknown Person")
        assert "No past meetings" in result
