"""
Graph Contradiction Detector (Phase 3)

Detects contradictions between new claims and existing graph claims.
Creates review queue entries for human review (no auto-overwrite).
All operations are tenant/twin scoped via group_id or scope_id (single-profile migration).
"""

import json
import hashlib
from typing import Any
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from modules.graph_memory_core import GraphMemoryCore
from modules.graph_memory_config import get_graph_memory_config, is_single_profile_enabled
from modules.observability import supabase


class ContradictionSeverity(Enum):
    """Severity levels for contradictions."""
    LOW = "low"          # Minor discrepancy, may be clarification
    MEDIUM = "medium"    # Notable difference, needs review
    HIGH = "high"        # Clear contradiction, urgent review


@dataclass
class Contradiction:
    """A detected contradiction between claims."""
    contradiction_id: str
    new_claim_id: str
    new_claim_text: str
    existing_claim_id: str
    existing_claim_text: str
    severity: ContradictionSeverity
    explanation: str
    confidence: float
    detected_at: str
    status: str  # 'pending', 'reviewed', 'resolved'
    resolution: str | None = None


class GraphContradictionDetector:
    """
    Detects contradictions between claims.
    Creates review queue entries for human review.

    Single-Profile Scope Migration:
    - When scope_id is provided, uses scope_id for isolation (new pattern)
    - Falls back to group_id (tenant_id__twin_id) for backward compatibility

    Usage:
        # New pattern (single-profile scope)
        detector = GraphContradictionDetector(
            tenant_id=tenant_id,
            twin_id=twin_id,
            scope_id=f"{tenant_id}__{creator_id}",
            correlation_id=correlation_id
        )

        # Legacy pattern (backward compatible)
        detector = GraphContradictionDetector(tenant_id, twin_id)
        contradictions = await detector.check_contradictions(new_claims)
    """

    def __init__(
        self,
        tenant_id: str,
        twin_id: str,
        scope_id: str | None = None,
        correlation_id: str | None = None
    ):
        self.tenant_id = tenant_id
        self.twin_id = twin_id
        self.correlation_id = correlation_id or "no-correlation"
        self.config = get_graph_memory_config()

        # Single-profile scope migration: use scope_id when available and enabled
        self.single_profile_enabled = is_single_profile_enabled()
        self.scope_id = scope_id

        # Legacy group_id for backward compatibility
        self.group_id = self.config.make_group_id(tenant_id, twin_id)

        # Effective scope for operations (scope_id takes precedence when enabled)
        self._effective_scope = self.scope_id if (self.single_profile_enabled and self.scope_id) else self.group_id

        self._client: GraphMemoryCore | None = None

    def _get_client(self) -> GraphMemoryCore | None:
        """Lazy initialize GraphMemoryCore client."""
        if self._client is not None:
            return self._client

        if not self.config.is_read_allowed():
            return None

        # GraphMemoryCore handles its own scope resolution internally
        self._client = GraphMemoryCore(
            tenant_id=self.tenant_id,
            twin_id=self.twin_id,
            correlation_id=self.correlation_id
        )
        return self._client

    def _make_queue_id(self, claim_id: str) -> str:
        """
        Generate queue ID with proper scope isolation.

        Uses scope_id when single-profile mode is enabled,
        otherwise falls back to group_id for backward compatibility.

        Args:
            claim_id: The claim identifier

        Returns:
            Scoped queue ID string
        """
        scope = self._effective_scope
        return f"{scope}:{claim_id}"

    async def _get_existing_claims(
        self,
        scope: str = "twin"
    ) -> list[dict[str, Any]]:
        """
        Get existing claims from the graph for contradiction checking.

        Single-Profile Scope Migration:
        - When scope_id is set and single-profile is enabled, queries by scope_id
        - Otherwise queries by legacy group_id for backward compatibility

        Args:
            scope: 'twin' (only this twin/scope) or 'tenant' (across tenant)

        Returns:
            List of existing claims
        """
        client = self._get_client()
        if not client:
            return []

        try:
            # Use scope-appropriate query method
            if self.single_profile_enabled and self.scope_id:
                # Single-profile scope: query by scope_id
                if scope == "tenant":
                    # Search across tenant (all scopes within tenant)
                    results = await client.search_by_tenant(
                        tenant_id=self.tenant_id,
                        query="*",
                        limit=100
                    )
                else:
                    # Search within specific scope
                    results = await client.search_by_scope(
                        scope_id=self.scope_id,
                        query="*",
                        limit=100
                    )
            else:
                # Legacy: query by group_id (tenant_id__twin_id)
                if scope == "tenant":
                    results = await client.search_by_tenant(
                        tenant_id=self.tenant_id,
                        query="*",
                        limit=100
                    )
                else:
                    # Search within twin scope (using legacy group_id)
                    results = await client.search(
                        query="*",
                        num_results=100
                    )

            # Convert episodes to claim format
            claims = []
            for result in results:
                claims.append({
                    'claim_id': result.get('id', 'unknown'),
                    'text': result.get('content', result.get('name', '')),
                    'source': 'graph',
                    'scope_id': result.get('scope_id', self.group_id)
                })

            return claims

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"[ContradictionDetector] Failed to get existing claims: {e}")
            return []

    async def check_contradictions(
        self,
        new_claims: list[dict[str, Any]],
        evaluation_scope: str = "twin"
    ) -> list[Contradiction]:
        """
        Check new claims against existing graph claims for contradictions.

        Args:
            new_claims: List of new claims to check (dict with 'text', 'claim_id')
            evaluation_scope: 'twin' (only this twin) or 'tenant' (across tenant)

        Returns:
            List of detected contradictions
        """
        client = self._get_client()
        if not client:
            return []

        all_contradictions = []

        for new_claim in new_claims:
            # Find potentially related existing claims
            related_claims = await self._find_related_claims(
                new_claim.get('text', ''),
                scope=evaluation_scope
            )

            for existing_claim in related_claims:
                # Check for contradiction
                is_contradiction, severity, explanation, confidence = \
                    await self._evaluate_contradiction(
                        new_claim.get('text', ''),
                        existing_claim.get('text', '')
                    )

                if is_contradiction and confidence > 0.7:
                    contradiction = Contradiction(
                        contradiction_id=self._generate_contradiction_id(
                            new_claim.get('claim_id', ''),
                            existing_claim.get('claim_id', '')
                        ),
                        new_claim_id=new_claim.get('claim_id', ''),
                        new_claim_text=new_claim.get('text', ''),
                        existing_claim_id=existing_claim.get('claim_id', ''),
                        existing_claim_text=existing_claim.get('text', ''),
                        severity=severity,
                        explanation=explanation,
                        confidence=confidence,
                        detected_at=datetime.utcnow().isoformat(),
                        status='pending'
                    )
                    all_contradictions.append(contradiction)

        return all_contradictions

    async def _find_related_claims(
        self,
        query_text: str,
        scope: str = "twin",
        top_k: int = 5
    ) -> list[dict[str, Any]]:
        """
        Find existing claims that might be related to the query text.

        Single-Profile Scope Migration:
        - When scope_id is set and single-profile is enabled, searches within scope
        - Otherwise uses legacy group_id search for backward compatibility

        Args:
            query_text: Text to search for
            scope: 'twin' or 'tenant'
            top_k: Number of results

        Returns:
            List of related claims
        """
        client = self._get_client()
        if not client:
            return []

        try:
            # Search graph for related content with scope-aware search
            if self.single_profile_enabled and self.scope_id:
                # Single-profile scope search
                if scope == "tenant":
                    results = await client.search_by_tenant(
                        tenant_id=self.tenant_id,
                        query=query_text,
                        limit=top_k
                    )
                else:
                    results = await client.search_by_scope(
                        scope_id=self.scope_id,
                        query=query_text,
                        limit=top_k
                    )
            else:
                # Legacy search (backward compatible)
                results = await client.search(query_text, num_results=top_k)

            # Convert episodes to claim format
            claims = []
            for result in results:
                claims.append({
                    'claim_id': result.get('id', 'unknown'),
                    'text': result.get('content', result.get('name', '')),
                    'source': 'graph',
                    'scope_id': result.get('scope_id', self.group_id)
                })

            return claims

        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"[ContradictionDetector] Failed to find related claims: {e}")
            return []

    async def _evaluate_contradiction(
        self,
        claim1: str,
        claim2: str
    ) -> tuple[bool, ContradictionSeverity, str, float]:
        """
        Use LLM to evaluate if two claims contradict.

        Returns:
            (is_contradiction, severity, explanation, confidence)
        """
        from modules.clients import openai_client

        prompt = f"""Evaluate whether these two claims contradict each other.

Claim A: "{claim1}"

Claim B: "{claim2}"

Analyze:
1. Do these claims express opposing views on the same topic?
2. Can both be true simultaneously?
3. What is the severity of any contradiction?

Respond in JSON format:
{{
  "contradiction": true/false,
  "severity": "low|medium|high",
  "explanation": "Brief explanation of the contradiction or why they don't contradict",
  "confidence": 0.0-1.0
}}

Severity guidelines:
- low: Minor discrepancy, could be clarification or nuance
- medium: Notable difference in position or preference
- high: Clear, direct contradiction that cannot both be true"""

        try:
            response = await openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a precise contradiction detection assistant."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1,
                max_tokens=500
            )

            result = json.loads(response.choices[0].message.content)

            is_contradiction = result.get('contradiction', False)
            severity_str = result.get('severity', 'low')
            explanation = result.get('explanation', '')
            confidence = result.get('confidence', 0.0)

            severity = ContradictionSeverity(severity_str.lower())

            return is_contradiction, severity, explanation, confidence

        except Exception as e:
            # On error, assume no contradiction
            return False, ContradictionSeverity.LOW, f"Error evaluating: {e}", 0.0

    def _generate_contradiction_id(self, claim_id1: str, claim_id2: str) -> str:
        """
        Generate deterministic contradiction ID.

        Uses effective scope (scope_id when enabled, else group_id) for isolation.
        """
        # Sort to ensure consistency
        ids = sorted([claim_id1, claim_id2])
        scope = self._effective_scope
        content = f"{scope}:{ids[0]}:{ids[1]}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    async def create_review_queue_entries(
        self,
        contradictions: list[Contradiction]
    ) -> list[str]:
        """
        Create review queue entries in Supabase for contradictions.

        Single-Profile Scope Migration:
        - Stores scope_id when single-profile mode is enabled
        - Always stores group_id for backward compatibility

        Args:
            contradictions: List of contradictions to queue

        Returns:
            List of review queue entry IDs
        """
        entry_ids = []

        for contradiction in contradictions:
            try:
                # Check if already exists (idempotency)
                existing = supabase.table("graph_contradiction_queue").select("id").eq(
                    "contradiction_id", contradiction.contradiction_id
                ).execute()

                if existing.data:
                    entry_ids.append(existing.data[0]['id'])
                    continue

                # Build insert data with scope-aware fields
                insert_data = {
                    "tenant_id": self.tenant_id,
                    "twin_id": self.twin_id,
                    "group_id": self.group_id,
                    "contradiction_id": contradiction.contradiction_id,
                    "new_claim_id": contradiction.new_claim_id,
                    "new_claim_text": contradiction.new_claim_text,
                    "existing_claim_id": contradiction.existing_claim_id,
                    "existing_claim_text": contradiction.existing_claim_text,
                    "severity": contradiction.severity.value,
                    "explanation": contradiction.explanation,
                    "confidence": contradiction.confidence,
                    "status": contradiction.status,
                    "detected_at": contradiction.detected_at,
                    "correlation_id": self.correlation_id
                }

                # Add scope_id when single-profile mode is enabled
                if self.single_profile_enabled and self.scope_id:
                    insert_data["scope_id"] = self.scope_id

                # Create entry
                result = supabase.table("graph_contradiction_queue").insert(insert_data).execute()

                if result.data:
                    entry_ids.append(result.data[0]['id'])

            except Exception as e:
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"[ContradictionDetector] Failed to create queue entry: {e}")

        return entry_ids


async def process_contradiction_evaluation_job(
    tenant_id: str,
    twin_id: str,
    payload: dict[str, Any],
    correlation_id: str | None = None
) -> bool:
    """
    Process a contradiction evaluation outbox job.
    Called by the background worker.

    Single-Profile Scope Migration:
    - Extracts scope_id from payload when available
    - Falls back to legacy group_id for backward compatibility

    Args:
        tenant_id: Tenant ID
        twin_id: Twin ID
        payload: Job payload with claims_context, evaluation_scope, optional scope_id
        correlation_id: For tracing

    Returns:
        True if successful
    """
    try:
        # Extract scope_id from payload (single-profile migration)
        scope_id = payload.get('scope_id')

        detector = GraphContradictionDetector(
            tenant_id=tenant_id,
            twin_id=twin_id,
            scope_id=scope_id,
            correlation_id=correlation_id
        )

        claims_context = payload.get('claims_context', {})
        evaluation_scope = payload.get('evaluation_scope', 'twin')

        # Extract claims from context
        new_claims = [{
            'claim_id': f"claim-{hash(claims_context.get('answer', '')) & 0xFFFFFFFF}",
            'text': claims_context.get('answer', ''),
            'source': 'escalation'
        }]

        # Check for contradictions
        contradictions = await detector.check_contradictions(
            new_claims=new_claims,
            evaluation_scope=evaluation_scope
        )

        if contradictions:
            # Create review queue entries
            entry_ids = await detector.create_review_queue_entries(contradictions)

            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"[ContradictionDetector] Created {len(entry_ids)} review entries")

        return True

    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"[ContradictionDetector] Failed to process job: {e}")
        return False
