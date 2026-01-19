"""Pydantic schemas for API request/response validation."""

from src.schemas.admin import (
    ApiKeyCreate,
    ApiKeyResponse,
    ApiKeyUpdate,
    CachePolicyCreate,
    CachePolicyResponse,
    CachePolicyUpdate,
    RouteCreate,
    RouteResponse,
    RouteUpdate,
    TenantCreate,
    TenantResponse,
    TenantUpdate,
)
from src.schemas.analytics import (
    AnalyticsSummary,
    CacheHitRateResponse,
    TopKeysResponse,
    TopRoutesResponse,
)
from src.schemas.common import ErrorResponse, HealthResponse, PaginatedResponse

__all__ = [
    # Admin schemas
    "TenantCreate",
    "TenantResponse",
    "TenantUpdate",
    "ApiKeyCreate",
    "ApiKeyResponse",
    "ApiKeyUpdate",
    "RouteCreate",
    "RouteResponse",
    "RouteUpdate",
    "CachePolicyCreate",
    "CachePolicyResponse",
    "CachePolicyUpdate",
    # Analytics schemas
    "AnalyticsSummary",
    "CacheHitRateResponse",
    "TopKeysResponse",
    "TopRoutesResponse",
    # Common schemas
    "ErrorResponse",
    "HealthResponse",
    "PaginatedResponse",
]
