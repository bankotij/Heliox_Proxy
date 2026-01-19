"""Unit tests for rate limiting algorithms."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.services.rate_limiter import (
    QuotaManager,
    RateLimitResult,
    SlidingWindowRateLimiter,
    TokenBucketRateLimiter,
)


class TestTokenBucketRateLimiter:
    """Tests for token bucket rate limiter."""

    @pytest.fixture
    def limiter(self):
        """Create token bucket limiter instance."""
        return TokenBucketRateLimiter()

    @pytest.mark.asyncio
    async def test_allows_requests_under_limit(self, limiter):
        """Should allow requests when under rate limit."""
        result = await limiter.check(
            key="user:12345",
            rate_per_second=10.0,
            burst_size=20,
        )
        assert result.allowed is True
        assert result.remaining > 0

    @pytest.mark.asyncio
    async def test_blocks_requests_over_limit(self, limiter):
        """Should block requests when burst is exhausted."""
        key = "user:burst_test"
        rate = 1.0  # 1 request per second
        burst = 3  # Only 3 tokens in bucket

        # Exhaust the burst
        for i in range(burst):
            result = await limiter.check(key, rate, burst)
            assert result.allowed is True, f"Request {i + 1} should be allowed"

        # Next request should be blocked
        result = await limiter.check(key, rate, burst)
        assert result.allowed is False
        assert result.retry_after > 0

    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self, limiter):
        """Should refill tokens at the specified rate."""
        key = "user:refill_test"
        rate = 10.0  # 10 tokens per second
        burst = 5

        # Exhaust tokens
        for _ in range(burst):
            await limiter.check(key, rate, burst)

        # Should be blocked now
        result = await limiter.check(key, rate, burst)
        assert result.allowed is False

        # Wait for refill (100ms = 1 token at 10/sec)
        await asyncio.sleep(0.15)

        # Should have at least 1 token now
        result = await limiter.check(key, rate, burst)
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_different_keys_independent(self, limiter):
        """Different keys should have independent limits."""
        rate = 1.0
        burst = 1

        # Exhaust key1
        await limiter.check("key1", rate, burst)
        result1 = await limiter.check("key1", rate, burst)

        # key2 should still work
        result2 = await limiter.check("key2", rate, burst)

        assert result1.allowed is False
        assert result2.allowed is True


class TestSlidingWindowRateLimiter:
    """Tests for sliding window rate limiter."""

    @pytest.fixture
    def limiter(self):
        """Create sliding window limiter instance."""
        return SlidingWindowRateLimiter(window_size_seconds=1)

    @pytest.mark.asyncio
    async def test_allows_requests_under_limit(self, limiter):
        """Should allow requests under the window limit."""
        result = await limiter.check(
            key="user:sw_12345",
            max_requests=10,
        )
        assert result.allowed is True
        assert result.remaining == 9

    @pytest.mark.asyncio
    async def test_blocks_requests_over_limit(self, limiter):
        """Should block requests exceeding window limit."""
        key = "user:sw_limit_test"
        max_requests = 3

        # Use up all requests in window
        for i in range(max_requests):
            result = await limiter.check(key, max_requests)
            assert result.allowed is True, f"Request {i + 1} should be allowed"

        # Next should be blocked
        result = await limiter.check(key, max_requests)
        assert result.allowed is False

    @pytest.mark.asyncio
    async def test_window_slides(self, limiter):
        """Requests should be allowed again after window slides."""
        key = "user:sw_slide_test"
        max_requests = 2

        # Use up requests
        await limiter.check(key, max_requests)
        await limiter.check(key, max_requests)

        result = await limiter.check(key, max_requests)
        assert result.allowed is False

        # Wait for window to slide
        await asyncio.sleep(1.1)

        # Should be allowed again
        result = await limiter.check(key, max_requests)
        assert result.allowed is True


class TestQuotaManager:
    """Tests for quota management."""

    @pytest.fixture
    def quota_manager(self):
        """Create quota manager instance."""
        return QuotaManager()

    @pytest.mark.asyncio
    async def test_daily_quota_tracking(self, quota_manager):
        """Should track daily quota usage."""
        key_id = "quota_daily_test"
        daily_limit = 100

        result = await quota_manager.check_and_increment(
            api_key_id=key_id,
            daily_limit=daily_limit,
            monthly_limit=1000,
        )

        assert result["allowed"] is True
        assert result["daily_remaining"] == daily_limit - 1

    @pytest.mark.asyncio
    async def test_daily_quota_exceeded(self, quota_manager):
        """Should block when daily quota exceeded."""
        key_id = "quota_exceed_test"
        daily_limit = 3

        # Use up quota
        for _ in range(daily_limit):
            result = await quota_manager.check_and_increment(
                api_key_id=key_id,
                daily_limit=daily_limit,
                monthly_limit=1000,
            )
            assert result["allowed"] is True

        # Should be blocked
        result = await quota_manager.check_and_increment(
            api_key_id=key_id,
            daily_limit=daily_limit,
            monthly_limit=1000,
        )
        assert result["allowed"] is False
        assert "daily" in result.get("exceeded", "")

    @pytest.mark.asyncio
    async def test_monthly_quota_tracking(self, quota_manager):
        """Should track monthly quota separately."""
        key_id = "quota_monthly_test"

        result = await quota_manager.check_and_increment(
            api_key_id=key_id,
            daily_limit=1000,
            monthly_limit=500,
        )

        assert result["allowed"] is True
        assert result["monthly_remaining"] == 499
