# backend/modules/graph_context.py
"""
Graph Context Module

Provides bounded, query-relevant graph snapshot retrieval for chat context.
Uses Supabase for storage with 1-hop and optional 2-hop expansion.
"""

from typing import Any
import logging

from modules.observability import supabase

logger = logging.getLogger(__name__)

# Caps for Graph Snapshot
MAX_SEED_NODES = 8
MAX_NODES = 12
MAX_EDGES = 24


def get_graph_stats(twin_id: str) -> dict[str, Any]:
    """
    Get summary statistics about a twin's cognitive graph.
    Returns node count and top nodes for UI display.
    """
    try:
        nodes_res = supabase.rpc("get_nodes_system", {
            "t_id": twin_id,
            "limit_val": 50
        }).execute()

        nodes = nodes_res.data if nodes_res.data else []

        intent_nodes = []
        profile_nodes = []

        for node in nodes:
            node_type = node.get("type", "").lower()
            name = node.get("name", "")
            description = node.get("description", "")

            if not name:
                continue

            node_summary = {
                "name": name,
                "type": node.get("type", ""),
                "description": description[:100] + "..." if len(description) > 100 else description
            }

            if "intent" in node_type:
                intent_nodes.append(node_summary)
            else:
                profile_nodes.append(node_summary)

        top_nodes = intent_nodes[:3] + profile_nodes[:5]

        return {
            "node_count": len(nodes),
            "has_graph": len(nodes) > 0,
            "intent_count": len(intent_nodes),
            "profile_count": len(profile_nodes),
            "top_nodes": top_nodes
        }
    except Exception as e:
        logger.error(f"Error fetching graph stats: {e}")
        return {
            "node_count": 0,
            "has_graph": False,
            "intent_count": 0,
            "profile_count": 0,
            "top_nodes": []
        }

# Import observe decorator for tracing
try:
    from langfuse import observe
    _observe_available = True
except ImportError:
    _observe_available = False
    def observe(*args, **kwargs):
        def decorator(func):
            return func
        return decorator


@observe(name="graph_snapshot")
async def get_graph_snapshot(
    twin_id: str,
    query: str = None,
    max_nodes: int = MAX_NODES,
    max_edges: int = MAX_EDGES,
    max_hops: int = 2
) -> dict[str, Any]:
    """
    Build bounded, query-relevant Graph Snapshot for chat context.

    Algorithm:
    1. Seed selection via keyword match + semantic fallback
    2. N-hop expansion via edges table (configurable)
    3. Rank by seed relevance, connectedness, recency
    4. Cap to max_nodes, max_edges
    5. Compress to prompt-ready text

    Args:
        twin_id: Twin UUID
        query: User query for seed selection
        max_nodes: Maximum nodes in snapshot (default 12)
        max_edges: Maximum edges in snapshot (default 24)
        max_hops: Maximum hops for graph expansion (default 2)

    Returns:
        Dict with context_text, nodes, edges, metadata
    """
    try:
        # 1. Seed Selection (keywords + semantic fallback)
        seed_nodes = await _select_seeds(twin_id, query)
        seed_ids = [n['id'] for n in seed_nodes]

        if not seed_nodes:
            # Fallback: get recent nodes if no query match
            all_nodes = await _get_all_nodes(twin_id, limit=max_nodes)
            return _format_snapshot(all_nodes, [], query)

        # Initialize with seeds
        all_nodes = {n['id']: n for n in seed_nodes}
        all_edges = []
        current_frontier = set(seed_ids)
        visited = set(seed_ids)

        # 2. N-hop expansion (configurable)
        for _hop in range(max_hops):
            if len(all_nodes) >= max_nodes or not current_frontier:
                break

            # Expand from current frontier
            neighbor_nodes, hop_edges = await _expand_one_hop(twin_id, list(current_frontier))
            all_edges.extend(hop_edges)

            # Add new neighbors to our node set
            new_frontier = set()
            for node in neighbor_nodes:
                node_id = node['id']
                if node_id not in visited and len(all_nodes) < max_nodes:
                    all_nodes[node_id] = node
                    new_frontier.add(node_id)
                    visited.add(node_id)

            # Move to next hop frontier
            current_frontier = new_frontier

        # 3. Filter edges to only those within our node set
        final_nodes = list(all_nodes.values())
        final_node_ids = set(all_nodes.keys())
        final_edges = [
            e for e in all_edges
            if e.get('from_node_id') in final_node_ids
            and e.get('to_node_id') in final_node_ids
        ][:max_edges]

        # 4. Rank nodes (seeds first, then by recency)
        ranked_nodes = _rank_nodes(final_nodes, seed_ids)

        return _format_snapshot(ranked_nodes[:max_nodes], final_edges, query)

    except Exception as e:
        logger.error(f"Error building graph snapshot: {e}")
        return {
            "context_text": "",
            "nodes": [],
            "edges": [],
            "node_count": 0,
            "edge_count": 0,
            "query": query,
            "error": str(e)
        }


async def _select_seeds(twin_id: str, query: str) -> list[dict[str, Any]]:
    """Select seed nodes via ILIKE match on query, with semantic fallback."""
    if not query:
        return []

    try:
        # Extract keywords from query (simple split, could use NLP)
        keywords = [w.strip() for w in query.split() if len(w.strip()) > 2]

        if not keywords:
            return []

        # Build ILIKE pattern
        # Use first 3 meaningful keywords
        search_terms = keywords[:3]

        # Fetch all nodes and filter (Supabase doesn't support complex OR ILIKE easily)
        nodes_res = supabase.rpc("get_nodes_system", {
            "t_id": twin_id,
            "limit_val": 100
        }).execute()

        nodes = nodes_res.data if nodes_res.data else []

        # Score nodes by keyword matches
        scored_nodes = []
        for node in nodes:
            name = (node.get("name") or "").lower()
            desc = (node.get("description") or "").lower()

            score = 0
            for term in search_terms:
                term_lower = term.lower()
                if term_lower in name:
                    score += 3  # Name match is high value
                if term_lower in desc:
                    score += 1  # Description match

            if score > 0:
                scored_nodes.append((score, node))

        # Sort by score descending, take top seeds
        scored_nodes.sort(key=lambda x: x[0], reverse=True)
        keyword_seeds = [n for _, n in scored_nodes[:MAX_SEED_NODES]]

        # If keyword matching found < 3 seeds, try semantic fallback
        if len(keyword_seeds) < 3:
            semantic_seeds = await _select_seeds_semantic(twin_id, query, nodes)
            # Merge keyword + semantic, deduplicate by ID
            seen_ids = {s['id'] for s in keyword_seeds}
            for s in semantic_seeds:
                if s['id'] not in seen_ids and len(keyword_seeds) < MAX_SEED_NODES:
                    keyword_seeds.append(s)
                    seen_ids.add(s['id'])

        return keyword_seeds

    except Exception as e:
        logger.error(f"Error selecting seeds: {e}")
        return []


async def _select_seeds_semantic(
    twin_id: str,
    query: str,
    cached_nodes: list[dict[str, Any]] = None,
    top_k: int = 5
) -> list[dict[str, Any]]:
    """
    Select seed nodes via semantic similarity using Pinecone.

    This finds related concepts even without exact keyword matches.
    For example, "investment strategy" will find nodes about "portfolio allocation".

    Args:
        twin_id: Twin UUID
        query: User query for semantic matching
        cached_nodes: Optional pre-fetched nodes to map against
        top_k: Maximum number of semantic seeds

    Returns:
        List of matched nodes
    """
    if not query:
        return []

    try:
        from adk_core.services.vector_store import search as vector_search

        # 1. Search pgvector for similar chunks
        results = await vector_search(query, twin_id, top_k=top_k * 2)

        if not results:
            return []

        # 2. Extract source_ids from matched chunks
        source_ids = set()
        for match in results:
            if match.get("score", 0) > 0.3:  # Minimum similarity threshold
                source_id = match.get("source_id")
                if source_id:
                    source_ids.add(source_id)

        if not source_ids:
            return []

        # 4. Find nodes that reference these sources (via properties or description)
        if cached_nodes is None:
            nodes_res = supabase.rpc("get_nodes_system", {
                "t_id": twin_id,
                "limit_val": 100
            }).execute()
            cached_nodes = nodes_res.data if nodes_res.data else []

        # 5. Score nodes by source_id proximity and text similarity
        matched_nodes = []
        for node in cached_nodes:
            # Check if node references any matched source
            props = node.get("properties") or {}
            node_source = props.get("source_id") or props.get("source")

            # Also check if node description contains query terms
            desc_lower = (node.get("description") or "").lower()
            _ = query.lower()

            # Simple semantic relevance check
            is_relevant = False
            if node_source and node_source in source_ids or any(term.lower() in desc_lower for term in query.split() if len(term) > 3):
                is_relevant = True

            if is_relevant:
                matched_nodes.append(node)

        return matched_nodes[:top_k]

    except Exception as e:
        logger.warning(f"Semantic seed selection failed: {e}, falling back to empty")
        return []


async def _get_all_nodes(twin_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """Get all nodes for a twin (fallback when no query)."""
    try:
        nodes_res = supabase.rpc("get_nodes_system", {
            "t_id": twin_id,
            "limit_val": limit
        }).execute()
        return nodes_res.data if nodes_res.data else []
    except Exception as e:
        logger.error(f"Error getting all nodes: {e}")
        return []


async def _expand_one_hop(twin_id: str, node_ids: list[str]) -> tuple:
    """Get 1-hop neighbors via edges."""
    if not node_ids:
        return [], []

    try:
        # Get edges where any seed is from or to
        # Note: This is a simplification - ideally we'd use a custom RPC
        edges_res = supabase.table("edges").select("*").eq(
            "twin_id", twin_id
        ).execute()

        edges = edges_res.data if edges_res.data else []

        # Filter to edges connected to our seeds
        connected_edges = []
        neighbor_ids = set()

        for edge in edges:
            from_id = edge.get("from_node_id")
            to_id = edge.get("to_node_id")

            if from_id in node_ids:
                connected_edges.append(edge)
                if to_id not in node_ids:
                    neighbor_ids.add(to_id)
            elif to_id in node_ids:
                connected_edges.append(edge)
                if from_id not in node_ids:
                    neighbor_ids.add(from_id)

        # Fetch neighbor nodes
        neighbor_nodes = []
        if neighbor_ids:
            nodes_res = supabase.table("nodes").select("*").eq(
                "twin_id", twin_id
            ).in_("id", list(neighbor_ids)).execute()
            neighbor_nodes = nodes_res.data if nodes_res.data else []

        return neighbor_nodes, connected_edges

    except Exception as e:
        logger.error(f"Error expanding 1-hop: {e}")
        return [], []


def _rank_nodes(nodes: list[dict], seed_ids: list[str]) -> list[dict]:
    """Rank nodes: seeds first, then by updated_at."""
    seed_set = set(seed_ids)

    def sort_key(node):
        is_seed = node['id'] in seed_set
        updated = node.get('updated_at') or node.get('created_at') or ''
        return (not is_seed, updated)  # False sorts before True

    return sorted(nodes, key=sort_key, reverse=True)


def _format_snapshot(nodes: list[dict], edges: list[dict], query: str = None) -> dict[str, Any]:
    """Format snapshot into prompt-ready context."""
    if not nodes:
        return {
            "context_text": "",
            "nodes": [],
            "edges": [],
            "node_count": 0,
            "edge_count": 0,
            "query": query
        }

    # Build context text
    node_lines = []
    for n in nodes:
        name = n.get("name", "")
        node_type = n.get("type", "")
        description = n.get("description", "")
        props = n.get("properties", {}) or {}

        if not name or not description:
            continue

        props_str = ""
        if props:
            props_items = [f"{k}: {v}" for k, v in props.items()
                          if isinstance(v, (str, int, float))][:3]
            if props_items:
                props_str = f" [{', '.join(props_items)}]"

        node_lines.append(f"- {name} ({node_type}): {description}{props_str}")

    # Build edge lines
    edge_lines = []
    node_name_map = {n['id']: n.get('name', 'Unknown') for n in nodes}
    for e in edges[:10]:  # Limit edge descriptions
        from_name = node_name_map.get(e.get('from_node_id'), 'Unknown')
        to_name = node_name_map.get(e.get('to_node_id'), 'Unknown')
        edge_type = e.get('type', 'RELATED_TO')
        edge_lines.append(f"  {from_name} → {edge_type} → {to_name}")

    context_text = ""
    if node_lines:
        context_text = "MEMORIZED KNOWLEDGE (High Priority - Answer from here if relevant):\n"
        context_text += "\n".join(node_lines)
        if edge_lines:
            context_text += "\n\nKNOWN RELATIONSHIPS:\n" + "\n".join(edge_lines)

    return {
        "context_text": context_text,
        "nodes": [{"id": n['id'], "name": n.get('name'), "type": n.get('type')} for n in nodes],
        "edges": [{"id": e['id'], "type": e.get('type')} for e in edges],
        "node_count": len(nodes),
        "edge_count": len(edges),
        "query": query
    }


# Legacy function for backward compatibility
def get_graph_context_for_chat(twin_id: str, limit: int = 20) -> dict[str, Any]:
    """
    Legacy sync wrapper. Use get_graph_snapshot for new code.
    """
    try:
        nodes_res = supabase.rpc("get_nodes_system", {
            "t_id": twin_id,
            "limit_val": limit
        }).execute()

        nodes = nodes_res.data if nodes_res.data else []

        if not nodes:
            return {
                "context_text": "",
                "node_count": 0,
                "nodes_used": []
            }

        node_summaries = []
        nodes_used = []

        for n in nodes:
            name = n.get("name", "")
            node_type = n.get("type", "")
            description = n.get("description", "")
            props = n.get("properties", {}) or {}

            if not name or not description:
                continue

            props_str = ""
            if props:
                props_items = [f"{k}: {v}" for k, v in props.items()
                              if isinstance(v, (str, int, float))]
                if props_items:
                    props_str = f" [{', '.join(props_items[:3])}]"

            node_summaries.append(f"- {name} ({node_type}): {description}{props_str}")
            nodes_used.append({
                "name": name,
                "type": node_type
            })

        context_text = ""
        if node_summaries:
            context_text = "MEMORIZED KNOWLEDGE (High Priority - Answer from here if relevant):\n" + "\n".join(node_summaries)

        return {
            "context_text": context_text,
            "node_count": len(nodes_used),
            "nodes_used": nodes_used
        }
    except Exception as e:
        logger.error(f"Error fetching graph context: {e}")
        return {
            "context_text": "",
            "node_count": 0,
            "nodes_used": []
        }

def get_style_guidelines(twin_id: str) -> str:
    """
    Get explicit style/tone guidelines from the graph.
    Returns a system prompt segment.
    """
    try:
        # Fetch style nodes
        nodes_res = supabase.rpc("get_nodes_system", {
            "t_id": twin_id,
            "limit_val": 10
        }).execute()

        nodes = nodes_res.data if nodes_res.data else []
        style_instructions = []

        for n in nodes:
            node_type = n.get("type", "").lower()
            name = n.get("name", "")
            desc = n.get("description", "")

            if "style" in node_type or "communication" in node_type or "tone" in node_type:
                style_instructions.append(f"- {name}: {desc}")

        if not style_instructions:
            return ""

        return "COMMUNICATION STYLE (Must Follow):\n" + "\n".join(style_instructions)

    except Exception as e:
        logger.error(f"Error fetching style guidelines: {e}")
        return ""
