"""Integration tests for quota management."""

import asyncio
from datetime import datetime, timezone

import pytest

from src.services.rate_limiter import QuotaManager


class TestQuotaIntegration:
    """Integration tests for quota enforcement."""

    @pytest.fixture
    def quota_manager(self):
        """Create quota manager."""
        return QuotaManager()

    @pytest.mark.asyncio
    async def test_daily_quota_enforcement(self, quota_manager):
        """Daily quota should be enforced correctly."""
        api_key_id = "quota_daily_enforce"
        daily_limit = 5
        monthly_limit = 100
        
        # Use up daily quota
        for i in range(daily_limit):
            result = await quota_manager.check_and_increment(
                api_key_id, daily_limit, monthly_limit
            )
            assert result["allowed"] is True, f"Request {i + 1} should be allowed"
            assert result["daily_remaining"] == daily_limit - i - 1
        
        # Next request should be blocked
        result = await quota_manager.check_and_increment(
            api_key_id, daily_limit, monthly_limit
        )
        assert result["allowed"] is False
        assert "daily" in result.get("exceeded", "").lower()

    @pytest.mark.asyncio
    async def test_monthly_quota_enforcement(self, quota_manager):
        """Monthly quota should be enforced correctly."""
        api_key_id = "quota_monthly_enforce"
        daily_limit = 100  # High daily limit
        monthly_limit = 3  # Low monthly limit
        
        # Use up monthly quota
        for i in range(monthly_limit):
            result = await quota_manager.check_and_increment(
                api_key_id, daily_limit, monthly_limit
            )
            assert result["allowed"] is True

        # Next request should be blocked by monthly limit
        result = await quota_manager.check_and_increment(
            api_key_id, daily_limit, monthly_limit
        )
        assert result["allowed"] is False
        assert "monthly" in result.get("exceeded", "").lower()

    @pytest.mark.asyncio
    async def test_quota_usage_tracking(self, quota_manager):
        """Should accurately track quota usage."""
        api_key_id = "quota_tracking"
        daily_limit = 100
        monthly_limit = 1000
        
        # Make some requests
        for _ in range(25):
            await quota_manager.check_and_increment(
                api_key_id, daily_limit, monthly_limit
            )
        
        # Check current usage
        usage = await quota_manager.get_usage(api_key_id)
        
        assert usage["daily_used"] == 25
        assert usage["monthly_used"] == 25
        assert usage["daily_remaining"] == 75
        assert usage["monthly_remaining"] == 975

    @pytest.mark.asyncio
    async def test_independent_key_quotas(self, quota_manager):
        """Different API keys should have independent quotas."""
        daily_limit = 5
        monthly_limit = 50
        
        # Exhaust quota for key1
        for _ in range(daily_limit):
            await quota_manager.check_and_increment(
                "key1", daily_limit, monthly_limit
            )
        
        result1 = await quota_manager.check_and_increment(
            "key1", daily_limit, monthly_limit
        )
        
        # key2 should still have quota
        result2 = await quota_manager.check_and_increment(
            "key2", daily_limit, monthly_limit
        )
        
        assert result1["allowed"] is False
        assert result2["allowed"] is True

    @pytest.mark.asyncio
    async def test_quota_reset(self, quota_manager):
        """Should be able to reset quotas."""
        api_key_id = "quota_reset_test"
        daily_limit = 3
        monthly_limit = 30
        
        # Use some quota
        for _ in range(daily_limit):
            await quota_manager.check_and_increment(
                api_key_id, daily_limit, monthly_limit
            )
        
        # Should be blocked
        result = await quota_manager.check_and_increment(
            api_key_id, daily_limit, monthly_limit
        )
        assert result["allowed"] is False
        
        # Reset daily quota
        await quota_manager.reset_daily(api_key_id)
        
        # Should be allowed again
        result = await quota_manager.check_and_increment(
            api_key_id, daily_limit, monthly_limit
        )
        assert result["allowed"] is True

    @pytest.mark.asyncio
    async def test_concurrent_quota_updates(self, quota_manager):
        """Concurrent requests should correctly update quotas."""
        api_key_id = "quota_concurrent"
        daily_limit = 100
        monthly_limit = 1000
        
        # Simulate 50 concurrent requests
        tasks = [
            quota_manager.check_and_increment(
                api_key_id, daily_limit, monthly_limit
            )
            for _ in range(50)
        ]
        
        results = await asyncio.gather(*tasks)
        
        # All should be allowed
        assert all(r["allowed"] for r in results)
        
        # Usage should be exactly 50
        usage = await quota_manager.get_usage(api_key_id)
        assert usage["daily_used"] == 50

    @pytest.mark.asyncio
    async def test_quota_percentage_calculation(self, quota_manager):
        """Should calculate quota usage percentage."""
        api_key_id = "quota_percentage"
        daily_limit = 100
        monthly_limit = 1000
        
        # Use 30% of daily quota
        for _ in range(30):
            await quota_manager.check_and_increment(
                api_key_id, daily_limit, monthly_limit
            )
        
        usage = await quota_manager.get_usage(api_key_id)
        
        assert usage["daily_percentage"] == 30.0
        assert usage["monthly_percentage"] == 3.0
