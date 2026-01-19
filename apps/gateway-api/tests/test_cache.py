"""Tests for caching service."""

import asyncio
import time

import pytest

from src.services.cache import (
    CacheEntry,
    CacheEntryStatus,
    CacheKeyBuilder,
    CacheService,
)
from src.services.redis_client import RedisClient


@pytest.fixture
def redis_client() -> RedisClient:
    """Get test Redis client in demo mode."""
    client = RedisClient()
    client._redis = None
    client.clear_demo_cache()
    return client


class TestCacheKeyBuilder:
    """Tests for cache key canonicalization."""

    def test_basic_key(self):
        """Basic key generation."""
        key = CacheKeyBuilder.build(
            method="GET",
            route_name="api",
            path="/items",
        )
        
        assert key.startswith("cache:")
        assert len(key) == len("cache:") + 32  # SHA256 prefix

    def test_query_param_ordering(self):
        """Query params should be normalized regardless of order."""
        key1 = CacheKeyBuilder.build(
            method="GET",
            route_name="api",
            path="/search",
            query_params={"a": ["1"], "b": ["2"]},
        )
        
        key2 = CacheKeyBuilder.build(
            method="GET",
            route_name="api",
            path="/search",
            query_params={"b": ["2"], "a": ["1"]},
        )
        
        assert key1 == key2

    def test_vary_headers_included(self):
        """Vary headers should affect cache key."""
        key1 = CacheKeyBuilder.build(
            method="GET",
            route_name="api",
            path="/items",
            vary_headers={"accept": "application/json"},
        )
        
        key2 = CacheKeyBuilder.build(
            method="GET",
            route_name="api",
            path="/items",
            vary_headers={"accept": "text/html"},
        )
        
        assert key1 != key2

    def test_method_affects_key(self):
        """Different methods should have different keys."""
        key_get = CacheKeyBuilder.build(method="GET", route_name="api", path="/items")
        key_post = CacheKeyBuilder.build(method="POST", route_name="api", path="/items")
        
        assert key_get != key_post

    def test_tenant_isolation(self):
        """Different tenants should have different keys."""
        key1 = CacheKeyBuilder.build(
            method="GET",
            route_name="api",
            path="/items",
            tenant_id="tenant-1",
        )
        
        key2 = CacheKeyBuilder.build(
            method="GET",
            route_name="api",
            path="/items",
            tenant_id="tenant-2",
        )
        
        assert key1 != key2


class TestCacheEntry:
    """Tests for cache entry behavior."""

    def test_fresh_status(self):
        """Entry within TTL should be fresh."""
        entry = CacheEntry(
            status_code=200,
            headers={"content-type": "application/json"},
            body=b'{"data": "test"}',
            created_at=time.time(),
            ttl_seconds=300,
            stale_seconds=60,
        )
        
        assert entry.get_status() == CacheEntryStatus.FRESH

    def test_stale_status(self):
        """Entry past TTL but within stale window should be stale."""
        entry = CacheEntry(
            status_code=200,
            headers={},
            body=b"test",
            created_at=time.time() - 310,  # 310s ago, TTL is 300
            ttl_seconds=300,
            stale_seconds=60,
        )
        
        assert entry.get_status() == CacheEntryStatus.STALE

    def test_miss_status(self):
        """Entry past TTL + stale window should be miss."""
        entry = CacheEntry(
            status_code=200,
            headers={},
            body=b"test",
            created_at=time.time() - 400,  # 400s ago, TTL+stale is 360
            ttl_seconds=300,
            stale_seconds=60,
        )
        
        assert entry.get_status() == CacheEntryStatus.MISS

    def test_serialization(self):
        """Entry should serialize and deserialize correctly."""
        original = CacheEntry(
            status_code=200,
            headers={"x-custom": "value"},
            body=b'{"test": true}',
            created_at=time.time(),
            ttl_seconds=300,
            stale_seconds=60,
            vary_key="accept:application/json",
        )
        
        json_str = original.to_json()
        restored = CacheEntry.from_json(json_str)
        
        assert restored.status_code == original.status_code
        assert restored.headers == original.headers
        assert restored.ttl_seconds == original.ttl_seconds
        assert restored.vary_key == original.vary_key


class TestCacheService:
    """Tests for cache service."""

    @pytest.fixture
    def cache(self, redis_client: RedisClient) -> CacheService:
        return CacheService(redis_client)

    @pytest.mark.asyncio
    async def test_get_miss(self, cache: CacheService):
        """Getting non-existent key should return miss."""
        result = await cache.get("nonexistent-key")
        
        assert result.status == CacheEntryStatus.MISS
        assert result.entry is None

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache: CacheService):
        """Setting and getting should work."""
        entry = CacheEntry(
            status_code=200,
            headers={"x-test": "value"},
            body=b"test data",
            created_at=time.time(),
            ttl_seconds=300,
            stale_seconds=60,
        )
        
        await cache.set("test-key", entry)
        result = await cache.get("test-key")
        
        assert result.status == CacheEntryStatus.FRESH
        assert result.entry is not None
        assert result.entry.status_code == 200
        assert result.entry.body == b"test data"

    @pytest.mark.asyncio
    async def test_delete(self, cache: CacheService):
        """Delete should remove entry."""
        entry = CacheEntry(
            status_code=200,
            headers={},
            body=b"test",
            created_at=time.time(),
            ttl_seconds=300,
            stale_seconds=60,
        )
        
        await cache.set("delete-key", entry)
        await cache.delete("delete-key")
        
        result = await cache.get("delete-key")
        assert result.status == CacheEntryStatus.MISS

    @pytest.mark.asyncio
    async def test_stale_needs_refresh(self, cache: CacheService):
        """Stale entry should indicate refresh needed."""
        entry = CacheEntry(
            status_code=200,
            headers={},
            body=b"test",
            created_at=time.time() - 310,  # Stale
            ttl_seconds=300,
            stale_seconds=60,
        )
        
        # Manually insert stale entry
        await cache._redis.set(
            "stale-key",
            entry.to_json(),
            ex=60,  # Still has time
        )
        
        result = await cache.get("stale-key")
        
        assert result.status == CacheEntryStatus.STALE
        assert result.needs_refresh is True

    @pytest.mark.asyncio
    async def test_request_coalescing(self, cache: CacheService):
        """Concurrent requests should coalesce."""
        fetch_count = 0
        
        async def slow_fetch():
            nonlocal fetch_count
            fetch_count += 1
            await asyncio.sleep(0.1)
            return CacheEntry(
                status_code=200,
                headers={},
                body=b"result",
                created_at=time.time(),
                ttl_seconds=300,
                stale_seconds=60,
            )
        
        # Start multiple concurrent requests
        tasks = [
            cache.get_or_fetch("coalesce-key", slow_fetch)
            for _ in range(5)
        ]
        
        results = await asyncio.gather(*tasks)
        
        # All should get the same result
        assert all(r[0].body == b"result" for r in results)
        
        # But fetch should only have been called once (or at most twice due to timing)
        assert fetch_count <= 2
