"""Shared fixtures for eval tests."""

import json
import os
import sys
from pathlib import Path

import pytest

# Ensure backend is in path
backend_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

EVAL_DIR = Path(backend_dir) / "eval"
DATASET_DIR = EVAL_DIR / "dataset"


@pytest.fixture
def personas_data():
    """Load personas dataset."""
    with open(DATASET_DIR / "personas.json") as f:
        return json.load(f)


@pytest.fixture
def chat_cases_data():
    """Load chat cases dataset."""
    with open(DATASET_DIR / "chat_cases.json") as f:
        return json.load(f)


@pytest.fixture
def sample_artifact():
    """A minimal ResearchArtifact dict for unit testing."""
    return {
        "subject_identity": {"canonical_name": "Naval Ravikant"},
        "source_registry": [
            {"source_id": f"s{i}", "url": f"https://example.com/{i}", "title": f"Source {i}"}
            for i in range(6)
        ],
        "extracted_claims": [
            {"claim_id": "c1", "text": "co-founded AngelList", "claim_type": "career", "confidence": 0.9, "source_ids": ["s1"]},
            {"claim_id": "c2", "text": "invested in Twitter as an early angel investor", "claim_type": "career", "confidence": 0.9, "source_ids": ["s2"]},
            {"claim_id": "c3", "text": "angel investor and entrepreneur", "claim_type": "role", "confidence": 0.9, "source_ids": ["s3"]},
        ],
        "timeline": [],
        "verified_quote_candidates": [],
        "synthesis_summary": "Naval Ravikant is an entrepreneur and investor.",
        "compile_metadata": {},
    }


@pytest.fixture
def retrieval_cases_data():
    """Load retrieval cases dataset."""
    with open(DATASET_DIR / "retrieval_cases.json") as f:
        return json.load(f)


@pytest.fixture
def sample_retrieved_chunks():
    """5 mock chunk dicts for naval_wealth case.

    Chunks 0, 1, 3 contain relevant keywords; chunks 2, 4 do not.
    This gives precision@5 = 3/5 = 0.6, MRR = 1.0 (chunk 0 relevant).
    """
    return [
        {"text": "Naval Ravikant talks about specific knowledge as the key to wealth creation.", "score": 0.92},
        {"text": "Wealth creation requires permissionless leverage through media and code.", "score": 0.88},
        {"text": "This chunk discusses general business concepts without specifics.", "score": 0.70},
        {"text": "Building accountability and equity ownership is central to Naval's wealth philosophy.", "score": 0.65},
        {"text": "An unrelated passage about investment strategies with no keyword match.", "score": 0.55},
    ]


@pytest.fixture
def sample_persona_expected():
    """Expected values for Naval Ravikant from personas.json."""
    return {
        "persona_id": "naval_ravikant",
        "subject_name": "Naval Ravikant",
        "hints": {"company": "AngelList"},
        "expected_claims": [
            {"text": "co-founded AngelList", "claim_type": "career"},
            {"text": "invested in Twitter", "claim_type": "career"},
            {"text": "angel investor and entrepreneur", "claim_type": "role"},
        ],
        "expected_topics": ["angel investing", "startups"],
    }


@pytest.fixture
def sample_source_text():
    """2000+ char source text containing Naval Ravikant keywords for chunk validator tests.

    Contains 'specific knowledge', 'leverage', 'co-founded AngelList', 'platform',
    and 'angel investor' phrases in natural paragraph context so keyword matching works.
    """
    return (
        "Naval Ravikant is an entrepreneur and philosopher best known for his ideas on wealth creation. "
        "He believes that specific knowledge — knowledge that cannot be trained for — is the foundation "
        "of building real wealth. This specific knowledge is often technical, creative, or involves "
        "deep domain expertise that took years to develop. Naval argues that permissionless leverage "
        "through code and media allows individuals to build scalable wealth without asking for "
        "anyone's permission. His philosophy emphasizes long-term game theory, accountability, "
        "and equity ownership as the path to financial freedom.\n\n"
        "Naval co-founded AngelList, a platform connecting startups with investors and job seekers. "
        "The angel investing platform democratized access to startup funding, enabling smaller "
        "angel investors to participate in early stage funding rounds that were previously reserved "
        "for institutional investors. As an AngelList founder, Naval changed how startup investing "
        "works globally. The platform has facilitated billions in startup capital.\n\n"
        "As an angel investor, Naval has invested in over 200 companies including Twitter, Uber, "
        "and many other successful startups. He is a prominent figure in Silicon Valley, known "
        "for his wisdom on entrepreneurship, happiness, and wealth. Naval's podcast appearances "
        "and Twitter threads have made his philosophy accessible to millions worldwide. "
        "His approach combines Eastern philosophy with Western capitalism, creating a unique "
        "framework for thinking about success, fulfillment, and building a meaningful life "
        "through deliberate choices and leveraging unique strengths.\n\n"
        "Naval emphasizes that the most important thing for an aspiring entrepreneur is to find "
        "their specific knowledge — the skills and knowledge at the intersection of what they "
        "love, what they are good at, and what the world needs. Building leverage through "
        "permissionless means such as software, media, or capital amplifies this specific knowledge "
        "into disproportionate returns. This is the core of his wealth creation framework.\n\n"
        "The concept of wealth creation in Naval's philosophy is distinct from making money. "
        "Wealth is defined as assets that earn while you sleep. Leverage building allows individuals "
        "to decouple time from income. Startup advice from Naval consistently points to finding "
        "product market fit as early as possible, then scaling through leverage rather than labor."
    )
