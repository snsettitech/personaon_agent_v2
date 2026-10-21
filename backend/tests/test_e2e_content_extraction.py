# tests/test_e2e_content_extraction.py
"""
End-to-end test for content extraction using real Supabase connection.
This test uses the actual Scribe Engine to extract nodes from existing content.

Run with: python -m pytest tests/test_e2e_content_extraction.py -v -s
"""

import asyncio
import os
import sys
import pytest

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.mark.network
@pytest.mark.asyncio
async def test_e2e_extraction():
    """
    Real E2E test: Extract nodes from sample content text.
    Uses actual OpenAI API and Supabase connection.
    """
    required_vars = ["OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        pytest.skip(f"Missing env vars for E2E extraction: {missing}")

    from modules._core.scribe_engine import extract_from_content
    from modules.observability import supabase

    # Use an existing twin
    try:
        twins_result = supabase.table("twins").select("id").limit(1).execute()
    except Exception as exc:
        pytest.skip(f"Supabase not reachable for E2E extraction: {exc}")

    if not twins_result.data:
        pytest.skip("No twins found - skipping E2E extraction")

    twin_id = twins_result.data[0]["id"]

    # Sample content to extract from
    sample_content = """
    Sajna Setti is the founder of PersonaOn, a platform that creates
    AI-powered personas for venture capitalists and executives. The company is based
    in the United States and focuses on enterprise AI solutions.

    The platform uses advanced natural language processing to capture decision-making patterns,
    investment criteria, and communication styles. Key features include Graph Memory,
    Interview Mode, and multi-tenant architecture with RLS security.

    The technology stack includes Python FastAPI backend, Next.js frontend, Supabase for
    database, and OpenAI for LLM processing. The company targets the $50B+ AI market.
    """

    print(f"\n[E2E Test] Extracting from {len(sample_content)} chars for twin {twin_id}...")

    # Run extraction
    result = await extract_from_content(
        twin_id=twin_id,
        content_text=sample_content,
        source_id="e2e-test-source",
        source_type="e2e_test",
        max_chunks=1,
        tenant_id=None  # Skip memory event for test
    )

    print("\n[E2E Test Results]")
    print(f"  Chunks processed: {result.get('chunks_processed', 0)}")
    print(f"  Nodes created: {len(result.get('all_nodes', []))}")
    print(f"  Edges created: {len(result.get('all_edges', []))}")
    print(f"  Confidence: {result.get('total_confidence', 0):.2f}")

    if result.get('all_nodes'):
        print("\n  Sample nodes:")
        for node in result['all_nodes'][:5]:
            print(f"    - {node.get('name')} ({node.get('type')})")

    if result.get('error'):
        pytest.fail(f"E2E extraction returned error: {result['error']}")

    # Verify nodes were created in DB
    nodes_check = supabase.table("nodes").select("id, name, type").eq("twin_id", twin_id).order("created_at", desc=True).limit(10).execute()
    print(f"\n  Latest nodes in DB: {len(nodes_check.data)}")

    assert len(result.get('all_nodes', [])) > 0


if __name__ == "__main__":
    print("\n" + "="*60)
    print("E2E Content Extraction Test")
    print("="*60)

    # Check for required env vars
    required_vars = ["OPENAI_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_KEY"]
    missing = [v for v in required_vars if not os.getenv(v)]
    if missing:
        print(f"Missing environment variables: {missing}")
        print("Set these in .env file or environment")
        sys.exit(1)

    # Run test
    success = asyncio.run(test_e2e_extraction())

    print("\n" + "="*60)
    if success:
        print("✅ E2E TEST PASSED - Nodes extracted and saved to database")
    else:
        print("❌ E2E TEST FAILED - No nodes extracted")
    print("="*60 + "\n")
