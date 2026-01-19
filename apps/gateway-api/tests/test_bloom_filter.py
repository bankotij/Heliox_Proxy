"""Tests for bloom filter implementation."""

import pytest

from src.services.bloom import BloomFilter, NegativeCacheManager
from src.services.redis_client import RedisClient


@pytest.fixture
def redis_client() -> RedisClient:
    """Get test Redis client in demo mode."""
    client = RedisClient()
    client._redis = None
    client.clear_demo_cache()
    return client


class TestBloomFilter:
    """Tests for bloom filter operations."""

    @pytest.fixture
    def bloom(self, redis_client: RedisClient) -> BloomFilter:
        return BloomFilter(
            redis=redis_client,
            name="test:bloom",
            expected_items=1000,
            false_positive_rate=0.01,
        )

    @pytest.mark.asyncio
    async def test_add_and_contains(self, bloom: BloomFilter):
        """Items added should be found."""
        await bloom.add("test-path-1")
        await bloom.add("test-path-2")
        
        assert await bloom.contains("test-path-1") is True
        assert await bloom.contains("test-path-2") is True

    @pytest.mark.asyncio
    async def test_not_contains_unadded(self, bloom: BloomFilter):
        """Items not added should not be found (no false negatives)."""
        await bloom.add("existing-path")
        
        # New item should not be found
        # Note: False positives are possible, but rare
        assert await bloom.contains("completely-different-path-12345") is False

    @pytest.mark.asyncio
    async def test_clear(self, bloom: BloomFilter):
        """Clear should remove all items."""
        await bloom.add("path-1")
        await bloom.add("path-2")
        
        await bloom.clear()
        
        # Items should no longer be found
        assert await bloom.contains("path-1") is False
        assert await bloom.contains("path-2") is False

    @pytest.mark.asyncio
    async def test_optimal_parameters(self, redis_client: RedisClient):
        """Parameters should be calculated correctly."""
        bloom = BloomFilter(
            redis=redis_client,
            name="test:params",
            expected_items=10000,
            false_positive_rate=0.01,
        )
        
        # For n=10000, p=0.01:
        # m should be ~95850 bits
        # k should be ~7 hash functions
        assert 80000 < bloom.bit_size < 120000
        assert 5 <= bloom.hash_count <= 10

    @pytest.mark.asyncio
    async def test_stats(self, bloom: BloomFilter):
        """Stats should return configuration."""
        stats = bloom.get_stats()
        
        assert stats["name"] == "test:bloom"
        assert stats["expected_items"] == 1000
        assert stats["false_positive_rate"] == 0.01
        assert "bit_size" in stats
        assert "hash_functions" in stats
        assert "memory_bytes" in stats

    @pytest.mark.asyncio
    async def test_false_positive_rate(self, redis_client: RedisClient):
        """False positive rate should be within expected bounds."""
        bloom = BloomFilter(
            redis=redis_client,
            name="test:fp",
            expected_items=1000,
            false_positive_rate=0.1,  # 10% FP rate for easier testing
        )
        
        # Add 1000 items
        for i in range(1000):
            await bloom.add(f"added-item-{i}")
        
        # Check 1000 items that were NOT added
        false_positives = 0
        for i in range(1000):
            if await bloom.contains(f"not-added-item-{i}"):
                false_positives += 1
        
        # FP rate should be roughly 10% (allow some variance)
        fp_rate = false_positives / 1000
        assert fp_rate < 0.20  # Should be well under 20%


class TestNegativeCacheManager:
    """Tests for negative cache manager."""

    @pytest.fixture
    def manager(self, redis_client: RedisClient) -> NegativeCacheManager:
        return NegativeCacheManager(
            redis=redis_client,
            default_expected_items=100,
            default_fp_rate=0.01,
        )

    @pytest.mark.asyncio
    async def test_record_and_check_404(self, manager: NegativeCacheManager):
        """Recording 404 should make path detectable."""
        await manager.record_404("api-route", "/items/999")
        
        is_404 = await manager.is_likely_404("api-route", "/items/999")
        assert is_404 is True

    @pytest.mark.asyncio
    async def test_different_routes_independent(self, manager: NegativeCacheManager):
        """Different routes should have independent filters."""
        await manager.record_404("route-a", "/path")
        
        # Same path on different route should not match
        is_404 = await manager.is_likely_404("route-b", "/path")
        assert is_404 is False

    @pytest.mark.asyncio
    async def test_clear_route(self, manager: NegativeCacheManager):
        """Clearing route should remove its 404s."""
        await manager.record_404("clear-route", "/path1")
        await manager.record_404("clear-route", "/path2")
        
        await manager.clear_route("clear-route")
        
        assert await manager.is_likely_404("clear-route", "/path1") is False
        assert await manager.is_likely_404("clear-route", "/path2") is False
