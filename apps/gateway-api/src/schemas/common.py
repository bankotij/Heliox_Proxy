"""Common schemas used across the API."""

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str = Field(..., description="Error type/code")
    message: str = Field(..., description="Human-readable error message")
    details: dict[str, Any] | None = Field(None, description="Additional error details")
    request_id: str | None = Field(None, description="Request ID for tracing")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    components: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Component health status",
    )


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response."""

    items: list[T] = Field(..., description="List of items")
    total: int = Field(..., description="Total number of items")
    page: int = Field(..., description="Current page number")
    page_size: int = Field(..., description="Items per page")
    has_more: bool = Field(..., description="Whether more items exist")


class MetricsResponse(BaseModel):
    """Prometheus-style metrics response."""

    cache_hit_total: int = 0
    cache_miss_total: int = 0
    cache_stale_total: int = 0
    upstream_error_total: int = 0
    rate_limited_total: int = 0
    blocked_total: int = 0
    requests_total: int = 0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    latency_p99_ms: float = 0.0
