"""Integration tests for API endpoints."""

import pytest
from httpx import AsyncClient


class TestHealthEndpoints:
    """Tests for health and metrics endpoints."""

    @pytest.mark.asyncio
    async def test_health_check(self, client: AsyncClient):
        """Health endpoint should return status."""
        response = await client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data
        assert "components" in data

    @pytest.mark.asyncio
    async def test_metrics(self, client: AsyncClient):
        """Metrics endpoint should return counters."""
        response = await client.get("/metrics")
        
        assert response.status_code == 200
        data = response.json()
        assert "cache_hit_total" in data
        assert "cache_miss_total" in data

    @pytest.mark.asyncio
    async def test_prometheus_metrics(self, client: AsyncClient):
        """Prometheus metrics should return text format."""
        response = await client.get("/metrics/prometheus")
        
        assert response.status_code == 200
        assert "heliox_cache_hits_total" in response.text


class TestAdminEndpoints:
    """Tests for admin API endpoints."""

    @pytest.mark.asyncio
    async def test_create_tenant(self, client: AsyncClient, admin_headers: dict):
        """Should create a new tenant."""
        response = await client.post(
            "/admin/tenants",
            json={"name": "Test Tenant", "description": "A test tenant"},
            headers=admin_headers,
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Tenant"
        assert "id" in data

    @pytest.mark.asyncio
    async def test_list_tenants(self, client: AsyncClient, admin_headers: dict):
        """Should list all tenants."""
        response = await client.get("/admin/tenants", headers=admin_headers)
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_create_api_key(self, client: AsyncClient, admin_headers: dict):
        """Should create an API key for a tenant."""
        # First create a tenant
        tenant_response = await client.post(
            "/admin/tenants",
            json={"name": "Key Test Tenant"},
            headers=admin_headers,
        )
        tenant_id = tenant_response.json()["id"]
        
        # Create API key
        response = await client.post(
            "/admin/keys",
            json={"tenant_id": tenant_id, "name": "Test Key"},
            headers=admin_headers,
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Key"
        assert "key" in data  # Full key returned on creation
        assert data["key"].startswith("hx_")

    @pytest.mark.asyncio
    async def test_create_route(self, client: AsyncClient, admin_headers: dict):
        """Should create a new route."""
        response = await client.post(
            "/admin/routes",
            json={
                "name": "test-route",
                "path_pattern": "/*",
                "upstream_base_url": "http://example.com",
                "methods": ["GET", "POST"],
            },
            headers=admin_headers,
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-route"
        assert "GET" in data["methods"]

    @pytest.mark.asyncio
    async def test_create_cache_policy(self, client: AsyncClient, admin_headers: dict):
        """Should create a cache policy."""
        response = await client.post(
            "/admin/policies",
            json={
                "name": "test-policy",
                "ttl_seconds": 600,
                "stale_seconds": 120,
            },
            headers=admin_headers,
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "test-policy"
        assert data["ttl_seconds"] == 600

    @pytest.mark.asyncio
    async def test_admin_requires_auth(self, client: AsyncClient):
        """Admin endpoints should require authentication."""
        response = await client.get("/admin/tenants")
        
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_analytics_summary(self, client: AsyncClient, admin_headers: dict):
        """Should return analytics summary."""
        response = await client.get(
            "/admin/analytics/summary",
            params={"hours": 24},
            headers=admin_headers,
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "total_requests" in data
        assert "cache_hit_rate" in data


class TestGatewayEndpoints:
    """Tests for gateway proxy endpoints."""

    @pytest.mark.asyncio
    async def test_gateway_requires_api_key(self, client: AsyncClient):
        """Gateway should require API key."""
        response = await client.get("/g/test-route/path")
        
        assert response.status_code == 401
        data = response.json()
        assert data["error"] == "missing_api_key"

    @pytest.mark.asyncio
    async def test_gateway_invalid_api_key(self, client: AsyncClient):
        """Gateway should reject invalid API keys."""
        response = await client.get(
            "/g/test-route/path",
            headers={"X-API-Key": "invalid-key"},
        )
        
        assert response.status_code == 401
        data = response.json()
        assert data["error"] == "invalid_api_key"

    @pytest.mark.asyncio
    async def test_gateway_route_not_found(self, client: AsyncClient, admin_headers: dict):
        """Gateway should return 404 for unknown routes."""
        # First create a valid API key
        tenant_response = await client.post(
            "/admin/tenants",
            json={"name": "Gateway Test Tenant"},
            headers=admin_headers,
        )
        tenant_id = tenant_response.json()["id"]
        
        key_response = await client.post(
            "/admin/keys",
            json={"tenant_id": tenant_id, "name": "Gateway Test Key"},
            headers=admin_headers,
        )
        api_key = key_response.json()["key"]
        
        # Try to access non-existent route
        response = await client.get(
            "/g/nonexistent-route/path",
            headers={"X-API-Key": api_key},
        )
        
        assert response.status_code == 404
        data = response.json()
        assert data["error"] == "route_not_found"
