"""
Graph Memory Configuration Module

Feature flags and configuration for Neo4j + Graphiti integration.
All settings have safe defaults for production rollout.

Single-Profile Scope Migration:
- scope_id: "{tenant_id}__{creator_id}" (single-profile boundary)
- Graphiti group_id: same as scope_id
- All deduplication and uniqueness includes scope_id
"""

import os
import hashlib
from dataclasses import dataclass


# Feature flag for single-profile scope rollout
# When true: prefer scope_id, fallback to legacy group_id only if missing
SINGLE_PROFILE_SCOPE_ENABLED = os.getenv("SINGLE_PROFILE_SCOPE_ENABLED", "false").lower() == "true"


@dataclass(frozen=True)
class GraphMemoryConfig:
    """Immutable configuration for graph memory."""

    # Master kill switch
    enabled: bool = False

    # Sub-switches
    read_enabled: bool = True
    write_enabled: bool = True
    debug_headers: bool = False

    # Performance
    # Note: 2.5s budget accounts for Neo4j Aura network round-trip from typical locations
    # This is a hard cap - queries exceeding this will fail fast and fallback to degraded mode
    read_timeout_ms: int = 2500

    # Chat-specific soft budget for best-effort graph context (Phase 2)
    # If graph context isn't ready within this budget, chat continues without it
    chat_soft_budget_ms: int = 500  # 300-600ms configurable

    extraction_timeout_ms: int = 5000
    max_retries: int = 5

    # Caching
    extraction_cache_ttl: int = 3600  # Redis TTL in seconds

    # Circuit breaker
    circuit_breaker_threshold: int = 10
    circuit_breaker_cooldown_sec: int = 60

    # Schema versioning (for cache invalidation)
    schema_version: str = "1"
    extractor_version: str = "1"

    # Neo4j connection (from env)
    neo4j_uri: str | None = None
    neo4j_user: str | None = None
    neo4j_password: str | None = None
    neo4j_database: str | None = None

    @classmethod
    def from_env(cls) -> "GraphMemoryConfig":
        """Load configuration from environment variables."""
        master_enabled = os.getenv("GRAPH_MEMORY_ENABLED", "false").lower() == "true"

        return cls(
            enabled=master_enabled,
            read_enabled=os.getenv("GRAPH_MEMORY_READ_ENABLED", "true").lower() == "true",
            write_enabled=os.getenv("GRAPH_MEMORY_WRITE_ENABLED", "true").lower() == "true",
            debug_headers=os.getenv("GRAPH_MEMORY_DEBUG_HEADERS", "false").lower() == "true",
            read_timeout_ms=int(os.getenv("GRAPH_MEMORY_READ_TIMEOUT_MS", "300")),
            chat_soft_budget_ms=int(os.getenv("GRAPH_MEMORY_CHAT_SOFT_BUDGET_MS", "500")),
            extraction_timeout_ms=int(os.getenv("GRAPH_MEMORY_EXTRACTION_TIMEOUT_MS", "5000")),
            max_retries=int(os.getenv("GRAPH_MEMORY_MAX_RETRIES", "5")),
            extraction_cache_ttl=int(os.getenv("GRAPH_MEMORY_EXTRACTION_CACHE_TTL", "3600")),
            circuit_breaker_threshold=int(os.getenv("GRAPH_MEMORY_CIRCUIT_BREAKER_THRESHOLD", "10")),
            circuit_breaker_cooldown_sec=int(os.getenv("GRAPH_MEMORY_CIRCUIT_BREAKER_COOLDOWN_SEC", "60")),
            schema_version=os.getenv("GRAPH_MEMORY_SCHEMA_VERSION", "1"),
            extractor_version=os.getenv("GRAPH_MEMORY_EXTRACTOR_VERSION", "1"),
            neo4j_uri=os.getenv("NEO4J_URI"),
            neo4j_user=os.getenv("NEO4J_USER") or os.getenv("NEO4J_USERNAME"),
            neo4j_password=os.getenv("NEO4J_PASSWORD"),
            neo4j_database=os.getenv("NEO4J_DATABASE"),
        )

    def is_read_allowed(self) -> bool:
        """Check if graph memory reads are allowed."""
        return self.enabled and self.read_enabled

    def is_write_allowed(self) -> bool:
        """Check if graph memory writes are allowed."""
        return self.enabled and self.write_enabled

    # ==========================================================================
    # Scope ID Methods (Single-Profile Migration)
    # ==========================================================================

    def make_scope_id(self, tenant_id: str, creator_id: str) -> str:
        """
        Generate scope_id for single-profile isolation.

        Format: "{tenant_id}__{creator_id}"
        This is the canonical scope identifier for all graph memory operations.
        """
        return f"{tenant_id}__{creator_id}"

    def resolve_scope_id(
        self,
        tenant_id: str,
        twin_id: str,
        creator_id: str | None = None
    ) -> str:
        """
        Resolve scope_id based on feature flag and available IDs.

        When SINGLE_PROFILE_SCOPE_ENABLED is true and creator_id is provided:
            Returns: "{tenant_id}__{creator_id}"
        Otherwise (legacy mode):
            Returns: "{tenant_id}__{twin_id}"

        Args:
            tenant_id: The tenant identifier
            twin_id: The twin identifier (legacy)
            creator_id: The creator identifier (single-profile)

        Returns:
            Scope ID string for isolation
        """
        if SINGLE_PROFILE_SCOPE_ENABLED and creator_id:
            return self.make_scope_id(tenant_id, creator_id)
        # Legacy fallback
        return self.make_group_id(tenant_id, twin_id)

    def make_group_id(self, tenant_id: str, twin_id: str) -> str:
        """
        Generate Graphiti group_id for tenant-twin isolation.

        DEPRECATED: Use resolve_scope_id() for new code.
        Kept for backward compatibility during migration.
        """
        # Use double underscore as separator (alphanumeric-safe for Graphiti)
        return f"{tenant_id}__{twin_id}"

    def make_idempotency_key(
        self,
        tenant_id: str,
        twin_id: str,
        source_type: str,
        source_ref: str,
        content: str,
        validity_scope: str | None = None,
        scope_id: str | None = None
    ) -> str:
        """
        Generate deterministic idempotency key.

        CRITICAL: When scope_id is provided (single-profile mode), it is included
        in the key to ensure deduplication is scope-isolated. This prevents
        cross-scope collisions where two different profiles could have the same
        idempotency key.

        Args:
            tenant_id: The tenant identifier
            twin_id: The twin identifier
            source_type: Type of source (e.g., "chat", "document")
            source_ref: Reference to the source
            content: Content to hash for uniqueness
            validity_scope: Optional additional scope string
            scope_id: Optional scope ID for single-profile isolation

        Returns:
            Deterministic idempotency key hash
        """
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]

        # Include scope_id in key generation when available (single-profile mode)
        # This ensures deduplication is properly scoped
        if scope_id:
            key_data = f"{scope_id}:{self.schema_version}:{self.extractor_version}:{source_type}:{source_ref}:{content_hash}"
        else:
            # Legacy format (for backward compatibility during rollout)
            key_data = f"{tenant_id}:{twin_id}:{self.schema_version}:{self.extractor_version}:{source_type}:{source_ref}:{content_hash}"

        if validity_scope:
            key_data += f":{validity_scope}"

        return hashlib.sha256(key_data.encode()).hexdigest()


# Global config instance (lazy loaded)
_config: GraphMemoryConfig | None = None


def get_graph_memory_config() -> GraphMemoryConfig:
    """Get or create global config instance."""
    global _config
    if _config is None:
        _config = GraphMemoryConfig.from_env()
    return _config


def reset_config():
    """Reset config (for testing)."""
    global _config
    _config = None


def is_single_profile_enabled() -> bool:
    """Check if single-profile scope is enabled."""
    return SINGLE_PROFILE_SCOPE_ENABLED
