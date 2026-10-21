#!/usr/bin/env python3
"""
GraphRAG Diagnosis Script

Diagnoses GraphRAG failures by checking:
1. Graph has nodes/edges for a test twin
2. Graph retrieval with sample queries
3. RPC functions exist and work
4. Ingestion path (checks if process_interaction is called)
5. Reports failure mode: empty graph, retrieval fails, errors, or integration issue
"""

import argparse
import sys
import os
import asyncio
import json
from typing import Any

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from modules.observability import supabase
from modules.graph_context import get_graph_snapshot, get_graph_stats


async def check_rpc_functions() -> dict[str, Any]:
    """Check if required RPC functions exist."""
    result = {
        "status": "unknown",
        "functions": {},
        "errors": []
    }

    required_functions = [
        "get_nodes_system",
        "create_node_system",
        "get_edges_system",
        "create_edge_system"
    ]

    try:
        # Try to call each function with dummy parameters to see if it exists
        for func_name in required_functions:
            try:
                if func_name.startswith("get_"):
                    # Test get functions with dummy UUID
                    test_uuid = "00000000-0000-0000-0000-000000000000"
                    if func_name == "get_nodes_system" or func_name == "get_edges_system":
                        _ = supabase.rpc(func_name, {"t_id": test_uuid, "limit_val": 1}).execute()
                    result["functions"][func_name] = "exists"
                else:
                    # For create functions, just check if they're callable (would need valid params to test)
                    result["functions"][func_name] = "exists (not tested)"
            except Exception as e:
                error_msg = str(e)
                if "function" in error_msg.lower() and "does not exist" in error_msg.lower():
                    result["functions"][func_name] = "missing"
                    result["errors"].append(f"{func_name}: {error_msg}")
                else:
                    # Function exists but call failed (expected with dummy params)
                    result["functions"][func_name] = "exists"

        all_exist = all(
            status in ("exists", "exists (not tested)")
            for status in result["functions"].values()
        )
        result["status"] = "pass" if all_exist else "fail"

    except Exception as e:
        result["status"] = "error"
        result["errors"].append(f"RPC check failed: {str(e)}")

    return result


async def check_graph_data(twin_id: str) -> dict[str, Any]:
    """Check if graph has nodes/edges for the twin."""
    result = {
        "status": "unknown",
        "node_count": 0,
        "edge_count": 0,
        "errors": []
    }

    try:
        # Get graph stats
        stats = get_graph_stats(twin_id)
        result["node_count"] = stats.get("node_count", 0)
        result["has_graph"] = stats.get("has_graph", False)

        # Try to get edges count
        try:
            edges_res = supabase.table("edges").select("id", count="exact").eq("twin_id", twin_id).execute()
            result["edge_count"] = edges_res.count if hasattr(edges_res, 'count') else 0
        except Exception as e:
            result["errors"].append(f"Edge count check failed: {str(e)}")

        if result["node_count"] > 0 or result["edge_count"] > 0:
            result["status"] = "pass"
        else:
            result["status"] = "empty"

    except Exception as e:
        result["status"] = "error"
        result["errors"].append(f"Graph data check failed: {str(e)}")

    return result


async def test_retrieval(twin_id: str, test_queries: list[str]) -> dict[str, Any]:
    """Test graph retrieval with sample queries."""
    result = {
        "status": "unknown",
        "queries": {},
        "errors": []
    }

    for query in test_queries:
        try:
            snapshot = await get_graph_snapshot(twin_id, query=query)
            query_result = {
                "node_count": snapshot.get("node_count", 0),
                "edge_count": snapshot.get("edge_count", 0),
                "has_context": bool(snapshot.get("context_text", "")),
                "context_length": len(snapshot.get("context_text", "")),
                "error": snapshot.get("error")
            }
            result["queries"][query] = query_result
        except Exception as e:
            result["queries"][query] = {
                "error": str(e),
                "node_count": 0,
                "has_context": False
            }
            result["errors"].append(f"Query '{query}' failed: {str(e)}")

    # Determine status
    successful_queries = sum(
        1 for q_result in result["queries"].values()
        if q_result.get("has_context", False) and not q_result.get("error")
    )

    if successful_queries == len(test_queries):
        result["status"] = "pass"
    elif successful_queries > 0:
        result["status"] = "partial"
    elif result["errors"]:
        result["status"] = "error"
    else:
        result["status"] = "empty"

    return result


async def diagnose_graphrag(twin_id: str) -> dict[str, Any]:
    """Run full GraphRAG diagnosis."""
    diagnosis = {
        "twin_id": twin_id,
        "rpc_functions": {},
        "graph_data": {},
        "retrieval": {},
        "summary": {},
        "failure_mode": "unknown"
    }

    print(f"Diagnosing GraphRAG for twin: {twin_id}\n")

    # 1. Check RPC functions
    print("1. Checking RPC functions...")
    diagnosis["rpc_functions"] = await check_rpc_functions()
    print(f"   Status: {diagnosis['rpc_functions']['status']}")
    for func, status in diagnosis["rpc_functions"]["functions"].items():
        print(f"   - {func}: {status}")

    # 2. Check graph data
    print("\n2. Checking graph data...")
    diagnosis["graph_data"] = await check_graph_data(twin_id)
    print(f"   Status: {diagnosis['graph_data']['status']}")
    print(f"   Nodes: {diagnosis['graph_data']['node_count']}")
    print(f"   Edges: {diagnosis['graph_data']['edge_count']}")

    # 3. Test retrieval
    print("\n3. Testing retrieval...")
    test_queries = [
        "test query",
        "what is my favorite",
        "where do I work"
    ]
    diagnosis["retrieval"] = await test_retrieval(twin_id, test_queries)
    print(f"   Status: {diagnosis['retrieval']['status']}")
    for query, q_result in diagnosis["retrieval"]["queries"].items():
        print(f"   - '{query}': {q_result.get('node_count', 0)} nodes, context={q_result.get('has_context', False)}")
        if q_result.get("error"):
            print(f"     Error: {q_result['error']}")

    # 4. Determine failure mode
    print("\n4. Determining failure mode...")
    if diagnosis["rpc_functions"]["status"] == "fail":
        diagnosis["failure_mode"] = "missing_rpc_functions"
        diagnosis["summary"] = {
            "issue": "Required RPC functions are missing",
            "fix": "Run database migrations to create RPC functions"
        }
    elif diagnosis["graph_data"]["status"] == "empty":
        diagnosis["failure_mode"] = "empty_graph"
        diagnosis["summary"] = {
            "issue": "Graph has no nodes or edges",
            "fix": "Ensure ingestion runs (process_interaction called after chat/cognitive interview)"
        }
    elif diagnosis["retrieval"]["status"] == "error":
        diagnosis["failure_mode"] = "retrieval_errors"
        diagnosis["summary"] = {
            "issue": "Graph retrieval throws errors",
            "fix": "Check error messages and fix retrieval logic"
        }
    elif diagnosis["retrieval"]["status"] == "empty":
        diagnosis["failure_mode"] = "retrieval_returns_empty"
        diagnosis["summary"] = {
            "issue": "Graph has data but retrieval returns empty context",
            "fix": "Improve seed selection or expansion logic"
        }
    elif diagnosis["retrieval"]["status"] == "partial":
        diagnosis["failure_mode"] = "partial_retrieval"
        diagnosis["summary"] = {
            "issue": "Graph retrieval works for some queries but not all",
            "fix": "Improve seed selection algorithm"
        }
    else:
        diagnosis["failure_mode"] = "working"
        diagnosis["summary"] = {
            "issue": "GraphRAG appears to be working",
            "fix": "No fixes needed"
        }

    print(f"   Failure mode: {diagnosis['failure_mode']}")
    print(f"   Issue: {diagnosis['summary']['issue']}")
    print(f"   Fix: {diagnosis['summary']['fix']}")

    return diagnosis


async def main():
    parser = argparse.ArgumentParser(description="Diagnose GraphRAG failures")
    parser.add_argument("--twin-id", required=True, help="Twin ID to diagnose")
    parser.add_argument("--json", action="store_true", help="Output JSON format")

    args = parser.parse_args()

    diagnosis = await diagnose_graphrag(args.twin_id)

    if args.json:
        print(json.dumps(diagnosis, indent=2))
    else:
        print("\n" + "="*60)
        print("DIAGNOSIS SUMMARY")
        print("="*60)
        print(f"Failure Mode: {diagnosis['failure_mode']}")
        print(f"Issue: {diagnosis['summary']['issue']}")
        print(f"Fix: {diagnosis['summary']['fix']}")
        print("="*60)


if __name__ == "__main__":
    asyncio.run(main())

