"""
Rate limiting implementations using Redis.

Provides two algorithms:
1. Token Bucket: Allows bursts up to bucket capacity
2. Sliding Window Log: Precise rate limiting with request timestamps

Both support per-key, per-route rate limits with Redis persistence.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import structlog

from src.services.redis_client import RedisClient, redis_client

logger = structlog.get_logger(__name__)


@dataclass
class RateLimitResult:
    """Result of a rate limit check."""

    allowed: bool
    remaining: int
    reset_after_seconds: float
    limit: int
    retry_after: float | None = None  # For 429 responses


class RateLimiter(ABC):
    """Abstract base class for rate limiters."""

    @abstractmethod
    async def is_allowed(
        self,
        key: str,
        rate: float,
        capacity: int,
    ) -> RateLimitResult:
        """
        Check if a request is allowed under rate limit.
        
        Args:
            key: Unique identifier (e.g., "apikey:route")
            rate: Requests per second allowed
            capacity: Maximum burst capacity
        
        Returns:
            RateLimitResult with decision and metadata
        """
        pass

    @abstractmethod
    async def get_usage(self, key: str) -> dict[str, float]:
        """Get current usage statistics for a key."""
        pass

    @abstractmethod
    async def reset(self, key: str) -> bool:
        """Reset rate limit for a key."""
        pass


class TokenBucketRateLimiter(RateLimiter):
    """
    Token Bucket rate limiter.
    
    Tokens are added at a fixed rate up to a maximum capacity.
    Each request consumes one token. Allows bursts up to capacity.
    
    Pros:
    - Allows controlled bursting
    - Smooth rate limiting over time
    - Efficient Redis operations
    
    Cons:
    - May allow temporary rate spikes
    """

    # Lua script for atomic token bucket operation
    TOKEN_BUCKET_SCRIPT = """
    local key = KEYS[1]
    local rate = tonumber(ARGV[1])
    local capacity = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])
    local requested = tonumber(ARGV[4])
    
    -- Get current bucket state
    local bucket = redis.call('HMGET', key, 'tokens', 'last_update')
    local tokens = tonumber(bucket[1])
    local last_update = tonumber(bucket[2])
    
    -- Initialize if new
    if tokens == nil then
        tokens = capacity
        last_update = now
    end
    
    -- Add tokens based on time elapsed
    local elapsed = now - last_update
    local new_tokens = elapsed * rate
    tokens = math.min(capacity, tokens + new_tokens)
    
    -- Check if request is allowed
    local allowed = 0
    local remaining = tokens
    
    if tokens >= requested then
        tokens = tokens - requested
        remaining = tokens
        allowed = 1
    end
    
    -- Update bucket
    redis.call('HMSET', key, 'tokens', tokens, 'last_update', now)
    redis.call('EXPIRE', key, math.ceil(capacity / rate) + 60)
    
    -- Calculate time until next token
    local wait_time = 0
    if allowed == 0 then
        wait_time = (requested - tokens) / rate
    end
    
    return {allowed, math.floor(remaining), wait_time, math.ceil(capacity / rate)}
    """

    def __init__(self, redis: RedisClient | None = None) -> None:
        self._redis = redis or redis_client
        self._prefix = "ratelimit:tb:"

    async def is_allowed(
        self,
        key: str,
        rate: float,
        capacity: int,
    ) -> RateLimitResult:
        """Check if request is allowed using token bucket algorithm."""
        full_key = f"{self._prefix}{key}"
        now = time.time()

        try:
            # Try Lua script first (atomic and efficient)
            result = await self._redis.eval(
                self.TOKEN_BUCKET_SCRIPT,
                keys=[full_key],
                args=[rate, capacity, now, 1],
            )
            allowed, remaining, wait_time, reset_after = result
            return RateLimitResult(
                allowed=bool(allowed),
                remaining=int(remaining),
                reset_after_seconds=float(reset_after),
                limit=capacity,
                retry_after=float(wait_time) if not allowed else None,
            )
        except NotImplementedError:
            # Fallback for demo mode (no Lua)
            return await self._is_allowed_fallback(full_key, rate, capacity, now)

    async def _is_allowed_fallback(
        self,
        key: str,
        rate: float,
        capacity: int,
        now: float,
    ) -> RateLimitResult:
        """Non-atomic fallback for demo mode."""
        data = await self._redis.hgetall(key)

        tokens = float(data.get("tokens", capacity))
        last_update = float(data.get("last_update", now))

        # Add tokens based on elapsed time
        elapsed = now - last_update
        tokens = min(capacity, tokens + elapsed * rate)

        # Check if request is allowed
        allowed = tokens >= 1
        if allowed:
            tokens -= 1

        # Update state
        await self._redis.hset(key, mapping={
            "tokens": str(tokens),
            "last_update": str(now),
        })
        await self._redis.expire(key, int(capacity / rate) + 60)

        wait_time = 0 if allowed else (1 - tokens) / rate

        return RateLimitResult(
            allowed=allowed,
            remaining=int(tokens),
            reset_after_seconds=capacity / rate,
            limit=capacity,
            retry_after=wait_time if not allowed else None,
        )

    async def get_usage(self, key: str) -> dict[str, float]:
        """Get current token bucket state."""
        full_key = f"{self._prefix}{key}"
        data = await self._redis.hgetall(full_key)
        return {
            "tokens": float(data.get("tokens", 0)),
            "last_update": float(data.get("last_update", 0)),
        }

    async def reset(self, key: str) -> bool:
        """Reset token bucket for a key."""
        full_key = f"{self._prefix}{key}"
        result = await self._redis.delete(full_key)
        return result > 0


class SlidingWindowRateLimiter(RateLimiter):
    """
    Sliding Window Log rate limiter.
    
    Tracks exact timestamps of recent requests in a sorted set.
    Provides precise rate limiting without the burst allowance of token bucket.
    
    Pros:
    - Precise rate limiting
    - No burst allowance
    - Accurate remaining count
    
    Cons:
    - Higher memory usage (stores each request timestamp)
    - More Redis operations
    """

    SLIDING_WINDOW_SCRIPT = """
    local key = KEYS[1]
    local limit = tonumber(ARGV[1])
    local window = tonumber(ARGV[2])
    local now = tonumber(ARGV[3])
    local request_id = ARGV[4]
    
    -- Remove old entries outside window
    local window_start = now - window
    redis.call('ZREMRANGEBYSCORE', key, '-inf', window_start)
    
    -- Count current requests in window
    local count = redis.call('ZCARD', key)
    
    local allowed = 0
    local remaining = limit - count
    
    if count < limit then
        -- Add new request
        redis.call('ZADD', key, now, request_id)
        remaining = remaining - 1
        allowed = 1
    end
    
    -- Set expiry on the key
    redis.call('EXPIRE', key, math.ceil(window) + 1)
    
    -- Get oldest entry for reset time calculation
    local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
    local reset_after = window
    if #oldest > 0 then
        reset_after = (tonumber(oldest[2]) + window) - now
    end
    
    return {allowed, remaining, reset_after}
    """

    def __init__(self, redis: RedisClient | None = None) -> None:
        self._redis = redis or redis_client
        self._prefix = "ratelimit:sw:"

    async def is_allowed(
        self,
        key: str,
        rate: float,
        capacity: int,
    ) -> RateLimitResult:
        """
        Check if request is allowed using sliding window.
        
        Args:
            key: Rate limit key
            rate: Requests per second (used to calculate window)
            capacity: Maximum requests in window
        """
        full_key = f"{self._prefix}{key}"
        now = time.time()
        window = capacity / rate  # Window size in seconds
        request_id = f"{now}:{id(self)}"

        try:
            result = await self._redis.eval(
                self.SLIDING_WINDOW_SCRIPT,
                keys=[full_key],
                args=[capacity, window, now, request_id],
            )
            allowed, remaining, reset_after = result
            return RateLimitResult(
                allowed=bool(allowed),
                remaining=max(0, int(remaining)),
                reset_after_seconds=float(reset_after),
                limit=capacity,
                retry_after=float(reset_after) if not allowed else None,
            )
        except NotImplementedError:
            return await self._is_allowed_fallback(full_key, capacity, window, now)

    async def _is_allowed_fallback(
        self,
        key: str,
        limit: int,
        window: float,
        now: float,
    ) -> RateLimitResult:
        """Non-atomic fallback for demo mode."""
        window_start = now - window

        # Remove old entries
        await self._redis.zremrangebyscore(key, float("-inf"), window_start)

        # Count current requests
        count = await self._redis.zcount(key, "-inf", "+inf")

        allowed = count < limit
        if allowed:
            request_id = f"{now}:{id(self)}"
            await self._redis.zadd(key, {request_id: now})
            count += 1

        remaining = max(0, limit - count)
        reset_after = window  # Simplified

        return RateLimitResult(
            allowed=allowed,
            remaining=remaining,
            reset_after_seconds=reset_after,
            limit=limit,
            retry_after=reset_after if not allowed else None,
        )

    async def get_usage(self, key: str) -> dict[str, float]:
        """Get current window usage."""
        full_key = f"{self._prefix}{key}"
        count = await self._redis.zcount(full_key, "-inf", "+inf")
        return {"request_count": float(count)}

    async def reset(self, key: str) -> bool:
        """Reset sliding window for a key."""
        full_key = f"{self._prefix}{key}"
        result = await self._redis.delete(full_key)
        return result > 0


class QuotaManager:
    """
    Manages daily and monthly usage quotas.
    
    Quotas are tracked in Redis with automatic expiration.
    """

    def __init__(self, redis: RedisClient | None = None) -> None:
        self._redis = redis or redis_client
        self._prefix = "quota:"

    def _get_daily_key(self, api_key_id: str) -> str:
        """Get Redis key for daily quota."""
        from datetime import datetime

        date_str = datetime.utcnow().strftime("%Y-%m-%d")
        return f"{self._prefix}daily:{api_key_id}:{date_str}"

    def _get_monthly_key(self, api_key_id: str) -> str:
        """Get Redis key for monthly quota."""
        from datetime import datetime

        month_str = datetime.utcnow().strftime("%Y-%m")
        return f"{self._prefix}monthly:{api_key_id}:{month_str}"

    async def check_and_increment(
        self,
        api_key_id: str,
        daily_limit: int,
        monthly_limit: int,
    ) -> tuple[bool, str | None]:
        """
        Check quotas and increment if allowed.
        
        Args:
            api_key_id: The API key ID
            daily_limit: Daily request limit (0 = unlimited)
            monthly_limit: Monthly request limit (0 = unlimited)
        
        Returns:
            Tuple of (allowed, reason if not allowed)
        """
        daily_key = self._get_daily_key(api_key_id)
        monthly_key = self._get_monthly_key(api_key_id)

        # Get current usage
        daily_usage = int(await self._redis.get(daily_key) or 0)
        monthly_usage = int(await self._redis.get(monthly_key) or 0)

        # Check limits
        if daily_limit > 0 and daily_usage >= daily_limit:
            return False, "daily_quota_exceeded"

        if monthly_limit > 0 and monthly_usage >= monthly_limit:
            return False, "monthly_quota_exceeded"

        # Increment counters
        pipe = await self._redis.pipeline()
        pipe.incr(daily_key)
        pipe.incr(monthly_key)
        await pipe.execute()

        # Set expiration if new keys
        if daily_usage == 0:
            # Expire at end of day (simplified: 24 hours)
            await self._redis.expire(daily_key, 86400)
        if monthly_usage == 0:
            # Expire at end of month (simplified: 31 days)
            await self._redis.expire(monthly_key, 31 * 86400)

        return True, None

    async def get_usage(self, api_key_id: str) -> dict[str, int]:
        """Get current quota usage."""
        daily_key = self._get_daily_key(api_key_id)
        monthly_key = self._get_monthly_key(api_key_id)

        daily = int(await self._redis.get(daily_key) or 0)
        monthly = int(await self._redis.get(monthly_key) or 0)

        return {
            "daily_usage": daily,
            "monthly_usage": monthly,
        }

    async def reset_daily(self, api_key_id: str) -> bool:
        """Reset daily quota for testing."""
        daily_key = self._get_daily_key(api_key_id)
        result = await self._redis.delete(daily_key)
        return result > 0


# Metrics for rate limiting
class RateLimitMetrics:
    """Track rate limiting metrics."""

    def __init__(self) -> None:
        self.allowed = 0
        self.denied = 0
        self.quota_exceeded = 0

    def record_allowed(self) -> None:
        self.allowed += 1

    def record_denied(self) -> None:
        self.denied += 1

    def record_quota_exceeded(self) -> None:
        self.quota_exceeded += 1

    def to_dict(self) -> dict[str, int]:
        return {
            "allowed": self.allowed,
            "denied": self.denied,
            "quota_exceeded": self.quota_exceeded,
        }


# Global instances
token_bucket = TokenBucketRateLimiter()
sliding_window = SlidingWindowRateLimiter()
quota_manager = QuotaManager()
rate_limit_metrics = RateLimitMetrics()


async def get_rate_limiter(algorithm: str = "token_bucket") -> RateLimiter:
    """Get rate limiter by algorithm name."""
    if algorithm == "sliding_window":
        return sliding_window
    return token_bucket
