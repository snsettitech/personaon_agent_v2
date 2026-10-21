#!/usr/bin/env python3
"""
Tenant Guard Module
Enforces tenant isolation at the application layer.
Prevents cross-tenant data access and ensures GDPR compliance.
"""
import logging
from functools import wraps
from typing import Any
from fastapi import HTTPException, Request
import json
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class TenantIsolationError(Exception):
    """Raised when a tenant isolation violation is detected."""
    pass


def derive_creator_ids(user: dict[str, Any]) -> list[str]:
    """
    Derive creator ids from the authenticated user payload.

    Compatibility order:
    1. Explicit `creator_ids` (new model)
    2. Explicit `creator_id`
    3. Deterministic tenant-derived creator id (`tenant_{tenant_id}`)
    """
    explicit = user.get("creator_ids")
    if isinstance(explicit, list) and explicit:
        return [str(c) for c in explicit]

    explicit_single = user.get("creator_id")
    if explicit_single:
        return [str(explicit_single)]

    tenant_id = user.get("tenant_id")
    if tenant_id:
        return [f"tenant_{tenant_id}"]

    return []


class TenantGuard:
    """
    Enforces tenant isolation for multi-tenant vector database access.

    This class ensures that users can only access data belonging to their
    assigned creators, preventing cross-tenant data leakage.
    """

    def __init__(self, user: dict[str, Any]):
        """
        Initialize TenantGuard with user information.

        Args:
            user: User dict containing id, creator_ids, role, etc.
        """
        self.user_id = user.get("id") or user.get("user_id")
        self.creator_ids = derive_creator_ids(user)
        self.role = user.get("role", "user")
        self.email = user.get("email", "unknown")

        # Admins can access all creators (with audit logging)
        self.is_admin = self.role in ["admin", "superadmin"]

    def validate_creator_access(self, creator_id: str) -> bool:
        """
        Validate that the user has access to the specified creator.

        Args:
            creator_id: The creator ID to validate access for

        Returns:
            True if access is allowed

        Raises:
            TenantIsolationError: If user doesn't have access to this creator
        """
        # Admin override (still logged)
        if self.is_admin:
            logger.info(
                f"Admin access granted: {self.user_id} ({self.email}) → "
                f"creator:{creator_id}"
            )
            return True

        # Check if user owns this creator
        if creator_id in self.creator_ids:
            logger.debug(
                f"Tenant access granted: {self.user_id} → creator:{creator_id}"
            )
            return True

        # Access denied - log the violation
        logger.warning(
            f"TENANT ISOLATION VIOLATION: User {self.user_id} ({self.email}) "
            f"attempted to access creator:{creator_id} "
            f"[authorized_creators: {self.creator_ids}]"
        )

        raise TenantIsolationError(
            f"Access denied: You do not have permission to access creator '{creator_id}'. "
            f"Your authorized creators: {', '.join(self.creator_ids) or 'None'}"
        )

    def validate_namespace_access(self, namespace: str) -> bool:
        """
        Validate access to a specific Pinecone namespace.

        Args:
            namespace: Pinecone namespace (e.g., "creator_sainath.no.1_twin_coach")

        Returns:
            True if access is allowed
        """
        # Extract creator_id from namespace
        if not namespace.startswith("creator_"):
            raise TenantIsolationError(f"Invalid namespace format: {namespace}")

        # Parse creator_id from namespace
        # Format: creator_{creator_id}_twin_{twin_id} or creator_{creator_id}
        parts = namespace.split("_")
        if len(parts) < 2:
            raise TenantIsolationError(f"Invalid namespace format: {namespace}")

        # Reconstruct creator_id (handles creator_ids with underscores)
        # creator_sainath.no.1_twin_coach → sainath.no.1
        # creator_user_123_twin_abc → user_123
        if "_twin_" in namespace:
            creator_id = namespace.split("_twin_")[0].replace("creator_", "")
        else:
            creator_id = namespace.replace("creator_", "")

        return self.validate_creator_access(creator_id)

    def get_allowed_namespaces(self) -> list[str]:
        """
        Get list of namespace patterns this user can access.

        Returns:
            List of namespace patterns (e.g., ["creator_sainath.no.1_*"])
        """
        if self.is_admin:
            return ["creator_*"]  # Admin can access all

        return [
            f"creator_{cid}_*"
            for cid in self.creator_ids
        ]

    def filter_results_by_tenant(self, results: list[Any]) -> list[Any]:
        """
        Filter query results to ensure only authorized data is returned.
        Defense in depth: secondary validation after namespace isolation.

        Args:
            results: List of Pinecone match objects

        Returns:
            Filtered list containing only authorized results
        """
        if self.is_admin:
            return results

        filtered = []
        for match in results:
            creator_id = match.metadata.get("creator_id") if hasattr(match, "metadata") else None

            if creator_id and creator_id in self.creator_ids:
                filtered.append(match)
            elif not creator_id:
                # Legacy data without creator_id - log warning
                logger.warning(
                    f"Result {match.id} missing creator_id metadata - "
                    f"excluding from results for security"
                )
            else:
                # Cross-tenant data detected - serious issue
                logger.error(
                    f"CROSS-TENANT DATA LEAKAGE DETECTED: "
                    f"Result {match.id} has creator_id {creator_id} "
                    f"but user {self.user_id} only authorized for {self.creator_ids}"
                )

        return filtered


def require_creator_access(creator_id_param: str = "creator_id"):
    """
    Decorator to enforce tenant isolation on FastAPI endpoints.

    Usage:
        @router.post("/query")
        @require_creator_access()
        async def query(
            request: QueryRequest,
            current_user: User = Depends(get_current_user)
        ):
            # Only reaches here if user owns the creator_id in request
            pass

    Args:
        creator_id_param: Name of the parameter containing creator_id
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Extract request object (first positional arg or 'request' in kwargs)
            request_obj = None
            if args and hasattr(args[0], creator_id_param):
                request_obj = args[0]
            elif 'request' in kwargs:
                request_obj = kwargs['request']

            if not request_obj:
                raise HTTPException(400, f"Request object with {creator_id_param} required")

            # Extract creator_id from request
            creator_id = getattr(request_obj, creator_id_param, None)
            if not creator_id:
                raise HTTPException(400, f"{creator_id_param} is required")

            # Extract current user
            current_user = kwargs.get('current_user') or kwargs.get('user')
            if not current_user:
                # Try to find user in args
                for arg in args:
                    if isinstance(arg, dict) and ('id' in arg or 'user_id' in arg):
                        current_user = arg
                        break

            if not current_user:
                raise HTTPException(401, "Authentication required")

            # Validate tenant access
            guard = TenantGuard(current_user)

            try:
                guard.validate_creator_access(creator_id)
            except TenantIsolationError as e:
                raise HTTPException(403, str(e))

            # Store guard in kwargs for potential use in endpoint
            kwargs['_tenant_guard'] = guard

            return await func(*args, **kwargs)
        return wrapper
    return decorator


class TenantAuditLogger:
    """
    Audit logging for tenant-related operations.
    Tracks access patterns and isolation violations.
    """

    def __init__(self):
        self.logger = logging.getLogger("tenant_audit")

    def log_vector_query(
        self,
        user_id: str,
        creator_id: str,
        twin_id: str | None,
        top_k: int,
        result_count: int,
        latency_ms: float,
        ip_address: str | None = None
    ):
        """Log a vector query operation."""
        self.logger.info(json.dumps({
            "event": "vector_query",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "creator_id": creator_id,
            "twin_id": twin_id,
            "top_k": top_k,
            "result_count": result_count,
            "latency_ms": round(latency_ms, 2),
            "ip_address": ip_address,
            "severity": "info"
        }))

    def log_isolation_violation(
        self,
        user_id: str,
        email: str,
        attempted_creator_id: str,
        authorized_creators: list[str],
        endpoint: str,
        ip_address: str | None = None
    ):
        """Log a tenant isolation violation attempt."""
        self.logger.warning(json.dumps({
            "event": "isolation_violation",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": "HIGH",
            "user_id": user_id,
            "email": email,
            "attempted_creator_id": attempted_creator_id,
            "authorized_creators": authorized_creators,
            "endpoint": endpoint,
            "ip_address": ip_address,
            "action": "blocked",
            "alert": True
        }))

    def log_data_deletion(
        self,
        user_id: str,
        creator_id: str,
        twin_id: str | None,
        vector_count: int,
        gdpr_request: bool = False
    ):
        """Log a data deletion event (important for GDPR)."""
        self.logger.info(json.dumps({
            "event": "data_deletion",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "creator_id": creator_id,
            "twin_id": twin_id,
            "type": "twin_specific" if twin_id else "creator_wide",
            "vector_count": vector_count,
            "gdpr_request": gdpr_request,
            "severity": "warning" if gdpr_request else "info"
        }))

    def log_admin_access(
        self,
        admin_id: str,
        admin_email: str,
        accessed_creator_id: str,
        reason: str
    ):
        """Log admin access to creator data."""
        self.logger.info(json.dumps({
            "event": "admin_access",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": "warning",
            "admin_id": admin_id,
            "admin_email": admin_email,
            "accessed_creator_id": accessed_creator_id,
            "reason": reason
        }))


# Convenience function for getting current user from request
def get_current_user(request: Request) -> dict[str, Any]:
    """
    Extract current user from request state (set by auth middleware).

    This assumes you have auth middleware that sets request.state.user
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "Not authenticated")
    return user


# Example usage and testing
if __name__ == "__main__":
    # Test TenantGuard
    print("Testing TenantGuard...")

    # Regular user
    user = {
        "id": "user_123",
        "email": "sainath@example.com",
        "creator_ids": ["sainath.no.1"],
        "role": "user"
    }

    guard = TenantGuard(user)

    # Should succeed
    try:
        guard.validate_creator_access("sainath.no.1")
        print("✓ Own creator access: ALLOWED")
    except TenantIsolationError:
        print("✗ Own creator access: DENIED (unexpected)")

    # Should fail
    try:
        guard.validate_creator_access("other.user")
        print("✗ Other creator access: ALLOWED (unexpected)")
    except TenantIsolationError as e:
        print(f"✓ Other creator access: DENIED ({e})")

    # Admin user
    admin = {
        "id": "admin_123",
        "email": "admin@digitalbrains.com",
        "creator_ids": [],
        "role": "admin"
    }

    admin_guard = TenantGuard(admin)

    try:
        admin_guard.validate_creator_access("any.creator")
        print("✓ Admin access: ALLOWED")
    except TenantIsolationError:
        print("✗ Admin access: DENIED (unexpected)")

    # Test namespace validation
    print("\nTesting namespace validation...")

    try:
        guard.validate_namespace_access("creator_sainath.no.1_twin_coach")
        print("✓ Own namespace: ALLOWED")
    except TenantIsolationError:
        print("✗ Own namespace: DENIED (unexpected)")

    try:
        guard.validate_namespace_access("creator_other.user_twin_coach")
        print("✗ Other namespace: ALLOWED (unexpected)")
    except TenantIsolationError:
        print("✓ Other namespace: DENIED")

    print("\nAll tests completed!")
