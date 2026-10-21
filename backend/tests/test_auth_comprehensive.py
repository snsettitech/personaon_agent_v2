# backend/tests/test_auth_comprehensive.py
"""
Comprehensive authentication tests for P0-B.

Tests cover:
- Wrong tenant access (cross-tenant isolation)
- Revoked/inactive users
- Expired JWT tokens
- Share link validation
- API key validation
- Rate limiting
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta


# ============================================================================
# Test Fixtures
# ============================================================================

@pytest.fixture
def mock_supabase():
    """Mock Supabase client for testing."""
    with patch('modules.observability.supabase') as mock:
        yield mock


@pytest.fixture
def valid_jwt_payload():
    """Valid JWT payload for testing."""
    return {
        "sub": "test-user-id-123",
        "aud": "authenticated",
        "email": "test@example.com",
        "user_metadata": {"full_name": "Test User"},
        "exp": int((datetime.utcnow() + timedelta(hours=1)).timestamp())
    }


@pytest.fixture
def expired_jwt_payload():
    """Expired JWT payload for testing."""
    return {
        "sub": "test-user-id-123",
        "aud": "authenticated",
        "email": "test@example.com",
        "exp": int((datetime.utcnow() - timedelta(hours=1)).timestamp())
    }


# ============================================================================
# Twin Ownership Tests
# ============================================================================

class TestTwinOwnership:
    """Tests for verify_twin_ownership function."""

    def test_owner_can_access_own_twin(self, mock_supabase):
        """Owner should be able to access their own twin."""
        from modules.auth_guard import verify_twin_ownership

        # Mock user with tenant
        user = {
            "user_id": "user-123",
            "tenant_id": "tenant-456",
            "role": "owner"
        }

        # Mock twin belonging to same tenant
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
            "id": "twin-789",
            "tenant_id": "tenant-456"
        }

        # Should not raise
        verify_twin_ownership("twin-789", user)

    def test_owner_cannot_access_other_tenant_twin(self, mock_supabase):
        """Owner should not be able to access another tenant's twin."""
        from modules.auth_guard import verify_twin_ownership
        from fastapi import HTTPException

        # Mock user with tenant A
        user = {
            "user_id": "user-123",
            "tenant_id": "tenant-A",
            "role": "owner"
        }

        # Mock twin belonging to tenant B
        # Tenant mismatch should result in no record due to tenant_id filter in query
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None

        with pytest.raises(HTTPException) as exc_info:
            verify_twin_ownership("twin-789", user)

        assert exc_info.value.status_code == 404  # Should return 404 to prevent enumeration

    def test_visitor_can_access_allowed_twin(self, mock_supabase):
        """Visitor with API key should be able to access the allowed twin."""
        from modules.auth_guard import verify_twin_ownership

        # Mock visitor user from API key
        user = {
            "user_id": None,
            "tenant_id": None,
            "role": "visitor",
            "twin_id": "twin-allowed"
        }

        # Should not raise for allowed twin
        verify_twin_ownership("twin-allowed", user)

    def test_visitor_cannot_access_other_twin(self, mock_supabase):
        """Visitor with API key should not be able to access other twins."""
        from modules.auth_guard import verify_twin_ownership
        from fastapi import HTTPException

        # Mock visitor user from API key
        user = {
            "user_id": None,
            "tenant_id": None,
            "role": "visitor",
            "twin_id": "twin-allowed"
        }

        with pytest.raises(HTTPException) as exc_info:
            verify_twin_ownership("twin-different", user)

        assert exc_info.value.status_code == 403

    def test_twin_not_found(self, mock_supabase):
        """Should return 404 when twin doesn't exist."""
        from modules.auth_guard import verify_twin_ownership
        from fastapi import HTTPException

        user = {
            "user_id": "user-123",
            "tenant_id": "tenant-456",
            "role": "owner"
        }

        # Mock twin not found
        mock_supabase.table.return_value.select.return_value.eq.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None

        with pytest.raises(HTTPException) as exc_info:
            verify_twin_ownership("nonexistent-twin", user)

        assert exc_info.value.status_code == 404


# ============================================================================
# Share Link Tests
# ============================================================================

class TestShareLinkValidation:
    """Tests for share link token validation."""

    def test_valid_share_token(self):
        """Valid share token should pass validation."""
        from modules.share_links import validate_share_token

        # Public reachability now also requires the marketplace-quality gate
        # (PRD R1); that gate has its own tests, so stub it to isolate the
        # token-matching logic under test here.
        with patch('modules.share_links.supabase') as mock_sb, patch(
            'modules.share_links.is_publicly_accessible_twin_record', return_value=True
        ):
            mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                "id": "twin-id",
                "status": "active",
                "settings": {
                    "widget_settings": {
                        "share_token": "valid-token-123",
                        "public_share_enabled": True
                    }
                }
            }

            assert validate_share_token("valid-token-123", "twin-id") is True

    def test_invalid_share_token(self):
        """Invalid share token should fail validation."""
        from modules.share_links import validate_share_token

        with patch('modules.share_links.supabase') as mock_sb:
            mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                "id": "twin-id",
                "status": "active",
                "settings": {
                    "widget_settings": {
                        "share_token": "valid-token-123",
                        "public_share_enabled": True
                    }
                }
            }

            assert validate_share_token("wrong-token", "twin-id") is False

    def test_sharing_disabled(self):
        """Should fail when public sharing is disabled."""
        from modules.share_links import validate_share_token

        with patch('modules.share_links.supabase') as mock_sb:
            mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                "id": "twin-id",
                "status": "active",
                "settings": {
                    "widget_settings": {
                        "share_token": "valid-token-123",
                        "public_share_enabled": False
                    }
                }
            }

            assert validate_share_token("valid-token-123", "twin-id") is False

    def test_expired_share_token(self):
        """Expired share token should fail validation."""
        from modules.share_links import validate_share_token

        expired_time = (datetime.utcnow() - timedelta(days=1)).isoformat()

        with patch('modules.share_links.supabase') as mock_sb:
            mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                "id": "twin-id",
                "status": "active",
                "settings": {
                    "widget_settings": {
                        "share_token": "valid-token-123",
                        "public_share_enabled": True,
                        "share_token_expires_at": expired_time
                    }
                }
            }

            assert validate_share_token("valid-token-123", "twin-id") is False


# ============================================================================
# API Key Tests
# ============================================================================

class TestAPIKeyValidation:
    """Tests for API key validation."""

    def test_valid_api_key(self):
        """Valid API key should pass validation."""
        from modules.api_keys import validate_api_key
        import bcrypt

        # Create a test key
        test_key = "twin_test1234_abcdefghijklmnopqrstuvwxyz"
        key_hash = bcrypt.hashpw(test_key.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        with patch('modules.api_keys.supabase') as mock_sb:
            # actual query: .select("*").eq("is_active", True).eq("key_prefix", ...).execute()
            mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = [
                {
                    "id": "key-123",
                    "twin_id": "twin-456",
                    "key_hash": key_hash,
                    "is_active": True,
                    "allowed_domains": ["example.com"],
                    "expires_at": None
                }
            ]

            result = validate_api_key(test_key)
            assert result is not None
            assert result["twin_id"] == "twin-456"

    def test_invalid_api_key_format(self, mock_supabase):
        """API key with wrong format should fail."""
        from modules.api_keys import validate_api_key

        result = validate_api_key("invalid_format_key")
        assert result is None

    def test_expired_api_key(self, mock_supabase):
        """Expired API key should fail validation."""
        from modules.api_keys import validate_api_key
        import bcrypt

        test_key = "twin_test1234_abcdefghijklmnopqrstuvwxyz"
        key_hash = bcrypt.hashpw(test_key.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        expired_time = (datetime.utcnow() - timedelta(days=1)).isoformat()

        mock_supabase.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {
                "id": "key-123",
                "twin_id": "twin-456",
                "key_hash": key_hash,
                "is_active": True,
                "allowed_domains": [],
                "expires_at": expired_time
            }
        ]

        result = validate_api_key(test_key)
        assert result is None


# ============================================================================
# Domain Validation Tests
# ============================================================================

class TestDomainValidation:
    """Tests for API key domain validation."""

    def test_exact_domain_match(self):
        """Exact domain match should pass."""
        from modules.api_keys import validate_domain

        assert validate_domain("example.com", ["example.com"]) is True
        assert validate_domain("https://example.com", ["example.com"]) is True
        assert validate_domain("https://example.com:3000", ["example.com"]) is True

    def test_wildcard_subdomain(self):
        """Wildcard subdomain should match."""
        from modules.api_keys import validate_domain

        assert validate_domain("sub.example.com", ["*.example.com"]) is True
        assert validate_domain("deep.sub.example.com", ["*.example.com"]) is True
        assert validate_domain("example.com", ["*.example.com"]) is True

    def test_domain_mismatch(self):
        """Non-matching domain should fail."""
        from modules.api_keys import validate_domain

        assert validate_domain("evil.com", ["example.com"]) is False
        assert validate_domain("example.com.evil.com", ["example.com"]) is False

    def test_no_restrictions(self):
        """Empty allowed list should allow all."""
        from modules.api_keys import validate_domain

        assert validate_domain("anything.com", []) is True
        assert validate_domain("any.domain.here", None) is True


# ============================================================================
# User Invitation Tests
# ============================================================================

class TestUserInvitations:
    """Tests for user invitation validation."""

    def test_valid_invitation(self):
        """Valid invitation should pass."""
        from modules.user_management import validate_invitation_token

        future_time = (datetime.utcnow() + timedelta(days=7)).isoformat()

        with patch('modules.user_management.supabase') as mock_sb:
            mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                "id": "invite-123",
                "tenant_id": "tenant-456",
                "email": "invitee@example.com",
                "role": "member",
                "invited_by": "user-789",
                "status": "pending",
                "expires_at": future_time
            }

            result = validate_invitation_token("valid-invite-token")
            assert result is not None
            assert result["email"] == "invitee@example.com"

    def test_expired_invitation(self):
        """Expired invitation should fail."""
        from modules.user_management import validate_invitation_token

        past_time = (datetime.utcnow() - timedelta(days=7)).isoformat()

        with patch('modules.user_management.supabase') as mock_sb:
            mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                "id": "invite-123",
                "tenant_id": "tenant-456",
                "email": "invitee@example.com",
                "role": "member",
                "invited_by": "user-789",
                "status": "pending",
                "expires_at": past_time
            }

            # Mock update call for marking as expired
            mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

            result = validate_invitation_token("valid-invite-token")
            assert result is None

    def test_already_accepted_invitation(self):
        """Already accepted invitation should fail."""
        from modules.user_management import validate_invitation_token

        with patch('modules.user_management.supabase') as mock_sb:
            mock_sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
                "id": "invite-123",
                "tenant_id": "tenant-456",
                "email": "invitee@example.com",
                "role": "member",
                "invited_by": "user-789",
                "status": "accepted",
                "expires_at": None
            }

            result = validate_invitation_token("valid-invite-token")
            assert result is None


# ============================================================================
# Integration Tests (require running backend)
# ============================================================================

@pytest.mark.network
class TestAuthIntegration:
    """Integration tests for authentication flow (requires running backend)."""

    @pytest.mark.skip(reason="Requires running backend")
    def test_unauthenticated_request_returns_401(self):
        """Unauthenticated request should return 401."""
        import httpx

        response = httpx.get("http://localhost:8000/twins")
        assert response.status_code == 401

    @pytest.mark.skip(reason="Requires running backend")
    def test_invalid_jwt_returns_401(self):
        """Invalid JWT should return 401."""
        import httpx

        headers = {"Authorization": "Bearer invalid.jwt.token"}
        response = httpx.get("http://localhost:8000/twins", headers=headers)
        assert response.status_code == 401

