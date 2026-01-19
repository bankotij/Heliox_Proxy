"""
API endpoints for algorithm demonstrations and management.

Provides endpoints to view algorithm stats, test algorithms,
and manage algorithm instances.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from src.api.admin import verify_admin_key
from src.services.algorithms import (
    AdaptiveRateLimiter,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerStats,
    CircuitState,
    ConsistentHash,
    CountMinSketch,
    ExponentialBackoff,
    HyperLogLog,
    LeakyBucketRateLimiter,
    LeakyBucketResult,
    PriorityQueue,
    SystemLoad,
    circuit_breaker_manager,
    get_adaptive_rate_limiter,
    get_leaky_bucket,
)
from src.services.abuse import abuse_detector, EWMACalculator, ZScoreDetector
from src.services.bloom import bloom_filter, negative_cache
from src.services.cache import cache_service, CacheKeyBuilder
from src.services.rate_limiter import (
    quota_manager,
    sliding_window,
    token_bucket,
)

router = APIRouter(prefix="/algorithms", tags=["algorithms"])


# =============================================================================
# SCHEMAS
# =============================================================================


class RateLimitTestRequest(BaseModel):
    """Request to test a rate limiter."""
    key: str = Field(default="test-key", description="Rate limit key")
    rate: float = Field(default=10.0, description="Requests per second")
    capacity: int = Field(default=20, description="Bucket capacity")
    algorithm: str = Field(
        default="token_bucket",
        description="Algorithm: token_bucket, sliding_window, leaky_bucket",
    )


class RateLimitTestResponse(BaseModel):
    """Response from rate limit test."""
    allowed: bool
    remaining: int
    limit: int
    algorithm: str
    details: dict


class CircuitBreakerTestRequest(BaseModel):
    """Request to test circuit breaker."""
    name: str = Field(default="test-service", description="Service name")
    action: str = Field(
        default="check",
        description="Action: check, success, failure, reset",
    )


class CircuitBreakerResponse(BaseModel):
    """Circuit breaker status response."""
    name: str
    state: str
    can_execute: bool
    stats: dict


class BloomFilterTestRequest(BaseModel):
    """Request to test bloom filter."""
    action: str = Field(default="check", description="Action: add, check, stats")
    item: str = Field(default="test-item", description="Item to add/check")


class BloomFilterResponse(BaseModel):
    """Bloom filter response."""
    action: str
    item: str
    result: bool | None
    stats: dict


class CountMinSketchRequest(BaseModel):
    """Request for count-min sketch operations."""
    action: str = Field(default="query", description="Action: add, query")
    item: str = Field(default="test-item", description="Item to add/query")
    count: int = Field(default=1, description="Count to add")


class CountMinSketchResponse(BaseModel):
    """Count-min sketch response."""
    action: str
    item: str
    count: int
    error_bounds: dict


class ConsistentHashRequest(BaseModel):
    """Request for consistent hash operations."""
    action: str = Field(default="lookup", description="Action: lookup, add_node, remove_node")
    key: str = Field(default="test-key", description="Key to look up")
    node: str | None = Field(default=None, description="Node to add/remove")


class ConsistentHashResponse(BaseModel):
    """Consistent hash response."""
    action: str
    key: str | None
    node: str | None
    distribution: dict


class HyperLogLogRequest(BaseModel):
    """Request for HyperLogLog operations."""
    action: str = Field(default="count", description="Action: add, count, clear")
    items: list[str] = Field(default=[], description="Items to add")


class HyperLogLogResponse(BaseModel):
    """HyperLogLog response."""
    action: str
    count: int
    items_added: int


class EWMATestRequest(BaseModel):
    """Request to test EWMA calculation."""
    values: list[float] = Field(description="Values to process")
    alpha: float = Field(default=0.3, description="Smoothing factor (0-1)")


class EWMATestResponse(BaseModel):
    """EWMA calculation response."""
    ewma_values: list[float]
    final_ewma: float
    variance: float
    std_dev: float


class ZScoreTestRequest(BaseModel):
    """Request to test Z-score calculation."""
    value: float = Field(description="Value to check")
    mean: float = Field(description="Population mean")
    std_dev: float = Field(description="Population standard deviation")
    threshold: float = Field(default=3.0, description="Anomaly threshold")


class ZScoreTestResponse(BaseModel):
    """Z-score calculation response."""
    value: float
    z_score: float
    is_anomaly: bool
    threshold: float


class BackoffTestRequest(BaseModel):
    """Request to test exponential backoff."""
    attempt: int = Field(default=1, description="Attempt number")
    base_delay: float = Field(default=1.0, description="Base delay in seconds")
    max_delay: float = Field(default=60.0, description="Maximum delay")
    max_attempts: int = Field(default=5, description="Maximum attempts")


class BackoffTestResponse(BaseModel):
    """Exponential backoff response."""
    attempt: int
    should_retry: bool
    delay_seconds: float
    max_attempts: int
    progression: list[float]


class AlgorithmSummary(BaseModel):
    """Summary of all available algorithms."""
    rate_limiters: list[dict]
    data_structures: list[dict]
    patterns: list[dict]


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/summary", response_model=AlgorithmSummary)
async def get_algorithms_summary(
    _: str = Depends(verify_admin_key),
) -> AlgorithmSummary:
    """
    Get a summary of all available algorithms.
    
    Returns descriptions and use cases for each algorithm.
    """
    return AlgorithmSummary(
        rate_limiters=[
            {
                "name": "Token Bucket",
                "description": "Allows bursts up to bucket capacity, refills at constant rate",
                "use_cases": ["API rate limiting", "Bursty traffic"],
                "endpoint": "/algorithms/rate-limit/test",
            },
            {
                "name": "Sliding Window",
                "description": "Precise rate limiting with request timestamps",
                "use_cases": ["Strict rate enforcement", "No burst allowance"],
                "endpoint": "/algorithms/rate-limit/test",
            },
            {
                "name": "Leaky Bucket",
                "description": "Enforces strict output rate by queuing requests",
                "use_cases": ["Traffic shaping", "Smooth output"],
                "endpoint": "/algorithms/rate-limit/test",
            },
            {
                "name": "Adaptive Rate Limiter",
                "description": "Dynamically adjusts limits based on system load",
                "use_cases": ["Auto-scaling", "System protection"],
                "endpoint": "/algorithms/adaptive/status",
            },
        ],
        data_structures=[
            {
                "name": "Bloom Filter",
                "description": "Probabilistic set membership test",
                "use_cases": ["Negative caching", "404 detection"],
                "endpoint": "/algorithms/bloom/test",
            },
            {
                "name": "Count-Min Sketch",
                "description": "Approximate frequency counting",
                "use_cases": ["Heavy hitters", "Top-K detection"],
                "endpoint": "/algorithms/cms/test",
            },
            {
                "name": "HyperLogLog",
                "description": "Cardinality estimation",
                "use_cases": ["Unique visitors", "Distinct counts"],
                "endpoint": "/algorithms/hll/test",
            },
            {
                "name": "Consistent Hash",
                "description": "Distributed key routing",
                "use_cases": ["Cache sharding", "Load balancing"],
                "endpoint": "/algorithms/consistent-hash/test",
            },
        ],
        patterns=[
            {
                "name": "Circuit Breaker",
                "description": "Prevents cascading failures",
                "use_cases": ["Upstream protection", "Graceful degradation"],
                "endpoint": "/algorithms/circuit-breaker/test",
            },
            {
                "name": "EWMA",
                "description": "Exponentially weighted moving average",
                "use_cases": ["Trend detection", "Smoothing"],
                "endpoint": "/algorithms/ewma/test",
            },
            {
                "name": "Z-Score",
                "description": "Anomaly detection via standard deviations",
                "use_cases": ["Abuse detection", "Spike detection"],
                "endpoint": "/algorithms/zscore/test",
            },
            {
                "name": "Exponential Backoff",
                "description": "Retry strategy with increasing delays",
                "use_cases": ["Retry logic", "Failure recovery"],
                "endpoint": "/algorithms/backoff/test",
            },
        ],
    )


# Rate Limiting
@router.post("/rate-limit/test", response_model=RateLimitTestResponse)
async def test_rate_limiter(
    request: RateLimitTestRequest,
    _: str = Depends(verify_admin_key),
) -> RateLimitTestResponse:
    """
    Test different rate limiting algorithms.
    
    Supports: token_bucket, sliding_window, leaky_bucket
    """
    if request.algorithm == "token_bucket":
        result = await token_bucket.is_allowed(
            request.key, request.rate, request.capacity
        )
        return RateLimitTestResponse(
            allowed=result.allowed,
            remaining=result.remaining,
            limit=result.limit,
            algorithm="token_bucket",
            details={
                "reset_after_seconds": result.reset_after_seconds,
                "retry_after": result.retry_after,
            },
        )

    elif request.algorithm == "sliding_window":
        result = await sliding_window.is_allowed(
            request.key, request.rate, request.capacity
        )
        return RateLimitTestResponse(
            allowed=result.allowed,
            remaining=result.remaining,
            limit=result.limit,
            algorithm="sliding_window",
            details={
                "reset_after_seconds": result.reset_after_seconds,
                "retry_after": result.retry_after,
            },
        )

    elif request.algorithm == "leaky_bucket":
        lb = await get_leaky_bucket()
        result = await lb.is_allowed(request.key, request.rate, request.capacity)
        return RateLimitTestResponse(
            allowed=result.allowed,
            remaining=request.capacity - int(result.bucket_level),
            limit=request.capacity,
            algorithm="leaky_bucket",
            details={
                "bucket_level": result.bucket_level,
                "queue_position": result.queue_position,
                "wait_time_seconds": result.wait_time_seconds,
            },
        )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown algorithm: {request.algorithm}",
        )


# Circuit Breaker
@router.post("/circuit-breaker/test", response_model=CircuitBreakerResponse)
async def test_circuit_breaker(
    request: CircuitBreakerTestRequest,
    _: str = Depends(verify_admin_key),
) -> CircuitBreakerResponse:
    """
    Test circuit breaker operations.
    
    Actions: check, success, failure, reset
    """
    cb = circuit_breaker_manager.get(request.name)

    if request.action == "check":
        can_execute = await cb.can_execute()
    elif request.action == "success":
        await cb.record_success()
        can_execute = await cb.can_execute()
    elif request.action == "failure":
        await cb.record_failure()
        can_execute = await cb.can_execute()
    elif request.action == "reset":
        await cb.reset()
        can_execute = True
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action: {request.action}",
        )

    stats = await cb.get_stats()
    return CircuitBreakerResponse(
        name=request.name,
        state=stats.state.value,
        can_execute=can_execute,
        stats={
            "failure_count": stats.failure_count,
            "success_count": stats.success_count,
            "total_failures": stats.total_failures,
            "total_successes": stats.total_successes,
        },
    )


# Bloom Filter
@router.post("/bloom/test", response_model=BloomFilterResponse)
async def test_bloom_filter(
    request: BloomFilterTestRequest,
    _: str = Depends(verify_admin_key),
) -> BloomFilterResponse:
    """
    Test bloom filter operations.
    
    Actions: add, check, stats
    """
    result = None

    if request.action == "add":
        result = await bloom_filter.add(request.item)
    elif request.action == "check":
        result = await bloom_filter.contains(request.item)
    elif request.action == "stats":
        pass
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action: {request.action}",
        )

    return BloomFilterResponse(
        action=request.action,
        item=request.item,
        result=result,
        stats=bloom_filter.get_stats(),
    )


# Count-Min Sketch
@router.post("/cms/test", response_model=CountMinSketchResponse)
async def test_count_min_sketch(
    request: CountMinSketchRequest,
    _: str = Depends(verify_admin_key),
) -> CountMinSketchResponse:
    """
    Test Count-Min Sketch operations.
    
    Actions: add, query
    """
    cms = CountMinSketch(name="cms:test")

    if request.action == "add":
        count = await cms.add(request.item, request.count)
    elif request.action == "query":
        count = await cms.query(request.item)
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action: {request.action}",
        )

    return CountMinSketchResponse(
        action=request.action,
        item=request.item,
        count=count,
        error_bounds=cms.get_error_bounds(),
    )


# Consistent Hash
_consistent_hash = ConsistentHash(nodes=["node-1", "node-2", "node-3"])


@router.post("/consistent-hash/test", response_model=ConsistentHashResponse)
async def test_consistent_hash(
    request: ConsistentHashRequest,
    _: str = Depends(verify_admin_key),
) -> ConsistentHashResponse:
    """
    Test consistent hashing operations.
    
    Actions: lookup, add_node, remove_node
    """
    global _consistent_hash

    if request.action == "lookup":
        node = _consistent_hash.get_node(request.key)
        return ConsistentHashResponse(
            action="lookup",
            key=request.key,
            node=node,
            distribution=_consistent_hash.get_distribution(),
        )

    elif request.action == "add_node":
        if not request.node:
            raise HTTPException(status_code=400, detail="Node name required")
        _consistent_hash.add_node(request.node)
        return ConsistentHashResponse(
            action="add_node",
            key=None,
            node=request.node,
            distribution=_consistent_hash.get_distribution(),
        )

    elif request.action == "remove_node":
        if not request.node:
            raise HTTPException(status_code=400, detail="Node name required")
        _consistent_hash.remove_node(request.node)
        return ConsistentHashResponse(
            action="remove_node",
            key=None,
            node=request.node,
            distribution=_consistent_hash.get_distribution(),
        )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action: {request.action}",
        )


# HyperLogLog
@router.post("/hll/test", response_model=HyperLogLogResponse)
async def test_hyperloglog(
    request: HyperLogLogRequest,
    _: str = Depends(verify_admin_key),
) -> HyperLogLogResponse:
    """
    Test HyperLogLog operations.
    
    Actions: add, count, clear
    """
    hll = HyperLogLog(name="hll:test")

    if request.action == "add":
        if request.items:
            await hll.add(*request.items)
        count = await hll.count()
        return HyperLogLogResponse(
            action="add",
            count=count,
            items_added=len(request.items),
        )

    elif request.action == "count":
        count = await hll.count()
        return HyperLogLogResponse(
            action="count",
            count=count,
            items_added=0,
        )

    elif request.action == "clear":
        await hll.clear()
        return HyperLogLogResponse(
            action="clear",
            count=0,
            items_added=0,
        )

    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown action: {request.action}",
        )


# EWMA
@router.post("/ewma/test", response_model=EWMATestResponse)
async def test_ewma(
    request: EWMATestRequest,
    _: str = Depends(verify_admin_key),
) -> EWMATestResponse:
    """
    Test EWMA (Exponentially Weighted Moving Average) calculation.
    
    Shows how EWMA smooths values over time.
    """
    ewma = 0.0
    variance = 0.0
    ewma_values = []

    for value in request.values:
        old_ewma = ewma
        ewma = EWMACalculator.update(ewma, value, request.alpha)
        variance = EWMACalculator.update_variance(variance, old_ewma, value, request.alpha)
        ewma_values.append(round(ewma, 4))

    import math
    std_dev = math.sqrt(variance)

    return EWMATestResponse(
        ewma_values=ewma_values,
        final_ewma=round(ewma, 4),
        variance=round(variance, 4),
        std_dev=round(std_dev, 4),
    )


# Z-Score
@router.post("/zscore/test", response_model=ZScoreTestResponse)
async def test_zscore(
    request: ZScoreTestRequest,
    _: str = Depends(verify_admin_key),
) -> ZScoreTestResponse:
    """
    Test Z-score anomaly detection.
    
    Calculates how many standard deviations a value is from the mean.
    """
    z_score = ZScoreDetector.calculate(
        request.value,
        request.mean,
        request.std_dev,
    )
    is_anomaly = ZScoreDetector.is_anomaly(z_score, request.threshold)

    return ZScoreTestResponse(
        value=request.value,
        z_score=round(z_score, 4),
        is_anomaly=is_anomaly,
        threshold=request.threshold,
    )


# Exponential Backoff
@router.post("/backoff/test", response_model=BackoffTestResponse)
async def test_backoff(
    request: BackoffTestRequest,
    _: str = Depends(verify_admin_key),
) -> BackoffTestResponse:
    """
    Test exponential backoff calculation.
    
    Shows the delay progression for retries.
    """
    backoff = ExponentialBackoff(
        base_delay=request.base_delay,
        max_delay=request.max_delay,
        max_attempts=request.max_attempts,
        jitter=False,  # Disable jitter for predictable demo
    )

    result = backoff.get_delay(request.attempt)

    # Calculate progression
    progression = []
    for i in range(1, request.max_attempts + 1):
        r = backoff.get_delay(i)
        progression.append(round(r.delay_seconds, 2))

    return BackoffTestResponse(
        attempt=request.attempt,
        should_retry=result.should_retry,
        delay_seconds=round(result.delay_seconds, 2),
        max_attempts=result.max_attempts,
        progression=progression,
    )


# Adaptive Rate Limiter Status
@router.get("/adaptive/status")
async def get_adaptive_status(
    key: str = Query(default="default", description="Rate limit key"),
    _: str = Depends(verify_admin_key),
) -> dict:
    """
    Get adaptive rate limiter status for a key.
    """
    arl = await get_adaptive_rate_limiter()
    current_rate = await arl.get_current_rate(key)

    return {
        "key": key,
        "current_rate": round(current_rate, 2),
        "base_rate": arl._base_rate,
        "min_rate": arl._min_rate,
        "max_rate": arl._max_rate,
    }


@router.post("/adaptive/simulate")
async def simulate_adaptive_update(
    key: str = Query(default="default"),
    cpu_usage: float = Query(default=0.5, ge=0, le=1),
    memory_usage: float = Query(default=0.5, ge=0, le=1),
    latency_p99: float = Query(default=100, ge=0),
    error_rate: float = Query(default=0.01, ge=0, le=1),
    _: str = Depends(verify_admin_key),
) -> dict:
    """
    Simulate an adaptive rate limit update based on system load.
    """
    arl = await get_adaptive_rate_limiter()
    old_rate = await arl.get_current_rate(key)

    load = SystemLoad(
        cpu_usage=cpu_usage,
        memory_usage=memory_usage,
        request_latency_p99=latency_p99,
        error_rate=error_rate,
    )

    new_rate = await arl.update_rate(key, load)

    return {
        "key": key,
        "old_rate": round(old_rate, 2),
        "new_rate": round(new_rate, 2),
        "change_percent": round((new_rate - old_rate) / old_rate * 100, 2) if old_rate > 0 else 0,
        "load": {
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "latency_p99_ms": latency_p99,
            "error_rate": error_rate,
        },
    }
