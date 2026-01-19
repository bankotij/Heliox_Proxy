"""Tests for rate limiting implementations."""

import asyncio
import time

import pytest

from src.services.rate_limiter import (
    QuotaManager,
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
)
from src.services.redis_client import RedisClient


@pytest.fixture
def redis_client() -> RedisClient:
    """Get test Redis client in demo mode."""
    client = RedisClient()
    client._redis = None  # Force demo mode
    client.clear_demo_cache()
    return client


class TestTokenBucketRateLimiter:
    """Tests for token bucket rate limiter."""

    @pytest.fixture
    def limiter(self, redis_client: RedisClient) -> TokenBucketRateLimiter:
        return TokenBucketRateLimiter(redis_client)

    @pytest.mark.asyncio
    async def test_allows_within_limit(self, limiter: TokenBucketRateLimiter):
        """Requests within rate limit should be allowed."""
        result = await limiter.is_allowed("test-key", rate=10.0, capacity=10)
        
        assert result.allowed is True
        assert result.remaining >= 0
        assert result.limit == 10

    @pytest.mark.asyncio
    async def test_denies_when_exhausted(self, limiter: TokenBucketRateLimiter):
        """Requests should be denied when bucket is empty."""
        # Exhaust the bucket
        for _ in range(10):
            await limiter.is_allowed("exhaust-key", rate=1.0, capacity=10)
        
        # Next request should be denied
        result = await limiter.is_allowed("exhaust-key", rate=1.0, capacity=10)
        
        assert result.allowed is False
        assert result.remaining == 0
        assert result.retry_after is not None
        assert result.retry_after > 0

    @pytest.mark.asyncio
    async def test_refills_over_time(self, limiter: TokenBucketRateLimiter):
        """Bucket should refill tokens over time."""
        # Exhaust bucket
        for _ in range(5):
            await limiter.is_allowed("refill-key", rate=100.0, capacity=5)
        
        # Wait for refill (100 tokens/second = 10ms per token)
        await asyncio.sleep(0.1)
        
        # Should have tokens again
        result = await limiter.is_allowed("refill-key", rate=100.0, capacity=5)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_burst_capacity(self, limiter: TokenBucketRateLimiter):
        """Should allow burst up to capacity."""
        key = "burst-key"
        allowed_count = 0
        
        # Try to make 20 requests quickly
        for _ in range(20):
            result = await limiter.is_allowed(key, rate=1.0, capacity=15)
            if result.allowed:
                allowed_count += 1
        
        # Should have allowed exactly capacity (15)
        assert allowed_count == 15

    @pytest.mark.asyncio
    async def test_reset(self, limiter: TokenBucketRateLimiter):
        """Reset should clear the bucket."""
        key = "reset-key"
        
        # Use some tokens
        for _ in range(5):
            await limiter.is_allowed(key, rate=1.0, capacity=10)
        
        # Reset
        await limiter.reset(key)
        
        # Should have full capacity
        result = await limiter.is_allowed(key, rate=1.0, capacity=10)
        assert result.remaining == 9  # 10 - 1

    @pytest.mark.asyncio
    async def test_different_keys_independent(self, limiter: TokenBucketRateLimiter):
        """Different keys should have independent limits."""
        # Exhaust key1
        for _ in range(5):
            await limiter.is_allowed("key1", rate=1.0, capacity=5)
        
        # key2 should still work
        result = await limiter.is_allowed("key2", rate=1.0, capacity=5)
        assert result.allowed is True


class TestSlidingWindowRateLimiter:
    """Tests for sliding window rate limiter."""

    @pytest.fixture
    def limiter(self, redis_client: RedisClient) -> SlidingWindowRateLimiter:
        return SlidingWindowRateLimiter(redis_client)

    @pytest.mark.asyncio
    async def test_allows_within_limit(self, limiter: SlidingWindowRateLimiter):
        """Requests within window limit should be allowed."""
        result = await limiter.is_allowed("sw-test", rate=10.0, capacity=10)
        
        assert result.allowed is True
        assert result.limit == 10

    @pytest.mark.asyncio
    async def test_denies_when_limit_exceeded(self, limiter: SlidingWindowRateLimiter):
        """Requests exceeding window limit should be denied."""
        key = "sw-exceed"
        
        # Make requests up to limit
        for _ in range(10):
            await limiter.is_allowed(key, rate=10.0, capacity=10)
        
        # Next should be denied
        result = await limiter.is_allowed(key, rate=10.0, capacity=10)
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_window_expires(self, limiter: SlidingWindowRateLimiter):
        """Old requests should expire from window."""
        key = "sw-expire"
        
        # High rate = small window
        # 100 req/s with capacity 5 = 50ms window
        for _ in range(5):
            await limiter.is_allowed(key, rate=100.0, capacity=5)
        
        # Should be denied
        result = await limiter.is_allowed(key, rate=100.0, capacity=5)
        assert result.allowed is False
        
        # Wait for window to expire
        await asyncio.sleep(0.1)
        
        # Should be allowed again
        result = await limiter.is_allowed(key, rate=100.0, capacity=5)
        assert result.allowed is True


class TestQuotaManager:
    """Tests for quota management."""

    @pytest.fixture
    def quota(self, redis_client: RedisClient) -> QuotaManager:
        return QuotaManager(redis_client)

    @pytest.mark.asyncio
    async def test_allows_within_daily_quota(self, quota: QuotaManager):
        """Requests within daily quota should be allowed."""
        allowed, reason = await quota.check_and_increment("key1", daily_limit=100, monthly_limit=0)
        
        assert allowed is True
        assert reason is None

    @pytest.mark.asyncio
    async def test_denies_when_daily_quota_exceeded(self, quota: QuotaManager):
        """Requests exceeding daily quota should be denied."""
        key = "quota-daily"
        
        # Use up quota
        for _ in range(10):
            await quota.check_and_increment(key, daily_limit=10, monthly_limit=0)
        
        # Next should be denied
        allowed, reason = await quota.check_and_increment(key, daily_limit=10, monthly_limit=0)
        
        assert allowed is False
        assert reason == "daily_quota_exceeded"

    @pytest.mark.asyncio
    async def test_unlimited_when_zero(self, quota: QuotaManager):
        """Zero quota means unlimited."""
        key = "quota-unlimited"
        
        # Make many requests
        for _ in range(100):
            allowed, _ = await quota.check_and_increment(key, daily_limit=0, monthly_limit=0)
            assert allowed is True

    @pytest.mark.asyncio
    async def test_get_usage(self, quota: QuotaManager):
        """Should track usage correctly."""
        key = "quota-usage"
        
        # Make 5 requests
        for _ in range(5):
            await quota.check_and_increment(key, daily_limit=100, monthly_limit=100)
        
        usage = await quota.get_usage(key)
        
        assert usage["daily_usage"] == 5
        assert usage["monthly_usage"] == 5
