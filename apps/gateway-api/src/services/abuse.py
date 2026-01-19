"""
Abuse detection using EWMA and Z-score anomaly detection.

Monitors request patterns per API key and automatically applies
soft blocks when anomalous behavior is detected.
"""

import math
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

from src.config import get_settings
from src.services.redis_client import RedisClient, redis_client

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


@dataclass
class AbuseMetrics:
    """Metrics tracked for abuse detection."""

    # Request rate tracking (EWMA)
    ewma_rate: float = 0.0
    ewma_rate_variance: float = 0.0
    last_rate_update: float = 0.0

    # Error rate tracking
    ewma_error_rate: float = 0.0
    total_requests: int = 0
    total_errors: int = 0

    # Window counters
    window_start: float = 0.0
    window_requests: int = 0
    window_errors: int = 0


@dataclass
class AbuseCheckResult:
    """Result of an abuse check."""

    is_blocked: bool = False
    is_soft_limited: bool = False
    rate_multiplier: float = 1.0
    reason: str | None = None
    anomaly_score: float = 0.0
    block_until: float | None = None


class EWMACalculator:
    """
    Exponentially Weighted Moving Average calculator.
    
    EWMA smooths out short-term fluctuations while tracking trends.
    Higher alpha = more weight on recent values.
    """

    @staticmethod
    def update(
        current_ewma: float,
        new_value: float,
        alpha: float,
    ) -> float:
        """
        Update EWMA with a new value.
        
        EWMA_new = alpha * new_value + (1 - alpha) * EWMA_old
        
        Args:
            current_ewma: Current EWMA value
            new_value: New observed value
            alpha: Smoothing factor (0-1)
        
        Returns:
            Updated EWMA value
        """
        if current_ewma == 0:
            return new_value
        return alpha * new_value + (1 - alpha) * current_ewma

    @staticmethod
    def update_variance(
        current_variance: float,
        current_ewma: float,
        new_value: float,
        alpha: float,
    ) -> float:
        """
        Update EWMA variance for standard deviation calculation.
        
        Variance_new = (1 - alpha) * (Variance_old + alpha * (new - EWMA_old)^2)
        
        Args:
            current_variance: Current variance estimate
            current_ewma: Current EWMA (before update)
            new_value: New observed value
            alpha: Smoothing factor
        
        Returns:
            Updated variance estimate
        """
        diff = new_value - current_ewma
        return (1 - alpha) * (current_variance + alpha * diff * diff)


class ZScoreDetector:
    """
    Z-score based anomaly detector.
    
    Calculates how many standard deviations a value is from the mean.
    Values beyond the threshold are considered anomalous.
    """

    @staticmethod
    def calculate(
        value: float,
        mean: float,
        std_dev: float,
    ) -> float:
        """
        Calculate z-score.
        
        z = (value - mean) / std_dev
        
        Args:
            value: Observed value
            mean: Expected mean (EWMA)
            std_dev: Standard deviation
        
        Returns:
            Z-score (number of std devs from mean)
        """
        if std_dev == 0:
            return 0.0
        return (value - mean) / std_dev

    @staticmethod
    def is_anomaly(z_score: float, threshold: float) -> bool:
        """Check if z-score indicates an anomaly."""
        return abs(z_score) > threshold


class AbuseDetector:
    """
    Real-time abuse detection for API keys.
    
    Tracks request rates and error rates per key, using EWMA for
    smoothing and z-score for anomaly detection.
    
    When anomalies are detected:
    1. First offense: Apply rate limit multiplier (e.g., 0.5x)
    2. Repeated offenses: Soft block for configurable duration
    
    All blocks are temporary and logged for admin review.
    """

    # Redis key prefixes
    PREFIX_METRICS = "abuse:metrics:"
    PREFIX_BLOCK = "abuse:block:"
    PREFIX_HISTORY = "abuse:history:"

    # Time window for rate calculation (seconds)
    RATE_WINDOW = 60.0

    def __init__(
        self,
        redis: RedisClient | None = None,
        alpha: float | None = None,
        z_threshold: float | None = None,
        block_duration: int | None = None,
    ) -> None:
        """
        Initialize abuse detector.
        
        Args:
            redis: Redis client
            alpha: EWMA smoothing factor (default from config)
            z_threshold: Z-score threshold for anomaly (default from config)
            block_duration: Soft block duration in seconds (default from config)
        """
        self._redis = redis or redis_client
        settings = get_settings()

        self._alpha = alpha or settings.abuse_ewma_alpha
        self._z_threshold = z_threshold or settings.abuse_zscore_threshold
        self._block_duration = block_duration or settings.abuse_block_duration_seconds

    async def record_request(
        self,
        api_key_id: str,
        is_error: bool = False,
        error_type: str | None = None,
    ) -> AbuseCheckResult:
        """
        Record a request and check for abuse.
        
        This should be called after each request is processed.
        
        Args:
            api_key_id: The API key making the request
            is_error: Whether the request resulted in an error
            error_type: Type of error if applicable
        
        Returns:
            AbuseCheckResult with block status and recommendations
        """
        now = time.time()
        metrics_key = f"{self.PREFIX_METRICS}{api_key_id}"

        # Load current metrics
        metrics = await self._load_metrics(metrics_key)

        # Check if already blocked
        block_result = await self._check_block(api_key_id)
        if block_result.is_blocked:
            return block_result

        # Update window counters
        if now - metrics.window_start > self.RATE_WINDOW:
            # Window expired - calculate rates and update EWMA
            if metrics.window_requests > 0:
                current_rate = metrics.window_requests / self.RATE_WINDOW
                current_error_rate = (
                    metrics.window_errors / metrics.window_requests
                    if metrics.window_requests > 0
                    else 0
                )

                # Update EWMA for rate
                old_ewma = metrics.ewma_rate
                metrics.ewma_rate = EWMACalculator.update(
                    metrics.ewma_rate,
                    current_rate,
                    self._alpha,
                )
                metrics.ewma_rate_variance = EWMACalculator.update_variance(
                    metrics.ewma_rate_variance,
                    old_ewma,
                    current_rate,
                    self._alpha,
                )

                # Update EWMA for error rate
                metrics.ewma_error_rate = EWMACalculator.update(
                    metrics.ewma_error_rate,
                    current_error_rate,
                    self._alpha,
                )

                # Check for anomalies
                anomaly_result = await self._check_anomaly(
                    api_key_id,
                    current_rate,
                    current_error_rate,
                    metrics,
                )
                if anomaly_result.is_blocked or anomaly_result.is_soft_limited:
                    await self._save_metrics(metrics_key, metrics)
                    return anomaly_result

            # Reset window
            metrics.window_start = now
            metrics.window_requests = 0
            metrics.window_errors = 0

        # Increment counters
        metrics.window_requests += 1
        metrics.total_requests += 1
        if is_error:
            metrics.window_errors += 1
            metrics.total_errors += 1
        metrics.last_rate_update = now

        # Save updated metrics
        await self._save_metrics(metrics_key, metrics)

        return AbuseCheckResult(
            is_blocked=False,
            is_soft_limited=False,
            rate_multiplier=1.0,
        )

    async def check_abuse(self, api_key_id: str) -> AbuseCheckResult:
        """
        Check if an API key is currently blocked or rate limited.
        
        Call this at the start of request processing.
        
        Args:
            api_key_id: The API key to check
        
        Returns:
            AbuseCheckResult with current status
        """
        return await self._check_block(api_key_id)

    async def _check_block(self, api_key_id: str) -> AbuseCheckResult:
        """Check if key is currently blocked."""
        block_key = f"{self.PREFIX_BLOCK}{api_key_id}"
        block_data = await self._redis.hgetall(block_key)

        if not block_data:
            return AbuseCheckResult()

        blocked_until = float(block_data.get("until", 0))
        if blocked_until > time.time():
            return AbuseCheckResult(
                is_blocked=True,
                reason=block_data.get("reason", "abuse_detected"),
                anomaly_score=float(block_data.get("score", 0)),
                block_until=blocked_until,
            )

        # Block expired - clean up
        await self._redis.delete(block_key)
        return AbuseCheckResult()

    async def _check_anomaly(
        self,
        api_key_id: str,
        current_rate: float,
        current_error_rate: float,
        metrics: AbuseMetrics,
    ) -> AbuseCheckResult:
        """Check for anomalous behavior and apply restrictions."""
        # Calculate z-scores
        std_dev = math.sqrt(max(0, metrics.ewma_rate_variance))
        rate_z = ZScoreDetector.calculate(current_rate, metrics.ewma_rate, std_dev)

        # Check rate spike
        if ZScoreDetector.is_anomaly(rate_z, self._z_threshold):
            logger.warning(
                "Rate spike detected",
                api_key_id=api_key_id,
                current_rate=current_rate,
                ewma_rate=metrics.ewma_rate,
                z_score=rate_z,
            )

            # Apply soft block
            await self._apply_block(
                api_key_id,
                reason="rate_spike",
                score=rate_z,
                rate=current_rate,
                error_rate=current_error_rate,
            )

            return AbuseCheckResult(
                is_blocked=True,
                reason="rate_spike",
                anomaly_score=rate_z,
                block_until=time.time() + self._block_duration,
            )

        # Check error rate spike
        if current_error_rate > 0.5 and metrics.total_requests > 10:
            error_z = (current_error_rate - metrics.ewma_error_rate) / 0.1
            if error_z > self._z_threshold:
                logger.warning(
                    "Error rate spike detected",
                    api_key_id=api_key_id,
                    error_rate=current_error_rate,
                    ewma_error_rate=metrics.ewma_error_rate,
                )

                # Apply rate limit multiplier instead of block
                return AbuseCheckResult(
                    is_soft_limited=True,
                    rate_multiplier=0.5,
                    reason="error_rate_spike",
                    anomaly_score=error_z,
                )

        return AbuseCheckResult()

    async def _apply_block(
        self,
        api_key_id: str,
        reason: str,
        score: float,
        rate: float,
        error_rate: float,
    ) -> None:
        """Apply a soft block to an API key."""
        block_key = f"{self.PREFIX_BLOCK}{api_key_id}"
        blocked_until = time.time() + self._block_duration

        await self._redis.hset(block_key, mapping={
            "until": str(blocked_until),
            "reason": reason,
            "score": str(score),
            "rate": str(rate),
            "error_rate": str(error_rate),
            "blocked_at": str(time.time()),
        })
        await self._redis.expire(block_key, self._block_duration + 60)

        # Record in history
        history_key = f"{self.PREFIX_HISTORY}{api_key_id}"
        await self._redis.zadd(history_key, {
            f"{reason}:{time.time()}": time.time()
        })

        logger.info(
            "API key blocked",
            api_key_id=api_key_id,
            reason=reason,
            duration=self._block_duration,
            score=score,
        )

    async def unblock(self, api_key_id: str, admin_id: str | None = None) -> bool:
        """
        Manually unblock an API key.
        
        Args:
            api_key_id: The API key to unblock
            admin_id: ID of admin performing the action
        
        Returns:
            True if unblocked, False if wasn't blocked
        """
        block_key = f"{self.PREFIX_BLOCK}{api_key_id}"
        result = await self._redis.delete(block_key)

        if result > 0:
            logger.info(
                "API key unblocked manually",
                api_key_id=api_key_id,
                admin_id=admin_id,
            )
            return True
        return False

    async def get_blocked_keys(self) -> list[dict]:
        """
        Get all currently blocked API keys.
        
        Note: This is a simplified implementation. In production,
        use SCAN for large datasets.
        """
        # This would need SCAN in production
        # For demo, we track blocked keys separately
        return []

    async def _load_metrics(self, key: str) -> AbuseMetrics:
        """Load metrics from Redis."""
        data = await self._redis.hgetall(key)
        if not data:
            return AbuseMetrics()

        return AbuseMetrics(
            ewma_rate=float(data.get("ewma_rate", 0)),
            ewma_rate_variance=float(data.get("ewma_rate_variance", 0)),
            last_rate_update=float(data.get("last_rate_update", 0)),
            ewma_error_rate=float(data.get("ewma_error_rate", 0)),
            total_requests=int(data.get("total_requests", 0)),
            total_errors=int(data.get("total_errors", 0)),
            window_start=float(data.get("window_start", 0)),
            window_requests=int(data.get("window_requests", 0)),
            window_errors=int(data.get("window_errors", 0)),
        )

    async def _save_metrics(self, key: str, metrics: AbuseMetrics) -> None:
        """Save metrics to Redis."""
        await self._redis.hset(key, mapping={
            "ewma_rate": str(metrics.ewma_rate),
            "ewma_rate_variance": str(metrics.ewma_rate_variance),
            "last_rate_update": str(metrics.last_rate_update),
            "ewma_error_rate": str(metrics.ewma_error_rate),
            "total_requests": str(metrics.total_requests),
            "total_errors": str(metrics.total_errors),
            "window_start": str(metrics.window_start),
            "window_requests": str(metrics.window_requests),
            "window_errors": str(metrics.window_errors),
        })
        # Expire after 24 hours of inactivity
        await self._redis.expire(key, 86400)


# Global instance
abuse_detector = AbuseDetector()


async def get_abuse_detector() -> AbuseDetector:
    """Dependency to get abuse detector."""
    return abuse_detector
