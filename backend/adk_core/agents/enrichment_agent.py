"""Single-agent web enrichment — searches and scrapes for NEW persona knowledge."""

from __future__ import annotations

from typing import Any

from google.adk.agents import LlmAgent

from adk_core.tools.search_tools import news_search, scrape_page, web_search


def build_enrichment_agent(
    *,
    model: Any,
    subject_name: str,
    organization: str = "",
    headline: str = "",
    bio_summary: str = "",
) -> LlmAgent:
    """Single agent that searches the web, scrapes pages, and summarizes new findings."""
    return LlmAgent(
        name="web_enrichment",
        model=model,
        instruction=f"""You are enriching an existing AI persona with web research.

Person: {subject_name}
Organization: {organization}
Headline: {headline}
Known bio: {bio_summary}

Your job: find NEW information about this person that is NOT already in their profile.

STRATEGY:
1. Search for "{subject_name}" + their organization/role (2-3 searches)
2. Search for interviews, podcasts, talks, or articles featuring them
3. Scrape the 3-5 most promising results
4. Focus on: direct quotes, opinions, stories, career milestones, public statements

RULES:
- Only search and scrape for THIS person (verify org/role matches)
- Skip pages about different people with the same name
- Stop after 5 successful scrapes — don't over-search
- If you find very little, that's OK — say so honestly

When done, summarize what NEW information you found that wasn't in the known bio.
""".strip(),
        tools=[web_search, news_search, scrape_page],
        output_key="enrichment_summary",
    )
