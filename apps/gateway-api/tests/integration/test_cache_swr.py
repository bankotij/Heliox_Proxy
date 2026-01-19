"""Integration tests for SWR (stale-while-revalidate) caching."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.cache import CacheEntry, CacheResult, CacheService, CacheStatus


class TestStaleWhileRevalidate:
    """Tests for SWR cache behavior."""

    @pytest.fixture
    def cache_service(self):
        """Create cache service instance."""
        return CacheService()

    @pytest.mark.asyncio
    async def test_fresh_cache_hit(self, cache_service):
        """Fresh cache entries should be served immediately."""
        cache_key = "swr:fresh_hit"
        
        # Store fresh entry
        entry = CacheEntry(
            data=b'{"product": "Widget Pro", "price": 29.99}',
            content_type="application/json",
            status_code=200,
            headers={"X-Cache": "HIT"},
            created_at=time.time(),
            ttl=300,
            stale_ttl=600,
        )
        await cache_service.set(cache_key, entry)
        
        # Retrieve
        result = await cache_service.get(cache_key)
        
        assert result is not None
        assert result.status == CacheStatus.HIT
        assert result.entry.data == entry.data

    @pytest.mark.asyncio
    async def test_stale_entry_served_with_revalidation(self, cache_service):
        """Stale entries should be served while triggering background refresh."""
        cache_key = "swr:stale_entry"
        
        # Store entry that's past TTL but within stale TTL
        entry = CacheEntry(
            data=b'{"status": "stale data"}',
            content_type="application/json",
            status_code=200,
            headers={},
            created_at=time.time() - 400,  # 400 seconds ago
            ttl=300,  # TTL was 300 seconds
            stale_ttl=600,  # Stale until 600 seconds
        )
        await cache_service.set(cache_key, entry, force_stale=True)
        
        # Get should return stale entry
        result = await cache_service.get(cache_key)
        
        assert result is not None
        assert result.status == CacheStatus.STALE
        assert result.needs_revalidation is True

    @pytest.mark.asyncio
    async def test_expired_entry_returns_miss(self, cache_service):
        """Entries past stale TTL should return cache miss."""
        cache_key = "swr:expired_entry"
        
        # Store completely expired entry
        entry = CacheEntry(
            data=b'{"status": "expired"}',
            content_type="application/json",
            status_code=200,
            headers={},
            created_at=time.time() - 700,  # 700 seconds ago
            ttl=300,
            stale_ttl=600,  # Expired 100 seconds ago
        )
        await cache_service.set(cache_key, entry, force_expired=True)
        
        # Get should return miss
        result = await cache_service.get(cache_key)
        
        assert result is None or result.status == CacheStatus.MISS

    @pytest.mark.asyncio
    async def test_swr_refresh_updates_cache(self, cache_service):
        """Background refresh should update the cache entry."""
        cache_key = "swr:refresh_test"
        
        # Initial entry
        old_entry = CacheEntry(
            data=b'{"version": 1}',
            content_type="application/json",
            status_code=200,
            headers={},
            created_at=time.time() - 350,
            ttl=300,
            stale_ttl=600,
        )
        await cache_service.set(cache_key, old_entry, force_stale=True)
        
        # Simulate refresh with new data
        new_entry = CacheEntry(
            data=b'{"version": 2}',
            content_type="application/json",
            status_code=200,
            headers={},
            created_at=time.time(),
            ttl=300,
            stale_ttl=600,
        )
        await cache_service.set(cache_key, new_entry)
        
        # Verify new entry is returned
        result = await cache_service.get(cache_key)
        
        assert result is not None
        assert b'"version": 2' in result.entry.data


class TestCacheStampedeProtection:
    """Tests for cache stampede prevention."""

    @pytest.fixture
    def cache_service(self):
        """Create cache service with stampede protection."""
        return CacheService()

    @pytest.mark.asyncio
    async def test_single_flight_lock(self, cache_service):
        """Only one refresh should happen for concurrent requests."""
        cache_key = "stampede:single_flight"
        refresh_count = 0
        
        async def mock_fetch():
            nonlocal refresh_count
            refresh_count += 1
            await asyncio.sleep(0.1)  # Simulate upstream latency
            return CacheEntry(
                data=b'{"fetched": true}',
                content_type="application/json",
                status_code=200,
                headers={},
                created_at=time.time(),
                ttl=300,
                stale_ttl=600,
            )
        
        # Simulate 5 concurrent requests
        tasks = [
            cache_service.get_or_fetch(cache_key, mock_fetch)
            for _ in range(5)
        ]
        
        results = await asyncio.gather(*tasks)
        
        # Only one fetch should have occurred
        assert refresh_count == 1
        
        # All should get the same result
        assert all(r.entry.data == results[0].entry.data for r in results)

    @pytest.mark.asyncio
    async def test_lock_released_on_error(self, cache_service):
        """Lock should be released if fetch fails."""
        cache_key = "stampede:error_release"
        
        async def failing_fetch():
            raise Exception("Upstream error")
        
        # First attempt should fail
        with pytest.raises(Exception):
            await cache_service.get_or_fetch(cache_key, failing_fetch)
        
        # Second attempt should not be blocked
        async def success_fetch():
            return CacheEntry(
                data=b'{"success": true}',
                content_type="application/json",
                status_code=200,
                headers={},
                created_at=time.time(),
                ttl=300,
                stale_ttl=600,
            )
        
        result = await cache_service.get_or_fetch(cache_key, success_fetch)
        assert result is not None


class TestRequestCoalescing:
    """Tests for request coalescing/deduplication."""

    @pytest.fixture
    def cache_service(self):
        """Create cache service with coalescing."""
        return CacheService()

    @pytest.mark.asyncio
    async def test_duplicate_requests_coalesced(self, cache_service):
        """Identical in-flight requests should be coalesced."""
        cache_key = "coalesce:duplicate"
        upstream_calls = 0
        
        async def slow_upstream():
            nonlocal upstream_calls
            upstream_calls += 1
            await asyncio.sleep(0.2)
            return CacheEntry(
                data=b'{"data": "coalesced response"}',
                content_type="application/json",
                status_code=200,
                headers={},
                created_at=time.time(),
                ttl=300,
                stale_ttl=600,
            )
        
        # Start multiple concurrent requests
        tasks = [
            cache_service.get_or_fetch(cache_key, slow_upstream)
            for _ in range(10)
        ]
        
        results = await asyncio.gather(*tasks)
        
        # Only one upstream call should have been made
        assert upstream_calls == 1
        
        # All results should be identical
        first_data = results[0].entry.data
        assert all(r.entry.data == first_data for r in results)

    @pytest.mark.asyncio
    async def test_different_keys_not_coalesced(self, cache_service):
        """Different cache keys should not be coalesced."""
        upstream_calls = 0
        
        async def upstream_call(key_suffix):
            nonlocal upstream_calls
            upstream_calls += 1
            await asyncio.sleep(0.05)
            return CacheEntry(
                data=f'{{"key": "{key_suffix}"}}'.encode(),
                content_type="application/json",
                status_code=200,
                headers={},
                created_at=time.time(),
                ttl=300,
                stale_ttl=600,
            )
        
        # Start requests with different keys
        tasks = [
            cache_service.get_or_fetch(f"coalesce:key_{i}", lambda i=i: upstream_call(i))
            for i in range(3)
        ]
        
        await asyncio.gather(*tasks)
        
        # Each key should trigger its own upstream call
        assert upstream_calls == 3
