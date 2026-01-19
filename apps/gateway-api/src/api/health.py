"""Health check and metrics endpoints."""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src import __version__
from src.database import get_db
from src.schemas.common import HealthResponse, MetricsResponse
from src.services.cache import cache_metrics
from src.services.rate_limiter import rate_limit_metrics
from src.services.redis_client import redis_client

router = APIRouter(tags=["Health"])


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)) -> HealthResponse:
    """
    Check service health status.
    
    Returns the health of all components:
    - Database connection
    - Redis connection
    - Overall service status
    """
    components: dict = {}

    # Check database
    try:
        await db.execute(text("SELECT 1"))
        components["database"] = {"status": "healthy"}
    except Exception as e:
        components["database"] = {"status": "unhealthy", "error": str(e)}

    # Check Redis
    try:
        if redis_client.is_demo_mode:
            components["redis"] = {"status": "demo_mode", "message": "Using in-memory cache"}
        else:
            await redis_client.get("health_check")
            components["redis"] = {"status": "healthy"}
    except Exception as e:
        components["redis"] = {"status": "unhealthy", "error": str(e)}

    # Determine overall status
    all_healthy = all(
        c.get("status") in ("healthy", "demo_mode")
        for c in components.values()
    )

    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        version=__version__,
        timestamp=datetime.utcnow(),
        components=components,
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics() -> MetricsResponse:
    """
    Get Prometheus-style metrics.
    
    Returns counters for:
    - Cache hits/misses/stale
    - Rate limiting
    - Errors and blocks
    """
    cache = cache_metrics.to_dict()
    rate = rate_limit_metrics.to_dict()

    return MetricsResponse(
        cache_hit_total=cache["hits"],
        cache_miss_total=cache["misses"],
        cache_stale_total=cache["stale_hits"],
        rate_limited_total=rate["denied"],
        requests_total=cache["hits"] + cache["misses"] + cache["stale_hits"],
    )


@router.get("/metrics/prometheus")
async def prometheus_metrics() -> str:
    """
    Get metrics in Prometheus text format.
    
    Suitable for scraping by Prometheus server.
    """
    cache = cache_metrics.to_dict()
    rate = rate_limit_metrics.to_dict()

    lines = [
        "# HELP heliox_cache_hits_total Total cache hits",
        "# TYPE heliox_cache_hits_total counter",
        f"heliox_cache_hits_total {cache['hits']}",
        "",
        "# HELP heliox_cache_misses_total Total cache misses",
        "# TYPE heliox_cache_misses_total counter",
        f"heliox_cache_misses_total {cache['misses']}",
        "",
        "# HELP heliox_cache_stale_total Total stale cache hits (SWR)",
        "# TYPE heliox_cache_stale_total counter",
        f"heliox_cache_stale_total {cache['stale_hits']}",
        "",
        "# HELP heliox_cache_hit_rate Cache hit rate",
        "# TYPE heliox_cache_hit_rate gauge",
        f"heliox_cache_hit_rate {cache['hit_rate']:.4f}",
        "",
        "# HELP heliox_rate_limited_total Total rate limited requests",
        "# TYPE heliox_rate_limited_total counter",
        f"heliox_rate_limited_total {rate['denied']}",
        "",
        "# HELP heliox_quota_exceeded_total Total quota exceeded requests",
        "# TYPE heliox_quota_exceeded_total counter",
        f"heliox_quota_exceeded_total {rate['quota_exceeded']}",
    ]

    return "\n".join(lines)
