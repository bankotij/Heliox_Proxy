"""Admin API schemas for tenant, API key, route, and policy management."""

from datetime import datetime

from pydantic import BaseModel, Field, field_validator


# =============================================================================
# TENANT SCHEMAS
# =============================================================================


class TenantBase(BaseModel):
    """Base tenant fields."""

    name: str = Field(..., min_length=1, max_length=255, description="Tenant name")
    description: str | None = Field(None, max_length=1000, description="Tenant description")


class TenantCreate(TenantBase):
    """Schema for creating a tenant."""

    pass


class TenantUpdate(BaseModel):
    """Schema for updating a tenant."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    is_active: bool | None = None


class TenantResponse(TenantBase):
    """Tenant response schema."""

    id: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
    api_key_count: int = 0
    route_count: int = 0

    model_config = {"from_attributes": True}


# =============================================================================
# API KEY SCHEMAS
# =============================================================================


class ApiKeyBase(BaseModel):
    """Base API key fields."""

    name: str = Field(..., min_length=1, max_length=255, description="Key name/label")
    quota_daily: int = Field(0, ge=0, description="Daily request quota (0=unlimited)")
    quota_monthly: int = Field(0, ge=0, description="Monthly request quota (0=unlimited)")
    rate_limit_rps: float | None = Field(
        None,
        ge=0.1,
        le=10000,
        description="Requests per second limit",
    )
    rate_limit_burst: int | None = Field(
        None,
        ge=1,
        le=100000,
        description="Maximum burst size",
    )


class ApiKeyCreate(ApiKeyBase):
    """Schema for creating an API key."""

    tenant_id: str = Field(..., description="Tenant ID to associate the key with")
    expires_at: datetime | None = Field(None, description="Optional expiration time")


class ApiKeyUpdate(BaseModel):
    """Schema for updating an API key."""

    name: str | None = Field(None, min_length=1, max_length=255)
    status: str | None = Field(None, description="Key status: active, disabled, revoked")
    quota_daily: int | None = Field(None, ge=0)
    quota_monthly: int | None = Field(None, ge=0)
    rate_limit_rps: float | None = Field(None, ge=0.1, le=10000)
    rate_limit_burst: int | None = Field(None, ge=1, le=100000)
    expires_at: datetime | None = None

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str | None) -> str | None:
        if v is not None and v not in ("active", "disabled", "revoked"):
            raise ValueError("Status must be one of: active, disabled, revoked")
        return v


class ApiKeyResponse(ApiKeyBase):
    """API key response schema."""

    id: str
    tenant_id: str
    key: str = Field(..., description="The API key (shown only on creation)")
    key_prefix: str = Field(..., description="First 10 chars of the key for identification")
    status: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


class ApiKeyResponseMasked(BaseModel):
    """API key response with masked key (for listing)."""

    id: str
    tenant_id: str
    name: str
    key_prefix: str
    status: str
    quota_daily: int
    quota_monthly: int
    rate_limit_rps: float | None
    rate_limit_burst: int | None
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None
    last_used_at: datetime | None

    model_config = {"from_attributes": True}


# =============================================================================
# ROUTE SCHEMAS
# =============================================================================


class RouteBase(BaseModel):
    """Base route fields."""

    name: str = Field(..., min_length=1, max_length=255, description="Route name (used in URL)")
    description: str | None = Field(None, max_length=1000)
    path_pattern: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="Path pattern to match (e.g., /api/v1/*)",
    )
    methods: list[str] = Field(
        default=["GET", "POST", "PUT", "PATCH", "DELETE"],
        description="Allowed HTTP methods",
    )
    upstream_base_url: str = Field(
        ...,
        min_length=1,
        max_length=1000,
        description="Base URL of upstream service",
    )
    upstream_path_rewrite: str | None = Field(
        None,
        max_length=500,
        description="Path rewrite pattern",
    )
    timeout_ms: int = Field(30000, ge=100, le=300000, description="Request timeout in ms")

    @field_validator("methods")
    @classmethod
    def validate_methods(cls, v: list[str]) -> list[str]:
        valid = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
        for method in v:
            if method.upper() not in valid:
                raise ValueError(f"Invalid method: {method}")
        return [m.upper() for m in v]


class RouteCreate(RouteBase):
    """Schema for creating a route."""

    tenant_id: str | None = Field(None, description="Tenant ID (null for shared routes)")
    policy_id: str | None = Field(None, description="Cache policy ID")
    request_headers_add: dict[str, str] = Field(default_factory=dict)
    request_headers_remove: list[str] = Field(default_factory=list)
    response_headers_add: dict[str, str] = Field(default_factory=dict)
    rate_limit_rps: float | None = Field(None, ge=0.1, le=10000)
    rate_limit_burst: int | None = Field(None, ge=1, le=100000)
    priority: int = Field(0, ge=0, le=1000, description="Route matching priority")


class RouteUpdate(BaseModel):
    """Schema for updating a route."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    path_pattern: str | None = Field(None, min_length=1, max_length=500)
    methods: list[str] | None = None
    upstream_base_url: str | None = Field(None, min_length=1, max_length=1000)
    upstream_path_rewrite: str | None = None
    timeout_ms: int | None = Field(None, ge=100, le=300000)
    policy_id: str | None = None
    request_headers_add: dict[str, str] | None = None
    request_headers_remove: list[str] | None = None
    response_headers_add: dict[str, str] | None = None
    rate_limit_rps: float | None = Field(None, ge=0.1, le=10000)
    rate_limit_burst: int | None = Field(None, ge=1, le=100000)
    is_active: bool | None = None
    priority: int | None = Field(None, ge=0, le=1000)


class RouteResponse(RouteBase):
    """Route response schema."""

    id: str
    tenant_id: str | None
    policy_id: str | None
    request_headers_add: dict[str, str]
    request_headers_remove: list[str]
    response_headers_add: dict[str, str]
    rate_limit_rps: float | None
    rate_limit_burst: int | None
    is_active: bool
    priority: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# =============================================================================
# CACHE POLICY SCHEMAS
# =============================================================================


class CachePolicyBase(BaseModel):
    """Base cache policy fields."""

    name: str = Field(..., min_length=1, max_length=255, description="Policy name")
    description: str | None = Field(None, max_length=1000)
    ttl_seconds: int = Field(300, ge=0, le=86400 * 7, description="Cache TTL in seconds")
    stale_seconds: int = Field(
        60,
        ge=0,
        le=86400,
        description="SWR window - serve stale for this long while refreshing",
    )
    vary_headers_json: list[str] = Field(
        default_factory=list,
        description="Headers to include in cache key",
    )
    cacheable_statuses_json: list[int] = Field(
        default=[200, 201, 204, 301, 304],
        description="HTTP status codes to cache",
    )
    max_body_bytes: int = Field(
        10 * 1024 * 1024,
        ge=0,
        le=100 * 1024 * 1024,
        description="Max response body size to cache",
    )


class CachePolicyCreate(CachePolicyBase):
    """Schema for creating a cache policy."""

    cache_private: bool = Field(False, description="Cache private responses")
    cache_no_store: bool = Field(False, description="Bypass cache entirely")


class CachePolicyUpdate(BaseModel):
    """Schema for updating a cache policy."""

    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = Field(None, max_length=1000)
    ttl_seconds: int | None = Field(None, ge=0, le=86400 * 7)
    stale_seconds: int | None = Field(None, ge=0, le=86400)
    vary_headers_json: list[str] | None = None
    cacheable_statuses_json: list[int] | None = None
    max_body_bytes: int | None = Field(None, ge=0, le=100 * 1024 * 1024)
    cache_private: bool | None = None
    cache_no_store: bool | None = None


class CachePolicyResponse(CachePolicyBase):
    """Cache policy response schema."""

    id: str
    cache_private: bool
    cache_no_store: bool
    created_at: datetime
    updated_at: datetime
    route_count: int = 0

    model_config = {"from_attributes": True}


# =============================================================================
# BLOCK RULE SCHEMAS
# =============================================================================


class BlockRuleResponse(BaseModel):
    """Block rule response schema."""

    id: str
    api_key_id: str
    reason: str
    reason_detail: str | None
    anomaly_score: float | None
    rate_at_block: float | None
    error_rate_at_block: float | None
    blocked_at: datetime
    blocked_until: datetime | None
    unblocked_at: datetime | None
    unblocked_by: str | None
    unblock_reason: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class UnblockRequest(BaseModel):
    """Request to unblock an API key."""

    reason: str = Field(..., min_length=1, max_length=500, description="Reason for unblocking")


# =============================================================================
# CACHE MANAGEMENT SCHEMAS
# =============================================================================


class CachePurgeRequest(BaseModel):
    """Request to purge cache entries."""

    route_name: str | None = Field(None, description="Purge by route name")
    prefix: str | None = Field(None, description="Purge by key prefix")
    all: bool = Field(False, description="Purge all cache entries")


class CachePurgeResponse(BaseModel):
    """Response from cache purge operation."""

    purged_count: int = Field(..., description="Number of entries purged")
    message: str = Field(..., description="Status message")
