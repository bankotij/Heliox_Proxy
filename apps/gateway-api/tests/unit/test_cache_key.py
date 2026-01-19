"""Unit tests for cache key canonicalization."""

import pytest

from src.services.cache import CacheKeyBuilder


class TestCacheKeyBuilder:
    """Tests for cache key builder."""

    @pytest.fixture
    def builder(self):
        """Create cache key builder instance."""
        return CacheKeyBuilder()

    def test_basic_key_generation(self, builder):
        """Should generate consistent cache keys."""
        key1 = builder.build(
            tenant_id="tenant_123",
            route_name="products",
            method="GET",
            path="/api/items",
            query_params={},
            vary_headers={},
        )
        key2 = builder.build(
            tenant_id="tenant_123",
            route_name="products",
            method="GET",
            path="/api/items",
            query_params={},
            vary_headers={},
        )
        assert key1 == key2

    def test_different_tenants_different_keys(self, builder):
        """Different tenants should produce different keys."""
        key1 = builder.build(
            tenant_id="tenant_abc",
            route_name="products",
            method="GET",
            path="/items",
            query_params={},
            vary_headers={},
        )
        key2 = builder.build(
            tenant_id="tenant_xyz",
            route_name="products",
            method="GET",
            path="/items",
            query_params={},
            vary_headers={},
        )
        assert key1 != key2

    def test_query_param_normalization(self, builder):
        """Query params should be sorted for consistency."""
        key1 = builder.build(
            tenant_id="tenant_123",
            route_name="search",
            method="GET",
            path="/search",
            query_params={"z": "3", "a": "1", "m": "2"},
            vary_headers={},
        )
        key2 = builder.build(
            tenant_id="tenant_123",
            route_name="search",
            method="GET",
            path="/search",
            query_params={"a": "1", "m": "2", "z": "3"},
            vary_headers={},
        )
        assert key1 == key2

    def test_vary_headers_included(self, builder):
        """Vary headers should affect cache key."""
        key1 = builder.build(
            tenant_id="tenant_123",
            route_name="products",
            method="GET",
            path="/items",
            query_params={},
            vary_headers={"accept": "application/json"},
        )
        key2 = builder.build(
            tenant_id="tenant_123",
            route_name="products",
            method="GET",
            path="/items",
            query_params={},
            vary_headers={"accept": "text/html"},
        )
        assert key1 != key2

    def test_vary_header_case_insensitive(self, builder):
        """Vary header names should be case-insensitive."""
        key1 = builder.build(
            tenant_id="tenant_123",
            route_name="products",
            method="GET",
            path="/items",
            query_params={},
            vary_headers={"Accept": "application/json"},
        )
        key2 = builder.build(
            tenant_id="tenant_123",
            route_name="products",
            method="GET",
            path="/items",
            query_params={},
            vary_headers={"accept": "application/json"},
        )
        assert key1 == key2

    def test_method_affects_key(self, builder):
        """HTTP method should affect cache key."""
        key_get = builder.build(
            tenant_id="tenant_123",
            route_name="resource",
            method="GET",
            path="/resource",
            query_params={},
            vary_headers={},
        )
        key_post = builder.build(
            tenant_id="tenant_123",
            route_name="resource",
            method="POST",
            path="/resource",
            query_params={},
            vary_headers={},
        )
        assert key_get != key_post

    def test_path_normalization(self, builder):
        """Paths should be normalized."""
        key1 = builder.build(
            tenant_id="tenant_123",
            route_name="api",
            method="GET",
            path="/api/items/",
            query_params={},
            vary_headers={},
        )
        key2 = builder.build(
            tenant_id="tenant_123",
            route_name="api",
            method="GET",
            path="/api/items",
            query_params={},
            vary_headers={},
        )
        # Trailing slash should be normalized
        assert key1 == key2

    def test_empty_query_params_handled(self, builder):
        """Empty query params should be handled gracefully."""
        key = builder.build(
            tenant_id="tenant_123",
            route_name="products",
            method="GET",
            path="/items",
            query_params=None,
            vary_headers=None,
        )
        assert key is not None
        assert len(key) > 0

    def test_special_characters_in_path(self, builder):
        """Special characters in path should be handled."""
        key = builder.build(
            tenant_id="tenant_123",
            route_name="products",
            method="GET",
            path="/items/special%20chars/test",
            query_params={"filter": "a=b&c=d"},
            vary_headers={},
        )
        assert key is not None
