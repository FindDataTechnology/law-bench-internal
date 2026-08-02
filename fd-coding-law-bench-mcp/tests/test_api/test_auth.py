"""Tests for authentication middleware."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


@pytest.fixture
def client():
    """Create test client."""
    from fd_coding_law_bench_mcp.api.main import app
    return TestClient(app)


class TestAPIKeyAuthentication:
    """Tests for API key authentication middleware."""

    def test_auth_disabled_health_accessible(self, client):
        """Test health endpoint accessible when auth disabled (default)."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_auth_disabled_docs_accessible(self, client):
        """Test docs endpoint accessible when auth disabled."""
        response = client.get("/docs")
        assert response.status_code == 200

    @patch("fd_coding_law_bench_mcp.api.middleware.get_settings")
    def test_auth_enabled_missing_key(self, mock_settings, client):
        """Test 401 when auth enabled but no API key provided."""
        mock_settings_obj = mock_settings.return_value
        mock_settings_obj.api_key_enabled = True
        mock_settings_obj.api_keys = ["valid-key"]
        mock_settings_obj.public_endpoints = ["/health", "/docs", "/redoc"]

        # Health endpoint should still be accessible
        response = client.get("/health")
        assert response.status_code == 200

        # Contract endpoint should require auth
        response = client.post(
            "/contracts/content",
            json={"contract_type": "sale"},
        )
        assert response.status_code == 401

    @patch("fd_coding_law_bench_mcp.api.middleware.get_settings")
    def test_auth_enabled_invalid_key(self, mock_settings, client):
        """Test 403 when auth enabled with invalid API key."""
        mock_settings_obj = mock_settings.return_value
        mock_settings_obj.api_key_enabled = True
        mock_settings_obj.api_keys = ["valid-key"]
        mock_settings_obj.public_endpoints = ["/health", "/docs", "/redoc"]

        response = client.post(
            "/contracts/content",
            json={"contract_type": "sale"},
            headers={"X-API-Key": "invalid-key"},
        )
        assert response.status_code == 403

    @patch("fd_coding_law_bench_mcp.api.middleware.get_settings")
    def test_auth_enabled_valid_key(self, mock_settings, client):
        """Test successful request with valid API key."""
        mock_settings_obj = mock_settings.return_value
        mock_settings_obj.api_key_enabled = True
        mock_settings_obj.api_keys = ["valid-key"]
        mock_settings_obj.public_endpoints = ["/health", "/docs", "/redoc"]

        # Mock the contract_content to return success
        from unittest.mock import AsyncMock
        mock_result = {
            "trace_id": "test",
            "contract_type": "sale",
            "format": "markdown",
            "body_text": "contract",
            "slots": [],
            "instructions": [],
            "law_refs": [],
            "tags_used": {},
        }
        with patch(
            "fd_coding_law_bench_mcp.api.routes.contracts.contract_content",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            response = client.post(
                "/contracts/content",
                json={"contract_type": "sale"},
                headers={"X-API-Key": "valid-key"},
            )
            assert response.status_code == 200

    @patch("fd_coding_law_bench_mcp.api.middleware.get_settings")
    def test_auth_enabled_public_endpoints_bypass(self, mock_settings, client):
        """Test public endpoints bypass authentication."""
        mock_settings_obj = mock_settings.return_value
        mock_settings_obj.api_key_enabled = True
        mock_settings_obj.api_keys = ["valid-key"]
        mock_settings_obj.public_endpoints = ["/health", "/docs", "/redoc"]

        # These should all work without API key
        assert client.get("/health").status_code == 200
        assert client.get("/docs").status_code == 200
