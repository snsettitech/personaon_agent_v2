"""
Graph Memory Circuit Breaker

Multi-instance safe circuit breaker using Redis-backed shared state.
Implements CLOSED -> OPEN -> HALF_OPEN state machine with cooldown.

Single-Profile Scope Migration:
- Redis key: graph_cb:{scope_id}
- scope_id: "{tenant_id}__{creator_id}" (single-profile boundary)
"""

import time
import logging
from enum import Enum
from dataclasses import dataclass

from modules.graph_memory_config import get_graph_memory_config

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"       # Normal operation
    OPEN = "open"          # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery


@dataclass
class CircuitStatus:
    state: CircuitState
    failure_count: int
    last_failure_time: float | None
    last_success_time: float | None


class GraphCircuitBreaker:
    """
    Redis-backed circuit breaker for multi-instance deployments.

    Key pattern: graph_cb:{scope_id}
    Value: JSON with state, failure_count, last_failure_time

    Single-Profile Scope:
    - scope_id: "{tenant_id}__{creator_id}"
    - Provides isolation per profile
    """

    def __init__(self, scope_id: str, tenant_id: str | None = None, twin_id: str | None = None):
        """
        Initialize circuit breaker.

        Args:
            scope_id: Scope ID for isolation (format: "{tenant_id}__{creator_id}")
            tenant_id: Tenant ID (legacy, for backward compat)
            twin_id: Twin ID (legacy, for backward compat)
        """
        self.scope_id = scope_id
        self.tenant_id = tenant_id  # Kept for logging/backward compat
        self.twin_id = twin_id  # Kept for logging/backward compat
        self.config = get_graph_memory_config()
        # Redis key uses scope_id for single-profile isolation
        self.redis_key = f"graph_cb:{scope_id}"
        self._local_cache: CircuitStatus | None = None
        self._cache_time: float = 0
        self._cache_ttl: float = 1.0  # Local cache TTL in seconds

    def _get_redis_client(self):
        """Get Redis client from job_queue module."""
        try:
            from modules.job_queue import get_redis_client
            return get_redis_client()
        except Exception:
            return None

    def _load_status(self) -> CircuitStatus:
        """Load circuit status from Redis or local cache."""
        now = time.time()

        # Check local cache
        if self._local_cache and (now - self._cache_time) < self._cache_ttl:
            return self._local_cache

        client = self._get_redis_client()

        if not client:
            # Redis unavailable - use local state only
            if self._local_cache:
                return self._local_cache
            return CircuitStatus(
                state=CircuitState.CLOSED,
                failure_count=0,
                last_failure_time=None,
                last_success_time=None
            )

        try:
            data = client.get(self.redis_key)
            if data:
                import json
                parsed = json.loads(data)
                status = CircuitStatus(
                    state=CircuitState(parsed.get("state", "closed")),
                    failure_count=parsed.get("failure_count", 0),
                    last_failure_time=parsed.get("last_failure_time"),
                    last_success_time=parsed.get("last_success_time")
                )
            else:
                status = CircuitStatus(
                    state=CircuitState.CLOSED,
                    failure_count=0,
                    last_failure_time=None,
                    last_success_time=None
                )

            # Update local cache
            self._local_cache = status
            self._cache_time = now
            return status

        except Exception as e:
            logger.warning(f"[CircuitBreaker] Failed to load status from Redis: {e}")
            return CircuitStatus(
                state=CircuitState.CLOSED,
                failure_count=0,
                last_failure_time=None,
                last_success_time=None
            )

    def _save_status(self, status: CircuitStatus):
        """Save circuit status to Redis."""
        # Update local cache
        self._local_cache = status
        self._cache_time = time.time()

        client = self._get_redis_client()
        if not client:
            logger.debug("[CircuitBreaker] Redis unavailable, using local state only")
            return

        try:
            import json
            data = json.dumps({
                "state": status.state.value,
                "failure_count": status.failure_count,
                "last_failure_time": status.last_failure_time,
                "last_success_time": status.last_success_time
            })
            # Expire after 24 hours to clean up unused circuits
            client.setex(self.redis_key, 86400, data)
        except Exception as e:
            logger.warning(f"[CircuitBreaker] Failed to save status to Redis: {e}")

    def is_open(self) -> bool:
        """Check if circuit is open (failing fast)."""
        status = self._load_status()

        if status.state == CircuitState.CLOSED:
            return False

        if status.state == CircuitState.OPEN:
            # Check cooldown
            if status.last_failure_time:
                elapsed = time.time() - status.last_failure_time
                if elapsed > self.config.circuit_breaker_cooldown_sec:
                    # Transition to HALF_OPEN
                    new_status = CircuitStatus(
                        state=CircuitState.HALF_OPEN,
                        failure_count=status.failure_count,
                        last_failure_time=status.last_failure_time,
                        last_success_time=status.last_success_time
                    )
                    self._save_status(new_status)
                    logger.info(f"[CircuitBreaker] {self.scope_id[:40]}... transitioning OPEN -> HALF_OPEN")
                    return False  # Allow probe
            return True

        if status.state == CircuitState.HALF_OPEN:
            return False  # Allow probe requests

        return False

    def record_success(self):
        """Record successful operation."""
        status = self._load_status()

        if status.state == CircuitState.HALF_OPEN:
            # Recovery confirmed - close circuit
            new_status = CircuitStatus(
                state=CircuitState.CLOSED,
                failure_count=0,
                last_failure_time=None,
                last_success_time=time.time()
            )
            self._save_status(new_status)
            logger.info(f"[CircuitBreaker] {self.scope_id[:40]}... transitioning HALF_OPEN -> CLOSED")
        else:
            # Just update success time
            status.last_success_time = time.time()
            self._save_status(status)

    def record_failure(self) -> bool:
        """
        Record failed operation.
        Returns True if circuit should open.
        """
        status = self._load_status()
        now = time.time()

        new_failure_count = status.failure_count + 1
        should_open = False

        if status.state == CircuitState.HALF_OPEN:
            # Failed in half-open - go back to open
            should_open = True
            new_state = CircuitState.OPEN
        elif new_failure_count >= self.config.circuit_breaker_threshold:
            # Threshold reached - open circuit
            should_open = True
            new_state = CircuitState.OPEN
        else:
            new_state = CircuitState.CLOSED

        new_status = CircuitStatus(
            state=new_state,
            failure_count=new_failure_count,
            last_failure_time=now,
            last_success_time=status.last_success_time
        )
        self._save_status(new_status)

        if should_open:
            logger.warning(
                f"[CircuitBreaker] {self.scope_id[:40]}... OPENING after "
                f"{new_failure_count} failures"
            )

        return should_open

    def get_status(self) -> dict:
        """Get current status for monitoring."""
        status = self._load_status()
        return {
            "state": status.state.value,
            "failure_count": status.failure_count,
            "last_failure_time": status.last_failure_time,
            "last_success_time": status.last_success_time,
            "is_open": self.is_open(),
            "scope_id": self.scope_id,
            "tenant_id": self.tenant_id,
            "twin_id": self.twin_id
        }


# Global breaker cache
_breaker_cache: dict = {}


def get_circuit_breaker(
    scope_id: str,
    tenant_id: str | None = None,
    twin_id: str | None = None
) -> GraphCircuitBreaker:
    """
    Get or create circuit breaker for scope.

    Single-Profile Mode:
        get_circuit_breaker("tenant_123__creator_456")

    Legacy Mode (backward compatibility):
        get_circuit_breaker("tenant_123__twin_789", tenant_id="123", twin_id="789")
    """
    key = scope_id
    if key not in _breaker_cache:
        _breaker_cache[key] = GraphCircuitBreaker(scope_id, tenant_id, twin_id)
    return _breaker_cache[key]


def get_circuit_breaker_legacy(tenant_id: str, twin_id: str) -> GraphCircuitBreaker:
    """
    Legacy circuit breaker getter (backward compatibility).

    Creates scope_id from tenant_id and twin_id.
    """
    config = get_graph_memory_config()
    scope_id = config.make_group_id(tenant_id, twin_id)
    return get_circuit_breaker(scope_id, tenant_id, twin_id)


def reset_all_breakers():
    """Reset all breakers (for testing)."""
    global _breaker_cache
    _breaker_cache = {}
