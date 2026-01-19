"""
Advanced algorithms for API Gateway operations.

This module provides production-grade implementations of:
1. Leaky Bucket Rate Limiter - Smooth traffic shaping
2. Circuit Breaker - Upstream service protection
3. Adaptive Rate Limiter - Dynamic limit adjustment
4. Count-Min Sketch - Approximate frequency counting
5. Consistent Hashing - Distributed key routing
6. Priority Queue - Request prioritization
7. Exponential Backoff - Retry strategies
8. HyperLogLog - Cardinality estimation
"""

import asyncio
import hashlib
import math
import random
import time
from abc import ABC, abstractmethod
from bisect import bisect_left
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Generic, TypeVar

import structlog

from src.services.redis_client import RedisClient, redis_client

logger = structlog.get_logger(__name__)

T = TypeVar("T")


# =============================================================================
# LEAKY BUCKET RATE LIMITER
# =============================================================================


@dataclass
class LeakyBucketResult:
    """Result of a leaky bucket rate limit check."""
    allowed: bool
    queue_position: int
    wait_time_seconds: float
    bucket_level: float


class LeakyBucketRateLimiter:
    """
    Leaky Bucket Rate Limiter.
    
    Unlike Token Bucket which allows bursts, Leaky Bucket enforces a strict
    output rate by queuing requests and processing them at a constant rate.
    
    Visualization:
    ```
        ┌─────────────┐
        │   Requests  │  ← Incoming requests fill the bucket
        │     ↓↓↓     │
        │  ┌───────┐  │
        │  │///////│  │  ← Bucket with limited capacity
        │  │///////│  │
        │  └───┬───┘  │
        │      │      │
        │      ↓      │  ← Leak rate (constant output)
        │   Output    │
        └─────────────┘
    ```
    
    Use cases:
    - Smoothing bursty traffic
    - Enforcing strict rate limits
    - Network traffic shaping
    """
    
    LEAKY_BUCKET_SCRIPT = """
    local key = KEYS[1]
    local rate = tonumber(ARGV[1])       -- leak rate (requests/second)
    local capacity = tonumber(ARGV[2])   -- bucket capacity
    local now = tonumber(ARGV[3])        -- current timestamp
    
    -- Get current bucket state
    local bucket = redis.call('HMGET', key, 'level', 'last_leak')
    local level = tonumber(bucket[1]) or 0
    local last_leak = tonumber(bucket[2]) or now
    
    -- Calculate leaked amount since last check
    local elapsed = now - last_leak
    local leaked = elapsed * rate
    level = math.max(0, level - leaked)
    
    -- Try to add request to bucket
    local allowed = 0
    local wait_time = 0
    
    if level < capacity then
        level = level + 1
        allowed = 1
    else
        -- Bucket full - calculate wait time
        wait_time = (level - capacity + 1) / rate
    end
    
    -- Update bucket state
    redis.call('HMSET', key, 'level', level, 'last_leak', now)
    redis.call('EXPIRE', key, math.ceil(capacity / rate) + 60)
    
    return {allowed, level, wait_time}
    """

    def __init__(self, redis: RedisClient | None = None) -> None:
        self._redis = redis or redis_client
        self._prefix = "ratelimit:lb:"

    async def is_allowed(
        self,
        key: str,
        rate: float,
        capacity: int,
    ) -> LeakyBucketResult:
        """
        Check if a request is allowed under leaky bucket.
        
        Args:
            key: Unique identifier
            rate: Leak rate (requests/second)
            capacity: Maximum bucket size
        
        Returns:
            LeakyBucketResult with decision and metadata
        """
        full_key = f"{self._prefix}{key}"
        now = time.time()

        try:
            result = await self._redis.eval(
                self.LEAKY_BUCKET_SCRIPT,
                keys=[full_key],
                args=[rate, capacity, now],
            )
            allowed, level, wait_time = result
            return LeakyBucketResult(
                allowed=bool(allowed),
                queue_position=int(level),
                wait_time_seconds=float(wait_time),
                bucket_level=float(level),
            )
        except NotImplementedError:
            # Fallback for demo mode
            return await self._is_allowed_fallback(full_key, rate, capacity, now)

    async def _is_allowed_fallback(
        self,
        key: str,
        rate: float,
        capacity: int,
        now: float,
    ) -> LeakyBucketResult:
        """Non-atomic fallback implementation."""
        data = await self._redis.hgetall(key)
        level = float(data.get("level", 0))
        last_leak = float(data.get("last_leak", now))

        # Leak
        elapsed = now - last_leak
        level = max(0, level - elapsed * rate)

        # Check capacity
        allowed = level < capacity
        wait_time = 0.0
        if allowed:
            level += 1
        else:
            wait_time = (level - capacity + 1) / rate

        await self._redis.hset(key, mapping={
            "level": str(level),
            "last_leak": str(now),
        })

        return LeakyBucketResult(
            allowed=allowed,
            queue_position=int(level),
            wait_time_seconds=wait_time,
            bucket_level=level,
        )


# =============================================================================
# CIRCUIT BREAKER
# =============================================================================


class CircuitState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5      # Failures before opening
    success_threshold: int = 3      # Successes to close from half-open
    timeout_seconds: float = 30.0   # Time in open state before half-open
    half_open_max_calls: int = 3    # Max calls allowed in half-open


@dataclass
class CircuitBreakerStats:
    """Statistics for a circuit breaker."""
    state: CircuitState
    failure_count: int
    success_count: int
    last_failure_time: float | None
    last_state_change: float
    total_failures: int
    total_successes: int


class CircuitBreaker:
    """
    Circuit Breaker pattern for upstream service protection.
    
    Prevents cascading failures by temporarily blocking requests to a
    failing service, allowing it time to recover.
    
    State Machine:
    ```
        ┌──────────────────────────────────────────────────┐
        │                                                   │
        ▼                                                   │
    ┌────────┐  failure_threshold   ┌────────┐  timeout   │
    │ CLOSED │ ─────────────────→  │  OPEN  │ ──────────┤
    └────────┘                      └────────┘            │
        ▲                               │                  │
        │                               ▼                  │
        │  success_threshold     ┌───────────┐            │
        └─────────────────────── │ HALF_OPEN │ ───────────┘
                                 └───────────┘   failure
    ```
    
    Use cases:
    - Protecting against slow/failing upstream services
    - Preventing resource exhaustion
    - Graceful degradation
    """

    def __init__(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
        redis: RedisClient | None = None,
    ) -> None:
        self._name = name
        self._config = config or CircuitBreakerConfig()
        self._redis = redis or redis_client
        self._prefix = "circuit:"

    def _key(self, suffix: str) -> str:
        return f"{self._prefix}{self._name}:{suffix}"

    async def get_state(self) -> CircuitState:
        """Get current circuit state."""
        data = await self._redis.hgetall(self._key("state"))
        if not data:
            return CircuitState.CLOSED

        state = data.get("state", "closed")
        last_change = float(data.get("last_change", 0))

        # Check if open circuit should transition to half-open
        if state == CircuitState.OPEN:
            if time.time() - last_change >= self._config.timeout_seconds:
                await self._set_state(CircuitState.HALF_OPEN)
                return CircuitState.HALF_OPEN

        return CircuitState(state)

    async def _set_state(self, state: CircuitState) -> None:
        """Set circuit state."""
        await self._redis.hset(self._key("state"), mapping={
            "state": state.value,
            "last_change": str(time.time()),
        })
        await self._redis.expire(self._key("state"), 86400)
        logger.info(
            "Circuit breaker state changed",
            name=self._name,
            state=state.value,
        )

    async def can_execute(self) -> bool:
        """
        Check if a request can be executed.
        
        Returns:
            True if request is allowed, False if circuit is open
        """
        state = await self.get_state()

        if state == CircuitState.CLOSED:
            return True

        if state == CircuitState.OPEN:
            return False

        # Half-open: allow limited requests
        calls = int(await self._redis.get(self._key("half_open_calls")) or 0)
        if calls < self._config.half_open_max_calls:
            await self._redis.incr(self._key("half_open_calls"))
            return True

        return False

    async def record_success(self) -> None:
        """Record a successful request."""
        state = await self.get_state()

        # Increment success counter
        await self._redis.incr(self._key("total_success"))

        if state == CircuitState.HALF_OPEN:
            successes = await self._redis.incr(self._key("success_count"))
            if successes >= self._config.success_threshold:
                await self._set_state(CircuitState.CLOSED)
                await self._redis.delete(self._key("failure_count"))
                await self._redis.delete(self._key("success_count"))
                await self._redis.delete(self._key("half_open_calls"))

        elif state == CircuitState.CLOSED:
            # Reset failure count on success
            await self._redis.delete(self._key("failure_count"))

    async def record_failure(self) -> None:
        """Record a failed request."""
        state = await self.get_state()

        # Increment failure counter
        await self._redis.incr(self._key("total_failure"))
        await self._redis.hset(self._key("state"), mapping={
            "last_failure": str(time.time()),
        })

        if state == CircuitState.HALF_OPEN:
            # Any failure in half-open goes back to open
            await self._set_state(CircuitState.OPEN)
            await self._redis.delete(self._key("success_count"))
            await self._redis.delete(self._key("half_open_calls"))

        elif state == CircuitState.CLOSED:
            failures = await self._redis.incr(self._key("failure_count"))
            if failures >= self._config.failure_threshold:
                await self._set_state(CircuitState.OPEN)

    async def get_stats(self) -> CircuitBreakerStats:
        """Get circuit breaker statistics."""
        state_data = await self._redis.hgetall(self._key("state"))
        return CircuitBreakerStats(
            state=await self.get_state(),
            failure_count=int(await self._redis.get(self._key("failure_count")) or 0),
            success_count=int(await self._redis.get(self._key("success_count")) or 0),
            last_failure_time=float(state_data.get("last_failure", 0)) or None,
            last_state_change=float(state_data.get("last_change", 0)),
            total_failures=int(await self._redis.get(self._key("total_failure")) or 0),
            total_successes=int(await self._redis.get(self._key("total_success")) or 0),
        )

    async def reset(self) -> None:
        """Reset circuit breaker to closed state."""
        await self._set_state(CircuitState.CLOSED)
        for suffix in ["failure_count", "success_count", "half_open_calls"]:
            await self._redis.delete(self._key(suffix))


class CircuitBreakerManager:
    """Manages multiple circuit breakers for different upstreams."""

    def __init__(self, redis: RedisClient | None = None) -> None:
        self._redis = redis or redis_client
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(
        self,
        name: str,
        config: CircuitBreakerConfig | None = None,
    ) -> CircuitBreaker:
        """Get or create a circuit breaker for a service."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                config=config,
                redis=self._redis,
            )
        return self._breakers[name]


# =============================================================================
# ADAPTIVE RATE LIMITER
# =============================================================================


@dataclass
class SystemLoad:
    """Current system load metrics."""
    cpu_usage: float = 0.0      # 0-1
    memory_usage: float = 0.0   # 0-1
    request_latency_p99: float = 0.0  # milliseconds
    error_rate: float = 0.0     # 0-1
    queue_depth: int = 0


class AdaptiveRateLimiter:
    """
    Adaptive Rate Limiter that adjusts limits based on system load.
    
    Uses a feedback loop to dynamically increase or decrease rate limits
    based on system health metrics.
    
    Algorithm:
    ```
    new_limit = base_limit * multiplier
    
    where multiplier = f(cpu, memory, latency, errors)
    
    If system is healthy: multiplier > 1 (increase limits)
    If system is stressed: multiplier < 1 (decrease limits)
    ```
    
    Use cases:
    - Auto-scaling rate limits
    - Protecting system during traffic spikes
    - Maximizing throughput while maintaining SLOs
    """

    def __init__(
        self,
        base_rate: float = 100.0,
        min_rate: float = 10.0,
        max_rate: float = 1000.0,
        adjustment_interval: float = 10.0,
        redis: RedisClient | None = None,
    ) -> None:
        """
        Initialize adaptive rate limiter.
        
        Args:
            base_rate: Starting rate limit (requests/second)
            min_rate: Minimum allowed rate
            max_rate: Maximum allowed rate
            adjustment_interval: How often to adjust (seconds)
        """
        self._base_rate = base_rate
        self._min_rate = min_rate
        self._max_rate = max_rate
        self._interval = adjustment_interval
        self._redis = redis or redis_client
        self._prefix = "adaptive:"

        # Thresholds for adjustment
        self._cpu_threshold = 0.8
        self._memory_threshold = 0.85
        self._latency_threshold = 500  # ms
        self._error_threshold = 0.05

    async def get_current_rate(self, key: str) -> float:
        """Get the current adaptive rate limit."""
        rate = await self._redis.get(f"{self._prefix}rate:{key}")
        return float(rate) if rate else self._base_rate

    async def update_rate(self, key: str, load: SystemLoad) -> float:
        """
        Update rate limit based on system load.
        
        Args:
            key: Rate limit key
            load: Current system load metrics
        
        Returns:
            New rate limit
        """
        current_rate = await self.get_current_rate(key)

        # Calculate multiplier based on each metric
        multiplier = 1.0

        # CPU factor
        if load.cpu_usage > self._cpu_threshold:
            cpu_factor = 1 - (load.cpu_usage - self._cpu_threshold) / (1 - self._cpu_threshold)
            multiplier *= max(0.5, cpu_factor)
        elif load.cpu_usage < self._cpu_threshold * 0.5:
            multiplier *= 1.1  # Increase if CPU is low

        # Memory factor
        if load.memory_usage > self._memory_threshold:
            mem_factor = 1 - (load.memory_usage - self._memory_threshold) / (1 - self._memory_threshold)
            multiplier *= max(0.5, mem_factor)

        # Latency factor
        if load.request_latency_p99 > self._latency_threshold:
            latency_factor = self._latency_threshold / load.request_latency_p99
            multiplier *= max(0.5, latency_factor)
        elif load.request_latency_p99 < self._latency_threshold * 0.5:
            multiplier *= 1.05

        # Error rate factor
        if load.error_rate > self._error_threshold:
            error_factor = 1 - (load.error_rate - self._error_threshold) * 10
            multiplier *= max(0.3, error_factor)

        # Apply EWMA smoothing to avoid oscillation
        alpha = 0.3
        new_rate = alpha * (current_rate * multiplier) + (1 - alpha) * current_rate

        # Clamp to bounds
        new_rate = max(self._min_rate, min(self._max_rate, new_rate))

        # Store new rate
        await self._redis.set(
            f"{self._prefix}rate:{key}",
            str(new_rate),
            ex=int(self._interval * 10),
        )

        logger.debug(
            "Adaptive rate updated",
            key=key,
            old_rate=current_rate,
            new_rate=new_rate,
            multiplier=multiplier,
        )

        return new_rate

    async def record_metrics(
        self,
        key: str,
        latency_ms: float,
        is_error: bool,
    ) -> None:
        """Record request metrics for adaptive adjustment."""
        pipe = await self._redis.pipeline()

        # Update latency histogram (simplified)
        pipe.lpush(f"{self._prefix}latency:{key}", latency_ms)
        pipe.ltrim(f"{self._prefix}latency:{key}", 0, 999)

        # Update error counter
        if is_error:
            pipe.incr(f"{self._prefix}errors:{key}")
        pipe.incr(f"{self._prefix}requests:{key}")

        await pipe.execute()


# =============================================================================
# COUNT-MIN SKETCH
# =============================================================================


class CountMinSketch:
    """
    Count-Min Sketch for approximate frequency counting.
    
    A probabilistic data structure that uses sub-linear space to track
    approximate frequencies of items. Useful for detecting heavy hitters
    (most frequent items) in streaming data.
    
    Structure:
    ```
    d rows (hash functions)
    w columns (counters)
    
        0   1   2   3   4   5   ... w-1
    0 [ 3 | 1 | 7 | 0 | 2 | 4 | ... ]
    1 [ 1 | 5 | 2 | 3 | 1 | 0 | ... ]
    2 [ 2 | 0 | 4 | 1 | 6 | 2 | ... ]
    ...
    d-1 [ ... ]
    
    To add item x:
      For each row i: increment counter at position hash_i(x)
    
    To query item x:
      Return min(counter[i][hash_i(x)] for all i)
    ```
    
    Properties:
    - Never underestimates count
    - May overestimate due to collisions
    - Error bounded by ε with probability 1-δ
    
    Use cases:
    - Finding heavy hitters (top talkers)
    - Detecting DDoS attacks
    - Traffic analysis
    - Trending items detection
    """

    def __init__(
        self,
        width: int = 1000,
        depth: int = 5,
        redis: RedisClient | None = None,
        name: str = "cms:default",
    ) -> None:
        """
        Initialize Count-Min Sketch.
        
        Args:
            width: Number of columns (w). Error ε ≈ e/w
            depth: Number of rows/hash functions (d). Probability δ ≈ e^(-d)
            redis: Redis client
            name: Key prefix for Redis storage
        """
        self._width = width
        self._depth = depth
        self._redis = redis or redis_client
        self._name = name

    def _get_positions(self, item: str) -> list[tuple[int, int]]:
        """Get (row, column) positions for an item."""
        positions = []
        for i in range(self._depth):
            # Use different seeds for each hash function
            h = int(hashlib.md5(f"{i}:{item}".encode()).hexdigest(), 16)
            col = h % self._width
            positions.append((i, col))
        return positions

    def _key(self, row: int) -> str:
        return f"{self._name}:row:{row}"

    async def add(self, item: str, count: int = 1) -> int:
        """
        Add an item to the sketch.
        
        Args:
            item: The item to add
            count: Number of occurrences to add
        
        Returns:
            Estimated count after adding
        """
        positions = self._get_positions(item)
        min_count = float("inf")

        for row, col in positions:
            new_val = await self._redis.hincrby(self._key(row), str(col), count)
            min_count = min(min_count, new_val)

        return int(min_count)

    async def query(self, item: str) -> int:
        """
        Query the approximate count of an item.
        
        Args:
            item: The item to query
        
        Returns:
            Estimated count (may be overestimate, never underestimate)
        """
        positions = self._get_positions(item)
        min_count = float("inf")

        for row, col in positions:
            val = await self._redis.hget(self._key(row), str(col))
            count = int(val) if val else 0
            min_count = min(min_count, count)

        return int(min_count) if min_count != float("inf") else 0

    async def get_heavy_hitters(
        self,
        candidates: list[str],
        threshold: int,
    ) -> list[tuple[str, int]]:
        """
        Find items with count >= threshold from a list of candidates.
        
        Note: CMS doesn't support iteration, so candidates must be provided.
        
        Args:
            candidates: Items to check
            threshold: Minimum count to be considered heavy hitter
        
        Returns:
            List of (item, count) tuples above threshold
        """
        results = []
        for item in candidates:
            count = await self.query(item)
            if count >= threshold:
                results.append((item, count))
        return sorted(results, key=lambda x: x[1], reverse=True)

    async def clear(self) -> None:
        """Clear the sketch."""
        for row in range(self._depth):
            await self._redis.delete(self._key(row))

    def get_error_bounds(self) -> dict[str, float]:
        """Get theoretical error bounds."""
        import math
        epsilon = math.e / self._width      # Error factor
        delta = math.exp(-self._depth)       # Failure probability
        return {
            "epsilon": epsilon,
            "delta": delta,
            "width": self._width,
            "depth": self._depth,
        }


# =============================================================================
# CONSISTENT HASHING
# =============================================================================


class ConsistentHash:
    """
    Consistent Hashing for distributed key routing.
    
    Maps keys to nodes in a way that minimizes remapping when nodes
    are added or removed. Uses virtual nodes for better distribution.
    
    Hash Ring:
    ```
              0°
              │
         ┌────┼────┐
        /     │     \
       /   ●  │      \        ● = Physical Node
      /       │   ○   \       ○ = Virtual Node
    90°───────┼───────270°
      \    ○  │      /
       \      │  ●  /
        \     │    /
         └────┼───┘
             180°
    ```
    
    When a key is hashed, it's assigned to the next node clockwise.
    Virtual nodes ensure even distribution across physical nodes.
    
    Use cases:
    - Distributed caching (sharding)
    - Load balancing
    - Service discovery
    - Database partitioning
    """

    def __init__(
        self,
        nodes: list[str] | None = None,
        virtual_nodes: int = 150,
    ) -> None:
        """
        Initialize consistent hash ring.
        
        Args:
            nodes: Initial list of node identifiers
            virtual_nodes: Number of virtual nodes per physical node
        """
        self._virtual_nodes = virtual_nodes
        self._ring: dict[int, str] = {}
        self._sorted_keys: list[int] = []
        self._nodes: set[str] = set()

        if nodes:
            for node in nodes:
                self.add_node(node)

    def _hash(self, key: str) -> int:
        """Hash a key to a position on the ring."""
        return int(hashlib.md5(key.encode()).hexdigest(), 16)

    def add_node(self, node: str) -> None:
        """Add a node to the ring with virtual nodes."""
        if node in self._nodes:
            return

        self._nodes.add(node)

        for i in range(self._virtual_nodes):
            virtual_key = f"{node}:vn{i}"
            hash_val = self._hash(virtual_key)
            self._ring[hash_val] = node
            self._sorted_keys.append(hash_val)

        self._sorted_keys.sort()
        logger.info(
            "Node added to consistent hash ring",
            node=node,
            total_nodes=len(self._nodes),
        )

    def remove_node(self, node: str) -> None:
        """Remove a node and its virtual nodes from the ring."""
        if node not in self._nodes:
            return

        self._nodes.discard(node)

        for i in range(self._virtual_nodes):
            virtual_key = f"{node}:vn{i}"
            hash_val = self._hash(virtual_key)
            if hash_val in self._ring:
                del self._ring[hash_val]
                self._sorted_keys.remove(hash_val)

        logger.info(
            "Node removed from consistent hash ring",
            node=node,
            total_nodes=len(self._nodes),
        )

    def get_node(self, key: str) -> str | None:
        """
        Get the node responsible for a key.
        
        Args:
            key: The key to look up
        
        Returns:
            Node identifier or None if ring is empty
        """
        if not self._ring:
            return None

        hash_val = self._hash(key)

        # Binary search for the first node with hash >= key hash
        idx = bisect_left(self._sorted_keys, hash_val)

        # Wrap around if necessary
        if idx >= len(self._sorted_keys):
            idx = 0

        return self._ring[self._sorted_keys[idx]]

    def get_nodes(self, key: str, count: int = 1) -> list[str]:
        """
        Get multiple nodes for a key (for replication).
        
        Args:
            key: The key to look up
            count: Number of nodes to return
        
        Returns:
            List of unique node identifiers
        """
        if not self._ring:
            return []

        hash_val = self._hash(key)
        idx = bisect_left(self._sorted_keys, hash_val)

        nodes = []
        seen = set()

        for _ in range(len(self._sorted_keys)):
            if len(nodes) >= count:
                break

            if idx >= len(self._sorted_keys):
                idx = 0

            node = self._ring[self._sorted_keys[idx]]
            if node not in seen:
                nodes.append(node)
                seen.add(node)

            idx += 1

        return nodes

    def get_distribution(self) -> dict[str, int]:
        """Get the distribution of virtual nodes per physical node."""
        distribution: dict[str, int] = {}
        for node in self._ring.values():
            distribution[node] = distribution.get(node, 0) + 1
        return distribution


# =============================================================================
# EXPONENTIAL BACKOFF
# =============================================================================


@dataclass
class BackoffResult:
    """Result of backoff calculation."""
    should_retry: bool
    delay_seconds: float
    attempt_number: int
    max_attempts: int


class ExponentialBackoff:
    """
    Exponential Backoff with jitter for retry strategies.
    
    Implements the "Full Jitter" algorithm recommended by AWS:
    delay = random(0, min(cap, base * 2^attempt))
    
    Benefits of jitter:
    - Spreads out retries to avoid thundering herd
    - Reduces correlation between client retries
    
    Backoff progression (without jitter):
    ```
    Attempt 1: 1s
    Attempt 2: 2s
    Attempt 3: 4s
    Attempt 4: 8s
    Attempt 5: 16s (capped at max_delay)
    ```
    
    Use cases:
    - Retrying failed API calls
    - Reconnection logic
    - Rate limit recovery
    - Distributed system resilience
    """

    def __init__(
        self,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        max_attempts: int = 5,
        jitter: bool = True,
    ) -> None:
        """
        Initialize exponential backoff.
        
        Args:
            base_delay: Initial delay in seconds
            max_delay: Maximum delay cap
            max_attempts: Maximum retry attempts
            jitter: Whether to add random jitter
        """
        self._base = base_delay
        self._max = max_delay
        self._max_attempts = max_attempts
        self._jitter = jitter

    def get_delay(self, attempt: int) -> BackoffResult:
        """
        Calculate the delay for a given attempt.
        
        Args:
            attempt: Current attempt number (1-based)
        
        Returns:
            BackoffResult with delay and metadata
        """
        should_retry = attempt < self._max_attempts

        if not should_retry:
            return BackoffResult(
                should_retry=False,
                delay_seconds=0,
                attempt_number=attempt,
                max_attempts=self._max_attempts,
            )

        # Calculate exponential delay
        exp_delay = self._base * (2 ** (attempt - 1))
        capped_delay = min(self._max, exp_delay)

        # Apply jitter
        if self._jitter:
            delay = random.uniform(0, capped_delay)
        else:
            delay = capped_delay

        return BackoffResult(
            should_retry=True,
            delay_seconds=delay,
            attempt_number=attempt,
            max_attempts=self._max_attempts,
        )

    async def execute_with_retry(
        self,
        func: Callable[[], Any],
        retryable_exceptions: tuple = (Exception,),
    ) -> Any:
        """
        Execute a function with exponential backoff retry.
        
        Args:
            func: Async function to execute
            retryable_exceptions: Exceptions that trigger retry
        
        Returns:
            Result of the function
        
        Raises:
            Last exception if all retries exhausted
        """
        last_exception = None

        for attempt in range(1, self._max_attempts + 1):
            try:
                return await func()
            except retryable_exceptions as e:
                last_exception = e
                result = self.get_delay(attempt)

                if not result.should_retry:
                    break

                logger.warning(
                    "Retrying after failure",
                    attempt=attempt,
                    delay=result.delay_seconds,
                    error=str(e),
                )
                await asyncio.sleep(result.delay_seconds)

        raise last_exception  # type: ignore


# =============================================================================
# HYPERLOGLOG (Cardinality Estimation)
# =============================================================================


class HyperLogLog:
    """
    HyperLogLog for cardinality estimation.
    
    Estimates the number of unique items in a set using sub-linear space.
    Uses Redis's built-in HyperLogLog implementation.
    
    Properties:
    - Space: O(log log n) - ~12KB for billions of items
    - Error: ~0.81% standard error
    - Operations: O(1) add and count
    
    Algorithm intuition:
    ```
    1. Hash each item to a binary string
    2. Count leading zeros in the hash
    3. Track maximum leading zeros seen
    4. Estimate: 2^(max_zeros) ≈ number of unique items
    
    Example:
    hash("a") = 0001... → 3 leading zeros
    hash("b") = 1000... → 0 leading zeros
    hash("c") = 0000001... → 6 leading zeros
    
    max = 6 → estimate ≈ 2^6 = 64 unique items
    ```
    
    Use cases:
    - Counting unique visitors
    - Unique API keys per day
    - Distinct query counting
    - Cardinality monitoring
    """

    def __init__(
        self,
        name: str = "hll:default",
        redis: RedisClient | None = None,
    ) -> None:
        self._name = name
        self._redis = redis or redis_client

    async def add(self, *items: str) -> int:
        """
        Add items to the HyperLogLog.
        
        Args:
            items: Items to add
        
        Returns:
            1 if cardinality changed, 0 otherwise
        """
        if not items:
            return 0
        return await self._redis.pfadd(self._name, *items)

    async def count(self) -> int:
        """
        Get estimated cardinality.
        
        Returns:
            Approximate number of unique items
        """
        return await self._redis.pfcount(self._name)

    async def merge(self, *other_names: str) -> None:
        """
        Merge other HyperLogLogs into this one.
        
        Args:
            other_names: Names of other HLLs to merge
        """
        await self._redis.pfmerge(self._name, self._name, *other_names)

    async def clear(self) -> None:
        """Clear the HyperLogLog."""
        await self._redis.delete(self._name)


# =============================================================================
# PRIORITY QUEUE
# =============================================================================


@dataclass
class PriorityItem(Generic[T]):
    """An item in the priority queue."""
    priority: float
    data: T
    timestamp: float = field(default_factory=time.time)


class PriorityQueue(Generic[T]):
    """
    Redis-backed Priority Queue for request prioritization.
    
    Uses Redis sorted sets where score = priority.
    Higher scores = higher priority (processed first).
    
    Use cases:
    - Premium tier request handling
    - Job scheduling by urgency
    - Rate limit queue processing
    - Fair queuing with priorities
    """

    def __init__(
        self,
        name: str = "pq:default",
        redis: RedisClient | None = None,
    ) -> None:
        self._name = name
        self._redis = redis or redis_client

    async def push(
        self,
        item_id: str,
        priority: float,
        data: str | None = None,
    ) -> bool:
        """
        Add an item to the queue.
        
        Args:
            item_id: Unique identifier for the item
            priority: Priority score (higher = more urgent)
            data: Optional data to store
        
        Returns:
            True if added, False if updated existing
        """
        # Store data separately if provided
        if data:
            await self._redis.hset(f"{self._name}:data", item_id, data)

        # Add to sorted set with priority as score
        result = await self._redis.zadd(
            self._name,
            {item_id: priority},
            nx=True,  # Only add if not exists
        )
        return result == 1

    async def pop(self) -> tuple[str, float] | None:
        """
        Remove and return the highest priority item.
        
        Returns:
            Tuple of (item_id, priority) or None if empty
        """
        # Get and remove the highest scored item
        result = await self._redis.zpopmax(self._name)
        if not result:
            return None

        item_id, priority = result[0]
        # Clean up data
        await self._redis.hdel(f"{self._name}:data", item_id)
        return item_id, priority

    async def peek(self) -> tuple[str, float] | None:
        """
        Return the highest priority item without removing it.
        
        Returns:
            Tuple of (item_id, priority) or None if empty
        """
        result = await self._redis.zrange(
            self._name, -1, -1, withscores=True
        )
        if not result:
            return None
        return result[0]

    async def get_data(self, item_id: str) -> str | None:
        """Get the data associated with an item."""
        return await self._redis.hget(f"{self._name}:data", item_id)

    async def size(self) -> int:
        """Get the number of items in the queue."""
        return await self._redis.zcard(self._name)

    async def clear(self) -> None:
        """Clear the queue."""
        await self._redis.delete(self._name)
        await self._redis.delete(f"{self._name}:data")


# =============================================================================
# GLOBAL INSTANCES
# =============================================================================

leaky_bucket = LeakyBucketRateLimiter()
circuit_breaker_manager = CircuitBreakerManager()
adaptive_rate_limiter = AdaptiveRateLimiter()


async def get_leaky_bucket() -> LeakyBucketRateLimiter:
    """Dependency to get leaky bucket rate limiter."""
    return leaky_bucket


async def get_circuit_breaker(name: str) -> CircuitBreaker:
    """Dependency to get a circuit breaker by name."""
    return circuit_breaker_manager.get(name)


async def get_adaptive_rate_limiter() -> AdaptiveRateLimiter:
    """Dependency to get adaptive rate limiter."""
    return adaptive_rate_limiter
