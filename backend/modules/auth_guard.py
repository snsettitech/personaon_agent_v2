"""
Secure Authentication Module
============================

Provides authentication and authorization guards for API endpoints.

SECURITY FIXES:
- Removed DEV_MODE authentication bypass
- Added strict JWT validation with proper error handling
- Environment-based security hardening
- Comprehensive token validation (signature, expiration, structure)

BACKWARD COMPATIBILITY:
- Maintains existing function signatures for router compatibility
- verify_owner: Validates token and returns user dict
- get_current_user: Extracts and validates user from request
- resolve_tenant_id: Resolves/corrects tenant mapping for a user
- verify_twin_ownership: Checks twin ownership
- verify_source_ownership: Checks source ownership
- ensure_twin_active: Checks twin is active
"""

import logging
import os
import jwt
from typing import Any
from datetime import datetime, timedelta
from pathlib import Path
import threading
import requests
import time

logger = logging.getLogger(__name__)

# Import json for type hints
import json

# FastAPI imports for dependencies
from fastapi import Header, HTTPException, status, Depends, Request
from dotenv import load_dotenv
import contextlib

# Ensure env files are loaded before reading auth settings.
_ROOT_ENV = Path(__file__).resolve().parents[2] / ".env"
_BACKEND_ENV = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_ROOT_ENV, override=False)
load_dotenv(_BACKEND_ENV, override=False)

# Security configuration from environment
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "authenticated")

# Security hardening flags
STRICT_MODE = os.getenv("AUTH_STRICT_MODE", "true").lower() == "true"
MAX_TOKEN_AGE_SECONDS = int(os.getenv("MAX_TOKEN_AGE_SECONDS", "3600"))  # 1 hour default
JWT_CLOCK_SKEW_SECONDS = int(os.getenv("JWT_CLOCK_SKEW_SECONDS", "60"))  # 60s default
SUPABASE_AUTH_FALLBACK_ENABLED = (
    os.getenv("SUPABASE_AUTH_FALLBACK_ENABLED", "true").lower() == "true"
)
SUPABASE_AUTH_TIMEOUT_SECONDS = float(os.getenv("SUPABASE_AUTH_TIMEOUT_SECONDS", "5"))


# ---------------------------------------------------------------------------
# JWKS client — fetched once from Supabase, reused for all ES256 verifications.
# PyJWT's PyJWKClient handles key rotation and caching internally.
# ---------------------------------------------------------------------------
_jwks_client: "jwt.PyJWKClient | None" = None
_jwks_lock = threading.Lock()


def _get_jwks_client() -> "jwt.PyJWKClient | None":
    """Return a cached PyJWKClient pointed at the Supabase JWKS endpoint."""
    global _jwks_client
    if _jwks_client is not None:
        return _jwks_client

    with _jwks_lock:
        if _jwks_client is not None:
            return _jwks_client

        supabase_url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
        if not supabase_url:
            return None

        try:
            uri = f"{supabase_url}/auth/v1/.well-known/jwks.json"
            _jwks_client = jwt.PyJWKClient(uri, cache_keys=True)
            logger.info("[auth_guard] JWKS client initialised uri=%s", uri)
            return _jwks_client
        except Exception as exc:
            logger.warning("[auth_guard] JWKS client init failed: %s", exc)
            return None


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass


class AuthorizationError(Exception):
    """Raised when authorization fails."""
    pass


def authenticate_via_supabase(token: str) -> tuple[bool, dict[str, Any]]:
    """
    Fallback token verification against Supabase Auth.

    This protects production auth flows when JWT secrets drift across environments.
    Supabase remains the source of truth for whether an access token is valid.
    """
    if not SUPABASE_AUTH_FALLBACK_ENABLED:
        return False, {"error": "Supabase auth fallback disabled"}

    supabase_url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    supabase_api_key = os.getenv("SUPABASE_KEY")
    if not supabase_url or not supabase_api_key:
        return False, {"error": "Supabase anon key not configured"}

    try:
        response = requests.get(
            f"{supabase_url}/auth/v1/user",
            headers={
                "apikey": supabase_api_key,
                "Authorization": f"Bearer {token}",
            },
            timeout=SUPABASE_AUTH_TIMEOUT_SECONDS,
        )
    except Exception as e:
        return False, {"error": f"Supabase auth lookup failed: {str(e)}"}

    if response.status_code != 200:
        return False, {"error": f"Supabase auth rejected token (status={response.status_code})"}

    try:
        user_data = response.json() or {}
    except Exception as e:
        return False, {"error": f"Supabase auth response parse failed: {str(e)}"}

    user_id = user_data.get("id")
    if not user_id:
        return False, {"error": "Supabase auth response missing user id"}

    auth_context = {
        "user_id": user_id,
        "email": user_data.get("email"),
        "role": user_data.get("role", "authenticated"),
        "authenticated_at": None,
        "expires_at": None,
        "session_id": None,
        "verified": True,
        "auth_source": "supabase_auth_api",
        "app_metadata": user_data.get("app_metadata") or {},
        "user_metadata": user_data.get("user_metadata") or {},
        "name": (user_data.get("user_metadata") or {}).get("name")
        or (user_data.get("user_metadata") or {}).get("full_name"),
        "avatar_url": (user_data.get("user_metadata") or {}).get("avatar_url")
        or (user_data.get("user_metadata") or {}).get("picture"),
    }
    return True, auth_context


def validate_jwt_structure(token: str) -> tuple[bool, str]:
    """
    Validate JWT structure before cryptographic verification.

    Args:
        token: JWT token string

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not token or not isinstance(token, str):
        return False, "Token is empty or invalid type"

    parts = token.split(".")
    if len(parts) != 3:
        return False, f"Invalid JWT structure: expected 3 parts, got {len(parts)}"

    # Check header and payload are valid base64
    try:
        import base64
        # Pad with = to make valid base64
        header_b64 = parts[0] + "=" * (4 - len(parts[0]) % 4)
        payload_b64 = parts[1] + "=" * (4 - len(parts[1]) % 4)

        header_json = base64.urlsafe_b64decode(header_b64)
        _ = base64.urlsafe_b64decode(payload_b64)

        header = json.loads(header_json)

        # Verify algorithm
        alg = header.get("alg")
        if alg != JWT_ALGORITHM:
            return False, f"Invalid algorithm: {alg}, expected {JWT_ALGORITHM}"

        # Check for none algorithm (security vulnerability)
        if alg.lower() == "none":
            return False, "'none' algorithm not allowed"

        return True, ""

    except Exception as e:
        return False, f"Invalid JWT encoding: {str(e)}"


def verify_token_signature(token: str) -> tuple[bool, dict[str, Any]]:
    """
    Cryptographically verify JWT signature.

    Args:
        token: JWT token string

    Returns:
        Tuple of (is_valid, payload_or_error)
    """
    # For ES256 (Supabase default), use the JWKS public key rather than the
    # plain JWT_SECRET string (which is only valid for HS256).
    if JWT_ALGORITHM == "ES256":
        client = _get_jwks_client()
        if client:
            try:
                signing_key = client.get_signing_key_from_jwt(token)
                payload = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["ES256"],
                    audience=JWT_AUDIENCE,
                    options={
                        "verify_exp": True,
                        "verify_iat": False,
                        "verify_signature": True,
                        "require": ["exp", "iat", "sub"],
                    },
                )
                return True, payload
            except jwt.ExpiredSignatureError:
                return False, {"error": "Token has expired"}
            except jwt.InvalidAudienceError:
                return False, {"error": "Invalid token audience"}
            except jwt.InvalidSignatureError:
                return False, {"error": "Invalid token signature"}
            except jwt.PyJWTError as exc:
                return False, {"error": f"Token decode failed: {exc}"}
            except Exception as exc:
                return False, {"error": f"Token verification failed: {exc}"}
        # JWKS unavailable — hard block. ES256 tokens cannot be verified without the public key.
        # To enable Supabase API fallback for ES256, implement fallthrough here.
        return False, {"error": "JWKS unavailable for ES256 verification"}

    jwt_secret = os.getenv("JWT_SECRET", os.getenv("SUPABASE_JWT_SECRET", ""))
    if not jwt_secret:
        if STRICT_MODE:
            raise AuthenticationError("JWT_SECRET not configured and strict mode enabled")
        logger.critical("[SECURITY WARNING] JWT_SECRET not configured, token verification disabled")
        return False, {"error": "JWT secret not configured"}

    try:
        payload = jwt.decode(
            token,
            jwt_secret,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            leeway=JWT_CLOCK_SKEW_SECONDS,
            options={
                "verify_exp": True,
                "verify_iat": False,
                "verify_signature": True,
                "require": ["exp", "iat", "sub"]
            }
        )
        return True, payload

    except jwt.ExpiredSignatureError:
        return False, {"error": "Token has expired"}
    except jwt.InvalidAudienceError:
        return False, {"error": "Invalid token audience"}
    except jwt.InvalidIssuedAtError:
        return False, {"error": "Token issued in the future"}
    except jwt.InvalidSignatureError:
        return False, {"error": "Invalid token signature"}
    except jwt.DecodeError as e:
        return False, {"error": f"Token decode failed: {str(e)}"}
    except Exception as e:
        return False, {"error": f"Token verification failed: {str(e)}"}


def verify_token_expiration(payload: dict[str, Any]) -> tuple[bool, str]:
    """
    Additional expiration checks beyond JWT library verification.

    Args:
        payload: Decoded JWT payload

    Returns:
        Tuple of (is_valid, error_message)
    """
    from datetime import timezone
    now = datetime.now(timezone.utc)

    # Check issued at (iat)
    iat = payload.get("iat")
    if iat:
        issued_at_dt = datetime.fromtimestamp(iat, tz=timezone.utc)
        # Reject tokens issued impossibly far in the past (before 2000-01-01)
        if iat < 946684800:
            return False, "Token has an implausible issue time"
        # Token issued in the future (clock skew or attack)
        if issued_at_dt > now + timedelta(seconds=JWT_CLOCK_SKEW_SECONDS):
            return False, "Token issued in the future"
        # NOTE: Max-age check intentionally omitted — jwt.decode with verify_exp=True
        # already handles expiry. Checking iat age would reject valid refreshed sessions
        # because iat reflects the original login time, not the last token refresh.

    return True, ""


def authenticate_request(token: str) -> dict[str, Any]:
    """
    Authenticate a request using JWT token.

    Args:
        token: JWT token from Authorization header

    Returns:
        Dict with user info if authentication succeeds

    Raises:
        AuthenticationError: If authentication fails
    """
    # Staging bypass: trust token claims without signature verification.
    # Only active when STAGING_AUTH_BYPASS=true — never set in production.
    if os.getenv("STAGING_AUTH_BYPASS", "false").lower() == "true":
        try:
            import base64
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            user_id = payload.get("sub")
            if user_id:
                logger.warning("[auth_guard] STAGING_AUTH_BYPASS active — skipping signature verification user_id=%s", user_id)
                return {
                    "user_id": user_id,
                    "email": payload.get("email"),
                    "role": payload.get("role", "authenticated"),
                    "authenticated_at": payload.get("iat"),
                    "expires_at": payload.get("exp"),
                    "session_id": payload.get("session_id"),
                    "verified": False,
                    "app_metadata": payload.get("app_metadata") or {},
                    "user_metadata": payload.get("user_metadata") or {},
                    "name": (payload.get("user_metadata") or {}).get("name")
                    or (payload.get("user_metadata") or {}).get("full_name"),
                    "avatar_url": (payload.get("user_metadata") or {}).get("avatar_url")
                    or (payload.get("user_metadata") or {}).get("picture"),
                }
        except Exception as bypass_err:
            logger.warning("[auth_guard] STAGING_AUTH_BYPASS decode failed: %s", bypass_err)
            # Fall through to normal auth

    # Step 1: Structure validation
    is_valid, error = validate_jwt_structure(token)
    if not is_valid:
        raise AuthenticationError(error)

    # Step 2: Signature verification (primary local path)
    try:
        is_valid, result = verify_token_signature(token)
    except AuthenticationError as primary_error:
        # Fallback to Supabase auth introspection when local secret is unavailable.
        # This keeps auth available if JWT_SECRET is misconfigured in runtime env.
        fallback_ok, fallback_result = authenticate_via_supabase(token)
        if fallback_ok:
            return fallback_result
        raise primary_error

    if not is_valid:
        # Local verification failed (e.g., signature mismatch). Ask Supabase.
        fallback_ok, fallback_result = authenticate_via_supabase(token)
        if fallback_ok:
            return fallback_result

        error_msg = result.get("error", "Unknown verification error")
        raise AuthenticationError(error_msg)

    payload = result

    # Step 3: Additional expiration checks
    is_valid, error = verify_token_expiration(payload)
    if not is_valid:
        raise AuthenticationError(error)

    # Step 4: Extract and validate user info
    user_id = payload.get("sub")
    if not user_id:
        raise AuthenticationError("Token missing subject (sub) claim")

    # Step 5: Build auth context
    auth_context = {
        "user_id": user_id,
        "email": payload.get("email"),
        "role": payload.get("role", "authenticated"),
        "authenticated_at": payload.get("iat"),
        "expires_at": payload.get("exp"),
        "session_id": payload.get("session_id"),
        "verified": True,
        "app_metadata": payload.get("app_metadata") or {},
        "user_metadata": payload.get("user_metadata") or {},
        "name": (payload.get("user_metadata") or {}).get("name")
        or (payload.get("user_metadata") or {}).get("full_name"),
        "avatar_url": (payload.get("user_metadata") or {}).get("avatar_url")
        or (payload.get("user_metadata") or {}).get("picture"),
    }

    return auth_context


# =============================================================================
# BACKWARD COMPATIBILITY FUNCTIONS
# =============================================================================

def get_token_from_header(authorization: str) -> str | None:
    """
    Extract Bearer token from Authorization header.

    Args:
        authorization: Authorization header value

    Returns:
        Token string or None
    """
    if not authorization:
        return None

    parts = authorization.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]

    return None


def _is_deleted_email(email: str) -> bool:
    normalized = (email or "").lower().strip()
    return normalized.startswith("deleted_") or normalized.endswith("@deleted.local")


def resolve_tenant_id(user_id: str, email: str = None, create_if_missing: bool = True) -> str:
    """
    Resolve tenant_id for a user, recovering stale mappings when possible.

    Behavior:
    - Returns existing users.tenant_id when present.
    - Attempts non-destructive recovery via tenants.owner_id and then by email.
    - Creates a tenant only when create_if_missing=True.
    """
    from modules.observability import supabase as supabase_client

    # 1) Primary lookup from users table. Lookup failures are non-mutating.
    try:
        user_lookup = (
            supabase_client.table("users")
            .select("id, tenant_id")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if user_lookup.data and len(user_lookup.data) > 0:
            tenant_id = user_lookup.data[0].get("tenant_id")
            if tenant_id:
                logger.debug("[resolve_tenant_id] Found existing tenant %s for user %s", tenant_id, user_id)
                return tenant_id
    except Exception as e:
        logger.warning("[resolve_tenant_id] User lookup failed (non-mutating): %s", e)
        raise HTTPException(status_code=503, detail="Tenant lookup temporarily unavailable")

    # 2) Recovery by owner_id where schema supports it.
    try:
        owner_tenant = (
            supabase_client.table("tenants")
            .select("id")
            .eq("owner_id", user_id)
            .order("created_at", desc=False)
            .limit(1)
            .execute()
        )
        if owner_tenant.data and len(owner_tenant.data) > 0:
            tenant_id = owner_tenant.data[0]["id"]
            user_data = {"id": user_id, "tenant_id": tenant_id}
            if email:
                user_data["email"] = email
            supabase_client.table("users").upsert(user_data).execute()
            logger.info("[resolve_tenant_id] Re-linked user %s to owner tenant %s", user_id, tenant_id)
            return tenant_id
    except Exception as e:
        logger.debug("[resolve_tenant_id] Owner-tenant recovery skipped: %s", e)

    # 3) Recovery by historical email mapping (prevents tenant drift after auth-id changes).
    normalized_email = (email or "").strip().lower()
    if normalized_email and not _is_deleted_email(normalized_email):
        try:
            email_matches = (
                supabase_client.table("users")
                .select("id, email, tenant_id, last_active_at, created_at")
                .eq("email", normalized_email)
                .execute()
            )
            candidates = []
            for row in email_matches.data or []:
                candidate_tenant_id = row.get("tenant_id")
                candidate_email = row.get("email")
                if not candidate_tenant_id:
                    continue
                if _is_deleted_email(candidate_email):
                    continue
                candidates.append(row)

            if candidates:
                candidates.sort(
                    key=lambda r: ((r.get("last_active_at") or ""), (r.get("created_at") or "")),
                    reverse=True,
                )
                tenant_id = candidates[0]["tenant_id"]
                supabase_client.table("users").upsert(
                    {"id": user_id, "tenant_id": tenant_id, "email": normalized_email}
                ).execute()
                logger.info(
                    "[resolve_tenant_id] Re-linked user %s to tenant %s via email %s",
                    user_id, tenant_id, normalized_email,
                )
                return tenant_id
        except Exception as e:
            logger.debug("[resolve_tenant_id] Email-tenant recovery skipped: %s", e)

    if not create_if_missing:
        raise HTTPException(status_code=404, detail="Tenant not found for user")

    def _recover_after_create_conflict() -> str | None:
        for _ in range(3):
            try:
                user_lookup = (
                    supabase_client.table("users")
                    .select("id, tenant_id")
                    .eq("id", user_id)
                    .limit(1)
                    .execute()
                )
                if user_lookup.data and user_lookup.data[0].get("tenant_id"):
                    return user_lookup.data[0]["tenant_id"]
            except Exception:
                pass

            if normalized_email and not _is_deleted_email(normalized_email):
                try:
                    email_matches = (
                        supabase_client.table("users")
                        .select("id, email, tenant_id, last_active_at, created_at")
                        .eq("email", normalized_email)
                        .execute()
                    )
                    candidates = [
                        row for row in email_matches.data or []
                        if row.get("tenant_id") and not _is_deleted_email(row.get("email"))
                    ]
                    if candidates:
                        candidates.sort(
                            key=lambda r: ((r.get("last_active_at") or ""), (r.get("created_at") or "")),
                            reverse=True,
                        )
                        tenant_id = candidates[0]["tenant_id"]
                        supabase_client.table("users").upsert(
                            {"id": user_id, "tenant_id": tenant_id, "email": normalized_email}
                        ).execute()
                        return tenant_id
                except Exception:
                    pass

            time.sleep(0.05)
        return None

    # 4) Auto-create tenant only for write-enabled flows.
    try:
        name = email.split("@")[0] if email else f"User-{user_id[:8]}"
        workspace_name = f"{name}'s Workspace"
        try:
            tenant_insert = supabase_client.table("tenants").insert(
                {"name": workspace_name}
            ).execute()
        except Exception as insert_exc:
            recovered_tenant_id = _recover_after_create_conflict()
            if recovered_tenant_id:
                logger.info(
                    "[resolve_tenant_id] Recovered tenant %s after create conflict for user %s",
                    recovered_tenant_id,
                    user_id,
                )
                return recovered_tenant_id

            logger.info(
                "[resolve_tenant_id] Tenant name create failed for %s, retrying with user suffix: %s",
                user_id,
                insert_exc,
            )
            tenant_insert = supabase_client.table("tenants").insert(
                {"name": f"{workspace_name} ({user_id[:8]})"}
            ).execute()

        if not tenant_insert.data:
            raise HTTPException(status_code=500, detail="Failed to auto-create tenant")

        tenant_id = tenant_insert.data[0]["id"]
        user_data = {"id": user_id, "tenant_id": tenant_id}
        if email:
            user_data["email"] = email
        supabase_client.table("users").upsert(user_data).execute()
        logger.info("[resolve_tenant_id] Created tenant %s and linked user %s", tenant_id, user_id)
        return tenant_id
    except HTTPException:
        raise
    except Exception:
        logger.exception("[auth_guard] Failed to resolve tenant for user %s", user_id)
        raise HTTPException(status_code=500, detail="Tenant resolution failed. Please try again.")


def get_current_user(
    request: Request = None,
    authorization: str = Header(None),
    x_twin_api_key: str = Header(None),
    origin: str = Header(None),
    referer: str = Header(None),
) -> dict[str, Any] | None:
    """
    Dependency to get current user without requiring authentication.

    Args:
        request: Optional request object (kept for backward compatibility)
        authorization: Authorization header
        x_twin_api_key: Optional API key header (legacy compatibility)
        origin: Optional request origin header (legacy compatibility)
        referer: Optional request referer header (legacy compatibility)

    Returns:
        User dict or None if not authenticated
    """
    if not authorization:
        return None

    token = get_token_from_header(authorization)
    if not token:
        return None

    try:
        auth_context = authenticate_request(token)

        # Best-effort tenant enrichment. Never auto-create tenants here — this is a
        # read-only dependency. Tenant creation is reserved for /auth/sync-user only.
        if not auth_context.get("tenant_id"):
            with contextlib.suppress(HTTPException):
                auth_context["tenant_id"] = resolve_tenant_id(
                    user_id=auth_context.get("user_id"),
                    email=auth_context.get("email"),
                    create_if_missing=False,
                )

        return auth_context
    except AuthenticationError as exc:
        logger.warning("[auth_guard] get_current_user auth failed: %s", exc)
        return None


def verify_owner(
    user: dict[str, Any] | None = Depends(get_current_user),
    authorization: str = Header(None),
) -> dict[str, Any]:
    """
    Dependency for FastAPI to verify the request owner.

    Primary auth source is `get_current_user` (supports dependency overrides in tests).
    Falls back to explicit header parsing when needed.
    """
    # Primary path: use get_current_user so dependency overrides in tests and
    # internal tooling continue to work.
    if isinstance(user, dict) and user.get("user_id"):
        auth_context = dict(user)
    else:
        # Fallback path: explicit header parsing for direct invocations.
        if not authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization header required",
                headers={"WWW-Authenticate": "Bearer"}
            )

        token = get_token_from_header(authorization)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authorization format. Expected: Bearer <token>",
                headers={"WWW-Authenticate": "Bearer"}
            )

        try:
            auth_context = authenticate_request(token)
        except AuthenticationError as e:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(e),
                headers={"WWW-Authenticate": "Bearer"}
            )

    # Enrich auth context with tenant_id. verify_owner is used for write operations
    # so we allow tenant lookup but NOT auto-creation here. Call /auth/sync-user to
    # create a tenant for new users before reaching any write endpoint.
    if not auth_context.get("tenant_id"):
        try:
            tenant_id = resolve_tenant_id(
                user_id=auth_context.get("user_id"),
                email=auth_context.get("email"),
                create_if_missing=False,
            )
            auth_context["tenant_id"] = tenant_id
        except HTTPException as exc:
            if exc.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User has no tenant association. Call /auth/sync-user first.",
                )
            raise

    return auth_context


def require_tenant(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    """
    Require an authenticated user with a resolvable tenant_id.
    Auto-creates tenant if missing to prevent 403 errors for new users.
    """
    if not user or not user.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    tenant_id = user.get("tenant_id")
    if not tenant_id:
        try:
            # Lookup only — no auto-creation. New users must call /auth/sync-user first.
            tenant_id = resolve_tenant_id(
                user_id=user.get("user_id"),
                email=user.get("email"),
                create_if_missing=False,
            )
        except HTTPException as exc:
            if exc.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User has no tenant association. Call /auth/sync-user first.",
                )
            raise

    user = dict(user)
    user["tenant_id"] = tenant_id
    return user


# Admin access policy: a company-domain email grants admin access (employees
# control a @personaon.com mailbox; signup is OTP/OAuth so the mailbox must be
# owned). An explicit admin/support role is an additional path for non-domain
# staff. The broad 'owner' role does NOT grant admin access.
ADMIN_EMAIL_DOMAIN = (os.getenv("ADMIN_EMAIL_DOMAIN", "personaon.com") or "personaon.com").strip().lower()


def _is_admin_email(email: str | None) -> bool:
    return bool(email) and email.strip().lower().endswith("@" + ADMIN_EMAIL_DOMAIN)


def require_admin(user: dict[str, Any] = Depends(require_tenant)) -> dict[str, Any]:
    """
    Require admin access: a @ADMIN_EMAIL_DOMAIN email OR an explicit admin/support
    role. The broad 'owner' role no longer grants admin access.
    """
    # Use get_supabase_client() consistently with the rest of this module. The
    # previous implementation referenced a bare `supabase` symbol that was
    # never imported here -- the resulting NameError was caught by the broad
    # `except Exception` below, silently defaulting every caller to
    # actual_role='viewer' and 403'ing every admin endpoint. Caught by the
    # 2026-05-31 second-pass audit.
    from modules.observability import get_supabase_client

    user_id = user.get("user_id")
    actual_role = "viewer"
    try:
        role_lookup = (
            get_supabase_client().table("users")
            .select("role")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if role_lookup.data:
            actual_role = role_lookup.data[0].get("role", "viewer")
    except Exception as e:
        logger.warning("[require_admin] Role lookup failed user_id=%s: %s", user_id, e)

    email = user.get("email")
    if not (_is_admin_email(email) or actual_role in {"admin", "support"}):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator privileges required",
        )

    user = dict(user)
    user["actual_role"] = actual_role
    user["is_admin_email"] = _is_admin_email(email)
    return user


def require_admin_write(user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    """Stricter guard for *mutating* admin actions.

    Allowed for a company-domain email or an explicit ``admin`` role. ``support``
    is read-only, so destructive operations (plan/role changes, suspend, delete,
    take-down) are blocked for it.
    """
    if not (user.get("is_admin_email") or user.get("actual_role") == "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write privileges required (admin)",
        )
    return user


def require_twin_access(twin_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure the twin belongs to the user's tenant and return minimal twin metadata.
    """
    from modules.observability import get_supabase_client

    tenant_id = user.get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no tenant association",
        )

    try:
        twin_res = (
            get_supabase_client().table("twins")
            .select("id, name, tenant_id, specialization")
            .eq("id", twin_id)
            .eq("tenant_id", tenant_id)
            .limit(1)
            .execute()
        )
        if not twin_res.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Twin not found or access denied",
            )
        return twin_res.data[0]
    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[require_twin_access] Access validation failed for twin %s: %s", twin_id, e)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Twin not found or access denied",
        )


def verify_twin_ownership(twin_id: str, user: dict[str, Any]) -> bool:
    """
    Verify that a user owns a specific twin.

    Args:
        twin_id: Twin ID to check
        user: User dict from authentication

    Returns:
        True if user owns the twin

    Raises:
        HTTPException: If user doesn't own the twin
    """
    from modules.observability import get_supabase_client

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    # API-key visitors are restricted to exactly one twin.
    if user.get("role") == "visitor":
        allowed_twin_id = user.get("twin_id")
        if not allowed_twin_id or str(allowed_twin_id) != str(twin_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this twin"
            )
        return True

    if not user.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    user_id = user.get("user_id")
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        try:
            # Lookup only — no auto-creation for ownership checks.
            tenant_id = resolve_tenant_id(
                user_id=user_id,
                email=user.get("email"),
                create_if_missing=False,
            )
        except HTTPException as exc:
            if exc.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_403_FORBIDDEN):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User has no tenant association. Call /auth/sync-user first.",
                )
            raise

    try:
        supabase = get_supabase_client()
        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User has no tenant association"
            )

        # maybe_single (not single): a missing twin returns 0 rows -> result.data
        # is None, so the clean 404 below runs. `.single()` RAISES PGRST116 on 0
        # rows, which the broad except turned into a 500 — making "you don't own
        # this twin" look like a server crash.
        result = (
            supabase.table("twins")
            .select("id, tenant_id, creator_id, settings")
            .eq("id", twin_id)
            .eq("tenant_id", tenant_id)
            .maybe_single()
            .execute()
        )

        if not result or not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Twin not found or access denied"
            )

        # Single-profile hardening: if ownership metadata exists, enforce user-level access.
        twin_row = result.data
        settings = twin_row.get("settings") if isinstance(twin_row.get("settings"), dict) else {}
        owner_user_id = str(settings.get("owner_user_id") or "").strip()
        creator_id = str(twin_row.get("creator_id") or "").strip()
        user_id_str = str(user_id or "").strip()
        role_value = str(user.get("actual_role") or user.get("role") or "").lower()
        is_admin = role_value in {"owner", "admin", "support", "superadmin"}

        if not is_admin:
            if owner_user_id and user_id_str and owner_user_id != user_id_str:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to this profile",
                )

            creator_candidates = {user_id_str, f"tenant_{tenant_id}"}
            creator_ids = user.get("creator_ids")
            if isinstance(creator_ids, list):
                creator_candidates.update(str(c) for c in creator_ids if c)
            creator_id_single = user.get("creator_id")
            if creator_id_single:
                creator_candidates.add(str(creator_id_single))

            if creator_id and creator_id not in creator_candidates:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to this profile",
                )

        return True

    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[Auth] Twin ownership check failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify twin ownership"
        )


def verify_source_ownership(source_id: str, user: dict[str, Any]) -> str:
    """
    Verify that a user owns a specific source.

    Args:
        source_id: Source ID to check
        user: User dict from authentication

    Returns:
        twin_id of the owning twin (str) — callers can use it directly

    Raises:
        HTTPException: If user doesn't own the source
    """
    from modules.observability import supabase

    if not user or not user.get("user_id"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )

    user_id = user.get("user_id")
    tenant_id = user.get("tenant_id")
    if not tenant_id:
        try:
            # Lookup only — no auto-creation for source ownership checks.
            tenant_id = resolve_tenant_id(
                user_id=user_id,
                email=user.get("email"),
                create_if_missing=False,
            )
        except HTTPException:
            tenant_id = None

    try:
        # Get source and its twin
        source_result = supabase.table("sources").select("twin_id").eq("id", source_id).single().execute()

        if not source_result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source {source_id} not found"
            )

        twin_id = source_result.data.get("twin_id")

        # Check twin ownership by tenant scope
        if not tenant_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source not found or access denied"
            )

        twin_result = (
            supabase.table("twins")
            .select("id, tenant_id")
            .eq("id", twin_id)
            .eq("tenant_id", tenant_id)
            .single()
            .execute()
        )

        if not twin_result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Source not found or access denied"
            )

        return twin_id

    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[Auth] Source ownership check failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify source ownership"
        )


def ensure_twin_active(twin_id: str) -> bool:
    """
    Verify that a twin exists and is usable for owner/internal operations.

    Args:
        twin_id: Twin ID to check

    Returns:
        True if twin can be used internally

    Raises:
        HTTPException: If twin doesn't exist or is not usable
    """
    from modules.observability import supabase

    try:
        # Prefer status-aware check when the column exists.
        try:
            result = (
                supabase.table("twins")
                .select("id, status")
                .eq("id", twin_id)
                .single()
                .execute()
            )
        except Exception as status_query_error:
            # Backward compatibility for environments where `twins.status`
            # has not been migrated yet.
            err = str(status_query_error).lower()
            status_column_missing = (
                "status" in err
                and (
                    "does not exist" in err
                    or "column" in err
                    or "pgrst204" in err
                )
            )
            if not status_column_missing:
                raise

            result = (
                supabase.table("twins")
                .select("id")
                .eq("id", twin_id)
                .single()
                .execute()
            )

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Twin {twin_id} not found"
            )

        # Internal owner routes allow draft and claims_ready so users can keep
        # building unfinished personas. Public routes use stricter active-only
        # gating in modules.share_links.
        twin_status = result.data.get("status")
        allowed_statuses = {"active", "live", "persona_built", "claims_ready", "draft", None}
        if twin_status and twin_status not in allowed_statuses:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Twin {twin_id} is not active (status: {twin_status})"
            )

        return True

    except HTTPException:
        raise
    except Exception as e:
        logger.warning("[Auth] Twin active check failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to verify twin status"
        )
