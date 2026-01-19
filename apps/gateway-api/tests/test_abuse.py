"""Tests for abuse detection."""

import asyncio
import time

import pytest

from src.services.abuse import AbuseDetector, EWMACalculator, ZScoreDetector
from src.services.redis_client import RedisClient


class TestEWMACalculator:
    """Tests for EWMA calculation."""

    def test_initial_value(self):
        """First value should be returned as-is."""
        result = EWMACalculator.update(current_ewma=0, new_value=10.0, alpha=0.3)
        assert result == 10.0

    def test_smoothing(self):
        """EWMA should smooth values."""
        ewma = 0
        alpha = 0.3
        
        # Add value 100
        ewma = EWMACalculator.update(ewma, 100.0, alpha)
        assert ewma == 100.0
        
        # Add value 100 again - should stay at 100
        ewma = EWMACalculator.update(ewma, 100.0, alpha)
        assert ewma == 100.0
        
        # Add value 0 - should decrease but not to 0
        ewma = EWMACalculator.update(ewma, 0.0, alpha)
        assert 60 < ewma < 80  # Should be around 70

    def test_higher_alpha_more_responsive(self):
        """Higher alpha should react faster to changes."""
        ewma_low = EWMACalculator.update(100.0, 0.0, alpha=0.1)
        ewma_high = EWMACalculator.update(100.0, 0.0, alpha=0.9)
        
        # High alpha reacts more to new value (0)
        assert ewma_high < ewma_low


class TestZScoreDetector:
    """Tests for z-score anomaly detection."""

    def test_normal_value(self):
        """Values within normal range should have low z-score."""
        z = ZScoreDetector.calculate(value=100.0, mean=100.0, std_dev=10.0)
        assert z == 0.0

    def test_anomaly_detection(self):
        """Values far from mean should be detected as anomalies."""
        z = ZScoreDetector.calculate(value=150.0, mean=100.0, std_dev=10.0)
        
        assert z == 5.0
        assert ZScoreDetector.is_anomaly(z, threshold=3.0) is True

    def test_not_anomaly(self):
        """Values within threshold should not be anomalies."""
        z = ZScoreDetector.calculate(value=120.0, mean=100.0, std_dev=10.0)
        
        assert z == 2.0
        assert ZScoreDetector.is_anomaly(z, threshold=3.0) is False

    def test_zero_std_dev(self):
        """Zero std dev should return 0 z-score."""
        z = ZScoreDetector.calculate(value=100.0, mean=50.0, std_dev=0.0)
        assert z == 0.0


@pytest.fixture
def redis_client() -> RedisClient:
    """Get test Redis client in demo mode."""
    client = RedisClient()
    client._redis = None
    client.clear_demo_cache()
    return client


class TestAbuseDetector:
    """Tests for abuse detector service."""

    @pytest.fixture
    def detector(self, redis_client: RedisClient) -> AbuseDetector:
        return AbuseDetector(
            redis=redis_client,
            alpha=0.3,
            z_threshold=3.0,
            block_duration=60,
        )

    @pytest.mark.asyncio
    async def test_normal_request_not_blocked(self, detector: AbuseDetector):
        """Normal requests should not trigger blocks."""
        result = await detector.record_request("api-key-1", is_error=False)
        
        assert result.is_blocked is False
        assert result.is_soft_limited is False
        assert result.rate_multiplier == 1.0

    @pytest.mark.asyncio
    async def test_check_not_blocked(self, detector: AbuseDetector):
        """Check should return not blocked for clean keys."""
        result = await detector.check_abuse("clean-key")
        
        assert result.is_blocked is False

    @pytest.mark.asyncio
    async def test_unblock(self, detector: AbuseDetector):
        """Unblock should clear block status."""
        # This tests the unblock mechanism
        result = await detector.unblock("any-key", admin_id="admin")
        
        # Should return False since wasn't blocked
        assert result is False

    @pytest.mark.asyncio
    async def test_error_tracking(self, detector: AbuseDetector):
        """Errors should be tracked."""
        # Record some errors
        for _ in range(5):
            await detector.record_request("error-key", is_error=True, error_type="upstream_error")
        
        # Should track without immediate block (needs sustained pattern)
        result = await detector.check_abuse("error-key")
        assert result.is_blocked is False  # Not immediate

    @pytest.mark.asyncio
    async def test_rate_spike_detection(self, detector: AbuseDetector):
        """Sudden rate spikes should trigger detection."""
        detector._alpha = 0.1  # Lower alpha for faster EWMA
        key = "spike-key"
        
        # Establish baseline with normal traffic
        for _ in range(100):
            await detector.record_request(key, is_error=False)
            await asyncio.sleep(0.001)
        
        # The spike detection happens on window rollover
        # This is a simplified test - full integration would need time simulation
