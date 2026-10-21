"""
Verified QnA Module: Canonical storage and retrieval of owner-verified answers.
"""
import json
import logging
from typing import Any
from difflib import SequenceMatcher
import re
from modules.observability import supabase
from modules.embeddings import get_embedding, cosine_similarity

logger = logging.getLogger(__name__)

QNA_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "if", "then", "else", "when", "what", "how", "why",
    "is", "are", "was", "were", "be", "been", "being", "do", "does", "did", "should", "would",
    "could", "can", "will", "my", "your", "their", "our", "about", "on", "in", "for", "to",
    "of", "with", "by", "at", "from", "as", "this", "that", "it", "we", "i", "you"
}


def _normalize_tokens(text: str) -> list[str]:
    if not text:
        return []
    normalized = re.sub(r"[^a-zA-Z0-9\s-]", " ", text.lower())
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return [tok for tok in normalized.split() if tok and tok not in QNA_STOPWORDS]


def _token_overlap_score(a: str, b: str) -> float:
    a_tokens = set(_normalize_tokens(a))
    b_tokens = set(_normalize_tokens(b))
    if not a_tokens or not b_tokens:
        return 0.0
    return len(a_tokens & b_tokens) / float(len(a_tokens | b_tokens))


def _fetch_verified_qna_entries(
    twin_id: str,
    group_id: str | None = None
) -> list[dict[str, Any]]:
    """
    Fetch verified QnA entries for a twin, optionally filtered by group.

    Args:
        twin_id: Twin ID to filter by
        group_id: Optional group ID to filter by permissions

    Returns:
        List of verified QnA entries
    """
    if group_id:
        # Get allowed content_ids from content_permissions
        permissions_response = supabase.table("content_permissions").select("content_id").eq(
            "group_id", group_id
        ).eq("content_type", "verified_qna").execute()

        allowed_content_ids = [perm["content_id"] for perm in (permissions_response.data or [])]

        if not allowed_content_ids:
            return []

        # Fetch verified QnA entries that match the allowed content_ids
        response = supabase.table("verified_qna").select("*").eq(
            "twin_id", twin_id
        ).eq("is_active", True).in_("id", allowed_content_ids).execute()
    else:
        # No group filter - fetch all active verified QnA entries for this twin
        response = supabase.table("verified_qna").select("*").eq(
            "twin_id", twin_id
        ).eq("is_active", True).execute()

    return response.data if response.data else []


def _exact_match_query(
    query: str,
    qna_entries: list[dict[str, Any]],
    exact_threshold: float
) -> tuple[dict[str, Any] | None, float]:
    """
    Perform exact/fuzzy matching on QnA entries.

    Args:
        query: User's query string
        qna_entries: List of QnA entries to match against
        exact_threshold: Similarity threshold for exact matching (0-1)

    Returns:
        Tuple of (best_match, best_score)
    """
    best_match = None
    best_score = 0.0

    query_normalized = query.lower().strip()
    for qna in qna_entries:
        question_normalized = qna["question"].lower().strip()

        # Check for exact match first (case-insensitive)
        if query_normalized == question_normalized:
            # Perfect match - return immediately
            return (qna, 1.0)

        # Otherwise use fuzzy matching
        similarity = SequenceMatcher(None, query_normalized, question_normalized).ratio()
        if similarity > best_score and similarity >= exact_threshold:
            best_score = similarity
            best_match = qna

    return (best_match, best_score)


def _semantic_match_query(
    query: str,
    qna_entries: list[dict[str, Any]],
    semantic_threshold: float,
    current_best_score: float
) -> tuple[dict[str, Any] | None, float]:
    """
    Perform semantic (embedding) matching on QnA entries.

    Args:
        query: User's query string
        qna_entries: List of QnA entries to match against
        semantic_threshold: Similarity threshold for semantic matching (0-1)
        current_best_score: Current best score from exact matching

    Returns:
        Tuple of (best_match, best_score)
    """
    best_match = None
    best_score = current_best_score
    best_overlap = 0.0
    query_tokens = _normalize_tokens(query)
    if not query_tokens:
        # Avoid semantic-only matches for ultra-generic prompts
        # (e.g., "who are you?") that have no lexical grounding.
        return (None, best_score)

    try:
        # Generate embedding for the query
        query_embedding = get_embedding(query)

        # Compare query embedding with stored embeddings in Postgres
        for qna in qna_entries:
            # Skip if no embedding stored
            if not qna.get("question_embedding"):
                continue

            try:
                # Parse stored embedding from JSON
                stored_embedding = json.loads(qna["question_embedding"])

                # Calculate cosine similarity
                similarity = cosine_similarity(query_embedding, stored_embedding)

                # Guardrail: semantic matches must keep lexical grounding to avoid
                # unrelated interview snippets winning on broad embedding similarity.
                overlap = _token_overlap_score(query, qna.get("question", ""))
                if overlap < 0.12:
                    continue

                # Update best match if similarity exceeds threshold and is better than current best
                if similarity >= semantic_threshold and (
                    similarity > best_score or (similarity == best_score and overlap > best_overlap)
                ):
                    best_score = similarity
                    best_match = qna
                    best_overlap = overlap
            except (json.JSONDecodeError, ValueError, TypeError) as e:
                # Skip entries with invalid embeddings
                logger.warning("Invalid embedding for QnA %s: %s", qna.get('id'), e)
                continue
    except Exception as e:
        logger.warning("Error during semantic matching: %s", e)

    return (best_match, best_score)


def _format_match_result(
    best_match: dict[str, Any],
    best_score: float
) -> dict[str, Any]:
    """
    Format a match result with citations.

    Args:
        best_match: Matched QnA entry
        best_score: Similarity score

    Returns:
        Formatted match result with citations
    """
    # Fetch citations for this QnA
    citations_res = supabase.table("citations").select("*").eq(
        "verified_qna_id", best_match["id"]
    ).execute()
    citations = citations_res.data if citations_res.data else []

    return {
        "id": best_match["id"],
        "question": best_match["question"],
        "answer": best_match["answer"],
        "similarity_score": best_score,
        "is_verified": True,
        "citations": [c["source_id"] for c in citations if c.get("source_id")]
    }


def _get_twin_id_from_escalation(escalation_id: str) -> str:
    """
    Fetch twin_id from escalation record.

    Args:
        escalation_id: ID of the escalation

    Returns:
        Twin ID
    """
    response = supabase.table("escalations").select(
        "*, messages(conversation_id, conversations(twin_id))"
    ).eq("id", escalation_id).single().execute()

    if not response.data:
        raise ValueError(f"Escalation {escalation_id} not found")

    return response.data["messages"]["conversations"]["twin_id"]


def _generate_and_store_embedding(question: str) -> str:
    """
    Generate embedding for a question and return as JSON string.

    Args:
        question: Question text to embed

    Returns:
        JSON-encoded embedding string
    """
    try:
        question_embedding = get_embedding(question)
        return json.dumps(question_embedding)
    except Exception as e:
        error_msg = f"Error generating embedding: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise ValueError(error_msg)


def _create_verified_qna_entry(
    twin_id: str,
    question: str,
    answer: str,
    question_embedding_json: str,
    owner_id: str
) -> str:
    """
    Create a verified QnA entry in the database.

    Args:
        twin_id: Twin ID
        question: Question text
        answer: Answer text
        question_embedding_json: JSON-encoded embedding
        owner_id: Owner user ID

    Returns:
        Verified QnA ID
    """
    try:
        qna_response = supabase.table("verified_qna").insert({
            "twin_id": twin_id,
            "question": question,
            "answer": answer,
            "question_embedding": question_embedding_json,
            "visibility": "private",
            "created_by": owner_id,
            "is_active": True
        }).execute()

        if not qna_response.data:
            raise ValueError("Failed to create verified QnA entry - no data returned")

        return qna_response.data[0]["id"]
    except Exception as e:
        error_msg = f"Error creating verified_qna entry: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise ValueError(error_msg)


def _create_citation_entries(verified_qna_id: str, citations: list[str]) -> None:
    """
    Create citation entries for a verified QnA.

    Args:
        verified_qna_id: Verified QnA ID
        citations: List of source/chunk IDs
    """
    if not citations:
        return

    citation_entries = [
        {
            "verified_qna_id": verified_qna_id,
            "source_id": citation,
            "chunk_id": None,
            "citation_url": None
        }
        for citation in citations
    ]
    supabase.table("citations").insert(citation_entries).execute()


async def create_verified_qna(
    question: str,
    answer: str,
    owner_id: str,
    escalation_id: str | None = None,
    citations: list[str] | None = None,
    twin_id: str | None = None,
    group_id: str | None = None,
) -> str:
    """
    Creates a verified QnA entry in Postgres.

    Args:
        escalation_id: Optional escalation ID being resolved
        question: Original question that triggered escalation
        answer: Owner's verified answer
        owner_id: ID of the user creating this QnA
        citations: Optional list of source/chunk IDs
        twin_id: Optional twin_id (will be fetched from escalation if not provided)
        group_id: Optional group ID (reserved for compatibility; currently unused)

    Returns:
        verified_qna_id: UUID of the created verified QnA entry
    """
    # Fetch escalation to get twin_id if not provided
    if not twin_id:
        if escalation_id:
            twin_id = _get_twin_id_from_escalation(escalation_id)
        else:
            raise ValueError("Either twin_id or escalation_id is required")

    # Generate embedding for question (for semantic matching)
    question_embedding_json = _generate_and_store_embedding(question)

    # Create verified_qna entry
    verified_qna_id = _create_verified_qna_entry(
        twin_id, question, answer, question_embedding_json, owner_id
    )

    # Create citation entries if provided
    _create_citation_entries(verified_qna_id, citations or [])

    return verified_qna_id


async def match_verified_qna(
    query: str,
    twin_id: str,
    group_id: str | None = None,
    use_exact: bool = True,
    use_semantic: bool = True,
    exact_threshold: float = 0.7,
    semantic_threshold: float = 0.7
) -> dict[str, Any] | None:
    """
    Matches a query against verified QnA entries using exact and/or semantic matching.
    If group_id is provided, only matches QnA entries accessible to that group.

    Args:
        query: User's query string
        twin_id: Twin ID to filter by
        group_id: Optional group ID to filter by permissions
        use_exact: Whether to use exact/fuzzy text matching
        use_semantic: Whether to use semantic (embedding) matching
        exact_threshold: Similarity threshold for exact matching (0-1)
        semantic_threshold: Similarity threshold for semantic matching (0-1)

    Returns:
        Best matching QnA entry with similarity score, or None if no match above threshold
    """
    # Fetch verified QnA entries, filtered by group if provided
    qna_entries = _fetch_verified_qna_entries(twin_id, group_id)

    if not qna_entries:
        return None

    exact_match = None
    exact_score = 0.0
    semantic_match = None
    semantic_score = 0.0

    # Exact matching: Compare query with question using fuzzy matching
    if use_exact:
        exact_match, exact_score = _exact_match_query(query, qna_entries, exact_threshold)
        # If perfect match found, return immediately
        if exact_score == 1.0 and exact_match:
            result = _format_match_result(exact_match, exact_score)
            result["match_type"] = "exact"
            return result

    # Semantic matching: Use Postgres embeddings (stored as JSON)
    if use_semantic:
        semantic_match, semantic_score = _semantic_match_query(
            query, qna_entries, semantic_threshold, 0.0
        )

    candidates: list[tuple[str, dict[str, Any], float]] = []
    if exact_match and exact_score >= exact_threshold:
        candidates.append(("exact", exact_match, exact_score))
    if semantic_match and semantic_score >= semantic_threshold:
        candidates.append(("semantic", semantic_match, semantic_score))

    if candidates:
        match_type, best_match, best_score = max(candidates, key=lambda c: c[2])
        result = _format_match_result(best_match, best_score)
        result["match_type"] = match_type
        return result

    return None


async def get_verified_qna(qna_id: str) -> dict[str, Any] | None:
    """
    Fetches a verified QnA entry with its citations and patch history.

    Args:
        qna_id: UUID of the verified QnA entry

    Returns:
        QnA entry with citations and patches, or None if not found
    """
    qna_res = supabase.table("verified_qna").select("*").eq("id", qna_id).single().execute()
    if not qna_res.data:
        return None

    qna = qna_res.data

    # Fetch citations
    citations_res = supabase.table("citations").select("*").eq(
        "verified_qna_id", qna_id
    ).execute()
    citations = citations_res.data if citations_res.data else []

    # Fetch patch history
    patches_res = supabase.table("answer_patches").select("*").eq(
        "verified_qna_id", qna_id
    ).order("patched_at", desc=True).execute()
    patches = patches_res.data if patches_res.data else []

    return {
        **qna,
        "citations": citations,
        "patches": patches
    }


async def edit_verified_qna(
    qna_id: str,
    new_answer: str,
    reason: str,
    owner_id: str
) -> bool:
    """
    Edits a verified QnA entry by creating a patch and updating the answer.

    Args:
        qna_id: UUID of the verified QnA entry
        new_answer: New answer text
        reason: Reason for the edit
        owner_id: ID of the user making the edit

    Returns:
        True if successful
    """
    # Fetch current answer
    qna_res = supabase.table("verified_qna").select("*").eq("id", qna_id).single().execute()
    if not qna_res.data:
        raise ValueError(f"Verified QnA {qna_id} not found")

    previous_answer = qna_res.data["answer"]

    # Create patch entry
    supabase.table("answer_patches").insert({
        "verified_qna_id": qna_id,
        "previous_answer": previous_answer,
        "new_answer": new_answer,
        "reason": reason,
        "patched_by": owner_id
    }).execute()

    # Update verified_qna entry
    from datetime import datetime
    supabase.table("verified_qna").update({
        "answer": new_answer,
        "updated_at": datetime.now().isoformat()
    }).eq("id", qna_id).execute()

    # Note: Embeddings are now stored in Postgres only (no Pinecone vectors)
    # The question_embedding column contains the JSON-encoded embedding for semantic matching

    return True


async def list_verified_qna(
    twin_id: str,
    visibility: str | None = None,
    group_id: str | None = None
) -> list[dict[str, Any]]:
    """
    Lists all verified QnA entries for a twin.

    Args:
        twin_id: Twin ID to filter by
        visibility: Optional visibility filter ('private', 'shared', 'public')
        group_id: Optional group ID to filter by permissions

    Returns:
        List of verified QnA entries
    """
    # Build query
    query = supabase.table("verified_qna").select("*").eq("twin_id", twin_id).eq("is_active", True)

    # Apply visibility filter if provided
    if visibility:
        query = query.eq("visibility", visibility)

    # Apply group filter if provided
    if group_id:
        # Get allowed content_ids from content_permissions
        permissions_response = supabase.table("content_permissions").select("content_id").eq(
            "group_id", group_id
        ).eq("content_type", "verified_qna").execute()

        allowed_content_ids = [perm["content_id"] for perm in (permissions_response.data or [])]

        if not allowed_content_ids:
            return []

        query = query.in_("id", allowed_content_ids)

    response = query.execute()
    return response.data if response.data else []
