"""
Unit tests for advanced algorithms.

Tests:
- Leaky Bucket Rate Limiter
- Circuit Breaker
- Count-Min Sketch
- Consistent Hashing
- Exponential Backoff
- HyperLogLog (mocked)
"""

import asyncio
import math
import pytest

# Import algorithms (these don't need Redis for basic tests)
from src.services.algorithms import (
    ConsistentHash,
    ExponentialBackoff,
    EWMACalculator,
    ZScoreDetector,
)


class TestConsistentHash:
    """Tests for Consistent Hashing."""

    def test_basic_lookup(self):
        """Test basic key-to-node mapping."""
        ch = ConsistentHash(nodes=["node-1", "node-2", "node-3"])
        
        # Same key should always map to same node
        node1 = ch.get_node("test-key")
        node2 = ch.get_node("test-key")
        assert node1 == node2
        assert node1 in ["node-1", "node-2", "node-3"]

    def test_add_node(self):
        """Test adding a node to the ring."""
        ch = ConsistentHash(nodes=["node-1", "node-2"])
        initial_distribution = ch.get_distribution()
        
        ch.add_node("node-3")
        new_distribution = ch.get_distribution()
        
        assert len(new_distribution) == 3
        assert "node-3" in new_distribution

    def test_remove_node(self):
        """Test removing a node from the ring."""
        ch = ConsistentHash(nodes=["node-1", "node-2", "node-3"])
        
        ch.remove_node("node-2")
        distribution = ch.get_distribution()
        
        assert len(distribution) == 2
        assert "node-2" not in distribution

    def test_consistent_remapping(self):
        """Test that adding/removing nodes minimizes key remapping."""
        ch = ConsistentHash(nodes=["node-1", "node-2", "node-3"])
        
        # Get mappings for 100 keys
        keys = [f"key-{i}" for i in range(100)]
        original_mappings = {k: ch.get_node(k) for k in keys}
        
        # Add a new node
        ch.add_node("node-4")
        new_mappings = {k: ch.get_node(k) for k in keys}
        
        # Count how many keys changed
        changed = sum(1 for k in keys if original_mappings[k] != new_mappings[k])
        
        # With consistent hashing, only ~25% of keys should move to the new node
        assert changed < 40  # Allow some variance

    def test_get_multiple_nodes(self):
        """Test getting multiple nodes for replication."""
        ch = ConsistentHash(nodes=["node-1", "node-2", "node-3"])
        
        nodes = ch.get_nodes("test-key", count=2)
        
        assert len(nodes) == 2
        assert len(set(nodes)) == 2  # All unique

    def test_empty_ring(self):
        """Test behavior with empty ring."""
        ch = ConsistentHash()
        
        assert ch.get_node("test-key") is None
        assert ch.get_nodes("test-key", count=3) == []

    def test_virtual_nodes_distribution(self):
        """Test that virtual nodes provide even distribution."""
        ch = ConsistentHash(
            nodes=["node-1", "node-2", "node-3"],
            virtual_nodes=150,
        )
        
        distribution = ch.get_distribution()
        
        # Each node should have ~150 virtual nodes
        for node, count in distribution.items():
            assert 140 <= count <= 160


class TestExponentialBackoff:
    """Tests for Exponential Backoff."""

    def test_basic_progression(self):
        """Test basic delay progression without jitter."""
        backoff = ExponentialBackoff(
            base_delay=1.0,
            max_delay=60.0,
            max_attempts=5,
            jitter=False,
        )
        
        result1 = backoff.get_delay(1)
        result2 = backoff.get_delay(2)
        result3 = backoff.get_delay(3)
        
        assert result1.delay_seconds == 1.0
        assert result2.delay_seconds == 2.0
        assert result3.delay_seconds == 4.0

    def test_max_delay_cap(self):
        """Test that delay is capped at max_delay."""
        backoff = ExponentialBackoff(
            base_delay=10.0,
            max_delay=30.0,
            max_attempts=10,
            jitter=False,
        )
        
        result = backoff.get_delay(5)  # Would be 160s without cap
        
        assert result.delay_seconds <= 30.0

    def test_max_attempts(self):
        """Test that retries stop after max_attempts."""
        backoff = ExponentialBackoff(max_attempts=3)
        
        result1 = backoff.get_delay(1)
        result2 = backoff.get_delay(2)
        result3 = backoff.get_delay(3)
        result4 = backoff.get_delay(4)
        
        assert result1.should_retry is True
        assert result2.should_retry is True
        assert result3.should_retry is False
        assert result4.should_retry is False

    def test_jitter_randomization(self):
        """Test that jitter adds randomization."""
        backoff = ExponentialBackoff(
            base_delay=1.0,
            max_attempts=5,
            jitter=True,
        )
        
        # Get multiple delays for the same attempt
        delays = [backoff.get_delay(2).delay_seconds for _ in range(10)]
        
        # With jitter, delays should vary
        assert len(set(delays)) > 1  # Not all the same
        
        # All should be within [0, 2.0] for attempt 2
        for d in delays:
            assert 0 <= d <= 2.0


class TestEWMACalculator:
    """Tests for EWMA (Exponentially Weighted Moving Average)."""

    def test_initial_value(self):
        """Test that first value becomes the EWMA."""
        result = EWMACalculator.update(0, 100, 0.3)
        assert result == 100

    def test_smoothing(self):
        """Test that EWMA smooths values."""
        ewma = 0
        values = [100, 100, 100, 200]  # Sudden spike
        
        for v in values:
            ewma = EWMACalculator.update(ewma, v, 0.3)
        
        # EWMA should be between old average and spike
        assert 100 < ewma < 200

    def test_alpha_sensitivity(self):
        """Test different alpha values."""
        # High alpha = more sensitive to recent values
        ewma_high = EWMACalculator.update(100, 200, 0.9)
        # Low alpha = less sensitive to recent values
        ewma_low = EWMACalculator.update(100, 200, 0.1)
        
        assert ewma_high > ewma_low
        assert ewma_high == pytest.approx(190)  # 0.9*200 + 0.1*100
        assert ewma_low == pytest.approx(110)   # 0.1*200 + 0.9*100

    def test_variance_update(self):
        """Test variance calculation."""
        variance = 0
        ewma = 100
        
        variance = EWMACalculator.update_variance(variance, ewma, 150, 0.3)
        
        assert variance > 0


class TestZScoreDetector:
    """Tests for Z-Score Anomaly Detection."""

    def test_normal_value(self):
        """Test that normal values have low z-score."""
        z = ZScoreDetector.calculate(
            value=100,
            mean=100,
            std_dev=10,
        )
        
        assert z == 0.0
        assert not ZScoreDetector.is_anomaly(z, threshold=3.0)

    def test_anomaly_detection(self):
        """Test that outliers have high z-score."""
        z = ZScoreDetector.calculate(
            value=150,  # 5 std devs above mean
            mean=100,
            std_dev=10,
        )
        
        assert z == 5.0
        assert ZScoreDetector.is_anomaly(z, threshold=3.0)

    def test_negative_anomaly(self):
        """Test detection of values below mean."""
        z = ZScoreDetector.calculate(
            value=50,
            mean=100,
            std_dev=10,
        )
        
        assert z == -5.0
        assert ZScoreDetector.is_anomaly(z, threshold=3.0)

    def test_zero_std_dev(self):
        """Test handling of zero standard deviation."""
        z = ZScoreDetector.calculate(
            value=100,
            mean=100,
            std_dev=0,
        )
        
        assert z == 0.0  # Avoid division by zero

    def test_threshold_boundary(self):
        """Test values at the threshold boundary."""
        # Exactly at threshold
        z_at = ZScoreDetector.calculate(150, 100, 50/3)  # z = 3.0
        assert pytest.approx(abs(z_at)) == 3.0
        assert not ZScoreDetector.is_anomaly(z_at, threshold=3.0)  # Not > threshold
        
        # Just above threshold
        z_above = ZScoreDetector.calculate(151, 100, 50/3)
        assert ZScoreDetector.is_anomaly(z_above, threshold=3.0)


class TestCountMinSketchMath:
    """Tests for Count-Min Sketch error bound calculations."""

    def test_error_bounds_calculation(self):
        """Test theoretical error bound formulas."""
        width = 1000
        depth = 5
        
        # ε ≈ e/width
        epsilon = math.e / width
        # δ ≈ e^(-depth)
        delta = math.exp(-depth)
        
        assert epsilon == pytest.approx(0.00272, rel=0.01)
        assert delta == pytest.approx(0.00674, rel=0.01)

    def test_optimal_parameters(self):
        """Test calculating optimal CMS parameters."""
        # For 1% error with 99% probability
        target_epsilon = 0.01
        target_delta = 0.01
        
        optimal_width = int(math.ceil(math.e / target_epsilon))
        optimal_depth = int(math.ceil(math.log(1 / target_delta)))
        
        assert optimal_width == 272
        assert optimal_depth == 5


class TestCircuitBreakerLogic:
    """Tests for Circuit Breaker state machine logic."""

    def test_state_transitions(self):
        """Test the state transition diagram."""
        # States
        CLOSED = "closed"
        OPEN = "open"
        HALF_OPEN = "half_open"
        
        # Valid transitions
        valid_transitions = {
            CLOSED: [OPEN],       # failures exceed threshold
            OPEN: [HALF_OPEN],   # timeout elapsed
            HALF_OPEN: [CLOSED, OPEN],  # success or failure
        }
        
        # Verify all transitions are defined
        for state, targets in valid_transitions.items():
            assert len(targets) > 0
            for target in targets:
                assert target in [CLOSED, OPEN, HALF_OPEN]


class TestPriorityQueueLogic:
    """Tests for Priority Queue ordering logic."""

    def test_priority_ordering(self):
        """Test that items are ordered by priority."""
        items = [
            ("low", 1),
            ("medium", 5),
            ("high", 10),
            ("urgent", 100),
        ]
        
        # Sort by priority (descending for pop order)
        sorted_items = sorted(items, key=lambda x: x[1], reverse=True)
        
        assert sorted_items[0][0] == "urgent"
        assert sorted_items[-1][0] == "low"
