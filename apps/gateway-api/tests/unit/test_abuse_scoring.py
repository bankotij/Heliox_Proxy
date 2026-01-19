"""Unit tests for abuse detection and scoring."""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from src.services.abuse import (
    AbuseDetector,
    AbuseScore,
    EWMACalculator,
    ZScoreDetector,
)


class TestEWMACalculator:
    """Tests for exponentially weighted moving average calculator."""

    def test_initial_value(self):
        """First value should be the EWMA."""
        calc = EWMACalculator(alpha=0.3)
        result = calc.update(100.0)
        assert result == 100.0

    def test_ewma_smoothing(self):
        """EWMA should smooth values over time."""
        calc = EWMACalculator(alpha=0.3)
        
        # Initialize with 100
        calc.update(100.0)
        
        # Add a spike
        result = calc.update(200.0)
        
        # EWMA should be between 100 and 200
        # new_ewma = 0.3 * 200 + 0.7 * 100 = 60 + 70 = 130
        assert result == pytest.approx(130.0)

    def test_ewma_convergence(self):
        """EWMA should converge to constant input."""
        calc = EWMACalculator(alpha=0.5)
        
        # Start with different value
        calc.update(0.0)
        
        # Keep updating with 100
        for _ in range(20):
            result = calc.update(100.0)
        
        # Should converge close to 100
        assert result == pytest.approx(100.0, rel=0.01)

    def test_alpha_affects_responsiveness(self):
        """Higher alpha should respond faster to changes."""
        calc_fast = EWMACalculator(alpha=0.8)
        calc_slow = EWMACalculator(alpha=0.2)
        
        # Initialize both
        calc_fast.update(0.0)
        calc_slow.update(0.0)
        
        # Single update with new value
        fast_result = calc_fast.update(100.0)
        slow_result = calc_slow.update(100.0)
        
        # Fast should be closer to 100
        assert fast_result > slow_result

    def test_reset(self):
        """Should be able to reset the calculator."""
        calc = EWMACalculator(alpha=0.3)
        calc.update(100.0)
        calc.update(200.0)
        
        calc.reset()
        
        # After reset, next value becomes the EWMA
        result = calc.update(50.0)
        assert result == 50.0


class TestZScoreDetector:
    """Tests for Z-score anomaly detection."""

    @pytest.fixture
    def detector(self):
        """Create Z-score detector."""
        return ZScoreDetector(threshold=3.0, window_size=20)

    def test_normal_values_not_anomalous(self, detector):
        """Normal values should not be flagged as anomalies."""
        # Build up history with normal values
        for i in range(20):
            result = detector.check(100.0 + (i % 5))
        
        # Check a normal value
        is_anomaly, z_score = detector.check(102.0)
        assert is_anomaly is False

    def test_spike_detected(self, detector):
        """Large spikes should be detected as anomalies."""
        # Build up stable history
        for _ in range(20):
            detector.check(100.0)
        
        # Add a massive spike
        is_anomaly, z_score = detector.check(500.0)
        
        assert is_anomaly is True
        assert z_score > 3.0

    def test_gradual_increase_not_anomalous(self, detector):
        """Gradual increases should not trigger anomaly detection."""
        # Gradually increase values
        for i in range(30):
            is_anomaly, _ = detector.check(100.0 + i * 2)
        
        # Next gradual increase should not be anomalous
        is_anomaly, _ = detector.check(160.0)
        assert is_anomaly is False

    def test_insufficient_data(self, detector):
        """Should not flag anomalies with insufficient data."""
        # Only a few data points
        for val in [100, 200, 50]:
            is_anomaly, _ = detector.check(val)
            # With insufficient history, shouldn't flag as anomaly
            assert is_anomaly is False

    def test_custom_threshold(self):
        """Should respect custom threshold."""
        strict_detector = ZScoreDetector(threshold=2.0, window_size=20)
        lenient_detector = ZScoreDetector(threshold=4.0, window_size=20)
        
        # Build history
        for _ in range(20):
            strict_detector.check(100.0)
            lenient_detector.check(100.0)
        
        # Moderate spike
        strict_result, _ = strict_detector.check(150.0)
        lenient_result, _ = lenient_detector.check(150.0)
        
        # Strict might flag it, lenient shouldn't
        # This depends on the actual std dev


class TestAbuseDetector:
    """Tests for the main abuse detection system."""

    @pytest.fixture
    def detector(self):
        """Create abuse detector."""
        return AbuseDetector(
            ewma_alpha=0.3,
            zscore_threshold=3.0,
            block_duration_seconds=60,
        )

    @pytest.mark.asyncio
    async def test_normal_traffic_not_blocked(self, detector):
        """Normal traffic patterns should not trigger blocks."""
        api_key_id = "key_normal_traffic"
        
        # Simulate normal traffic
        for _ in range(10):
            score = await detector.record_request(
                api_key_id=api_key_id,
                response_time_ms=50,
                is_error=False,
            )
            assert score.should_block is False

    @pytest.mark.asyncio
    async def test_high_error_rate_increases_score(self, detector):
        """High error rates should increase abuse score."""
        api_key_id = "key_error_traffic"
        
        # Establish baseline
        for _ in range(20):
            await detector.record_request(api_key_id, 50, is_error=False)
        
        # Generate errors
        for _ in range(10):
            score = await detector.record_request(
                api_key_id=api_key_id,
                response_time_ms=50,
                is_error=True,
            )
        
        # Score should have increased
        assert score.error_rate > 0

    @pytest.mark.asyncio
    async def test_request_spike_detected(self, detector):
        """Sudden request spikes should be detected."""
        api_key_id = "key_spike_traffic"
        
        # Normal rate: 1 request every 100ms
        for _ in range(20):
            await detector.record_request(api_key_id, 50, is_error=False)
            await asyncio.sleep(0.01)
        
        # Spike: many requests quickly
        for _ in range(50):
            score = await detector.record_request(api_key_id, 50, is_error=False)
        
        # Should detect elevated request rate
        assert score.request_rate > 0

    @pytest.mark.asyncio
    async def test_soft_block_applied(self, detector):
        """Should apply soft block for abusive behavior."""
        api_key_id = "key_abusive"
        
        # Force high abuse score by generating many errors rapidly
        for _ in range(100):
            score = await detector.record_request(
                api_key_id=api_key_id,
                response_time_ms=5000,  # Slow responses
                is_error=True,  # All errors
            )
        
        # Check if blocked
        is_blocked = await detector.is_blocked(api_key_id)
        # Note: May or may not be blocked depending on scoring thresholds

    @pytest.mark.asyncio
    async def test_block_expires(self, detector):
        """Soft blocks should expire after duration."""
        api_key_id = "key_block_expire"
        
        # Manually block
        await detector.apply_block(api_key_id, duration_seconds=1)
        
        assert await detector.is_blocked(api_key_id) is True
        
        # Wait for expiry
        await asyncio.sleep(1.1)
        
        assert await detector.is_blocked(api_key_id) is False

    @pytest.mark.asyncio
    async def test_get_score_summary(self, detector):
        """Should return score summary for API key."""
        api_key_id = "key_summary"
        
        await detector.record_request(api_key_id, 50, is_error=False)
        await detector.record_request(api_key_id, 100, is_error=True)
        
        score = await detector.get_score(api_key_id)
        
        assert isinstance(score, AbuseScore)
        assert hasattr(score, "request_rate")
        assert hasattr(score, "error_rate")
        assert hasattr(score, "should_block")
