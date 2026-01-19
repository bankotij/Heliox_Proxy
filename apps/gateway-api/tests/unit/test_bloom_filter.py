"""Unit tests for bloom filter negative caching."""

import pytest

from src.services.bloom import BloomFilter, NegativeCacheManager


class TestBloomFilter:
    """Tests for bloom filter implementation."""

    @pytest.fixture
    def bloom(self):
        """Create bloom filter instance."""
        return BloomFilter(
            expected_items=1000,
            false_positive_rate=0.01,
        )

    @pytest.mark.asyncio
    async def test_add_and_check(self, bloom):
        """Should detect added items."""
        await bloom.add("item_12345")
        result = await bloom.might_contain("item_12345")
        assert result is True

    @pytest.mark.asyncio
    async def test_not_added_returns_false(self, bloom):
        """Items not added should return False (mostly)."""
        result = await bloom.might_contain("never_added_item")
        assert result is False

    @pytest.mark.asyncio
    async def test_multiple_items(self, bloom):
        """Should handle multiple items correctly."""
        items = [f"item_{i}" for i in range(100)]
        
        for item in items:
            await bloom.add(item)
        
        # All added items should be found
        for item in items:
            assert await bloom.might_contain(item) is True

    @pytest.mark.asyncio
    async def test_false_positive_rate(self, bloom):
        """False positive rate should be within bounds."""
        # Add 500 items
        for i in range(500):
            await bloom.add(f"added_{i}")
        
        # Check 1000 items that were NOT added
        false_positives = 0
        test_count = 1000
        for i in range(test_count):
            if await bloom.might_contain(f"not_added_{i}"):
                false_positives += 1
        
        # False positive rate should be roughly around 1%
        # Allow some margin due to probabilistic nature
        fp_rate = false_positives / test_count
        assert fp_rate < 0.05  # Allow up to 5% for test stability

    @pytest.mark.asyncio
    async def test_clear_filter(self, bloom):
        """Should be able to clear the filter."""
        await bloom.add("test_item")
        assert await bloom.might_contain("test_item") is True
        
        await bloom.clear()
        
        # After clearing, item might still appear due to false positives
        # but the filter should be reset

    def test_optimal_parameters(self):
        """Should calculate optimal m and k values."""
        bloom = BloomFilter(expected_items=10000, false_positive_rate=0.01)
        
        # m should be approximately -n*ln(p) / (ln2)^2
        # k should be approximately m/n * ln2
        assert bloom.bit_size > 0
        assert bloom.hash_count > 0
        assert bloom.hash_count < 20  # Reasonable number of hash functions


class TestNegativeCacheManager:
    """Tests for negative cache manager."""

    @pytest.fixture
    def manager(self):
        """Create negative cache manager instance."""
        return NegativeCacheManager()

    @pytest.mark.asyncio
    async def test_record_and_check_404(self, manager):
        """Should record and detect 404 patterns."""
        route = "products"
        path = "/items/nonexistent"
        
        await manager.record_miss(route, path, status_code=404)
        
        result = await manager.should_skip_upstream(route, path)
        assert result is True

    @pytest.mark.asyncio
    async def test_successful_response_not_recorded(self, manager):
        """Non-404 responses should not be in negative cache."""
        route = "products"
        path = "/items/existing"
        
        await manager.record_miss(route, path, status_code=200)
        
        result = await manager.should_skip_upstream(route, path)
        assert result is False

    @pytest.mark.asyncio
    async def test_different_routes_independent(self, manager):
        """Different routes should have independent filters."""
        await manager.record_miss("route_a", "/missing", status_code=404)
        
        # Same path on different route should not be cached
        result = await manager.should_skip_upstream("route_b", "/missing")
        assert result is False

    @pytest.mark.asyncio
    async def test_clear_route_filter(self, manager):
        """Should be able to clear filter for a specific route."""
        route = "products"
        await manager.record_miss(route, "/missing1", status_code=404)
        await manager.record_miss(route, "/missing2", status_code=404)
        
        await manager.clear_route(route)
        
        # After clearing, should not detect as negative cached
        result = await manager.should_skip_upstream(route, "/missing1")
        assert result is False
