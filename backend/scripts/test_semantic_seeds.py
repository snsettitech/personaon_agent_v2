"""
Test semantic seed selection with real data.

This script demonstrates the enhanced GraphRAG capabilities:
1. Fetches an existing twin
2. Shows its graph nodes
3. Tests keyword vs semantic seed selection
4. Compares results
"""
__test__ = False

import asyncio
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from modules.observability import supabase
from modules.graph_context import (
    get_graph_snapshot,
    _select_seeds,
    _select_seeds_semantic,
    get_graph_stats
)


async def get_first_twin_with_graph():
    """Find a twin that has graph nodes."""
    # Get all twins
    twins_res = supabase.table("twins").select("id, name").limit(10).execute()
    twins = twins_res.data or []

    for twin in twins:
        stats = get_graph_stats(twin["id"])
        if stats["node_count"] > 0:
            return twin["id"], twin["name"], stats

    return None, None, None


async def test_seed_selection(twin_id: str, query: str):
    """Compare keyword vs semantic seed selection."""
    print(f"\n{'='*60}")
    print(f"Query: \"{query}\"")
    print(f"{'='*60}")

    # Get all nodes first for comparison
    nodes_res = supabase.rpc("get_nodes_system", {
        "t_id": twin_id,
        "limit_val": 50
    }).execute()
    all_nodes = nodes_res.data or []

    # Test keyword selection
    keyword_seeds = await _select_seeds(twin_id, query)
    print(f"\n[KEYWORD] Seeds ({len(keyword_seeds)}):")
    for node in keyword_seeds[:5]:
        print(f"   - {node.get('name')} ({node.get('type')})")

    # Test semantic selection
    semantic_seeds = await _select_seeds_semantic(twin_id, query, all_nodes)
    print(f"\n[SEMANTIC] Seeds ({len(semantic_seeds)}):")
    for node in semantic_seeds[:5]:
        print(f"   - {node.get('name')} ({node.get('type')})")

    # Get full snapshot with combined approach
    snapshot = await get_graph_snapshot(twin_id, query, max_hops=2)
    print("\n[SNAPSHOT] Full result (combined):")
    print(f"   - Nodes: {snapshot.get('node_count', 0)}")
    print(f"   - Edges: {snapshot.get('edge_count', 0)}")

    if snapshot.get("context_text"):
        preview = snapshot["context_text"][:500]
        print(f"\n[CONTEXT] Preview:\n{preview}...")


async def main():
    print("[TEST] Testing Semantic Seed Selection with Real Data\n")

    # Find a twin with graph data
    twin_id, twin_name, stats = await get_first_twin_with_graph()

    if not twin_id:
        print("[ERROR] No twins with graph data found. Please ingest some documents first.")
        return

    print(f"[OK] Using Twin: {twin_name}")
    print(f"   - Node count: {stats['node_count']}")
    print(f"   - Top nodes: {[n['name'] for n in stats['top_nodes'][:3]]}")

    # Test with various queries
    test_queries = [
        "investment philosophy",  # Semantic - should find related concepts
        "market strategy",        # Semantic - broader match
        stats['top_nodes'][0]['name'] if stats['top_nodes'] else "test"  # Exact keyword match
    ]

    for query in test_queries:
        await test_seed_selection(twin_id, query)

    print("\n" + "="*60)
    print("[DONE] Test complete!")


if __name__ == "__main__":
    asyncio.run(main())
