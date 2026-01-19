"""Analytics and reporting schemas."""

from datetime import datetime

from pydantic import BaseModel, Field


class TopKeyItem(BaseModel):
    """Item in top keys list."""

    api_key_id: str
    api_key_name: str
    tenant_id: str
    tenant_name: str
    request_count: int
    error_count: int
    avg_latency_ms: float
    cache_hit_rate: float


class TopKeysResponse(BaseModel):
    """Response for top API keys by traffic."""

    items: list[TopKeyItem]
    period_start: datetime
    period_end: datetime
    total_requests: int


class TopRouteItem(BaseModel):
    """Item in top routes list."""

    route_id: str
    route_name: str
    request_count: int
    avg_latency_ms: float
    cache_hit_rate: float
    error_rate: float


class TopRoutesResponse(BaseModel):
    """Response for top routes by traffic."""

    items: list[TopRouteItem]
    period_start: datetime
    period_end: datetime
    total_requests: int


class CacheHitRateResponse(BaseModel):
    """Response for cache hit rate analytics."""

    overall_hit_rate: float = Field(..., description="Overall cache hit rate (0-1)")
    hits: int = Field(..., description="Total cache hits")
    misses: int = Field(..., description="Total cache misses")
    stale_hits: int = Field(..., description="Stale cache hits (SWR)")
    by_route: dict[str, float] = Field(
        default_factory=dict,
        description="Hit rate by route name",
    )
    by_hour: list[dict] = Field(
        default_factory=list,
        description="Hit rate by hour for the last 24 hours",
    )
    period_start: datetime
    period_end: datetime


class LatencyPercentiles(BaseModel):
    """Latency percentile breakdown."""

    p50: float
    p75: float
    p90: float
    p95: float
    p99: float


class AnalyticsSummary(BaseModel):
    """Summary analytics for dashboard."""

    # Traffic
    total_requests: int = 0
    requests_per_minute: float = 0.0
    unique_keys: int = 0
    unique_routes: int = 0

    # Performance
    avg_latency_ms: float = 0.0
    latency_percentiles: LatencyPercentiles | None = None

    # Cache
    cache_hit_rate: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    cache_stale: int = 0

    # Errors
    error_rate: float = 0.0
    error_count: int = 0
    rate_limited_count: int = 0
    blocked_count: int = 0

    # Time period
    period_start: datetime | None = None
    period_end: datetime | None = None


class RequestLogItem(BaseModel):
    """Single request log entry."""

    id: str
    request_id: str
    timestamp: datetime
    tenant_id: str | None
    tenant_name: str | None
    api_key_id: str | None
    api_key_name: str | None
    route_id: str | None
    route_name: str | None
    method: str
    path: str
    status_code: int
    latency_ms: int
    cache_status: str
    error_type: str | None
    client_ip: str | None

    model_config = {"from_attributes": True}


class RequestLogsResponse(BaseModel):
    """Paginated request logs response."""

    items: list[RequestLogItem]
    total: int
    page: int
    page_size: int
    has_more: bool


class TimeSeriesPoint(BaseModel):
    """Single point in a time series."""

    timestamp: datetime
    value: float


class TimeSeriesResponse(BaseModel):
    """Time series data response."""

    metric: str
    points: list[TimeSeriesPoint]
    period_start: datetime
    period_end: datetime
    interval_seconds: int
