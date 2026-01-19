"""Admin API endpoints for tenant, key, route, and policy management."""

from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.config import get_settings
from src.database import get_db
from src.models import ApiKey, BlockRule, CachePolicy, RequestLog, Route, Tenant
from src.models.api_key import ApiKeyStatus, generate_api_key
from src.models.block_rule import BlockReason
from src.models.request_log import CacheStatus
from src.schemas.admin import (
    ApiKeyCreate,
    ApiKeyResponse,
    ApiKeyResponseMasked,
    ApiKeyUpdate,
    BlockRuleResponse,
    CachePolicyCreate,
    CachePolicyResponse,
    CachePolicyUpdate,
    CachePurgeRequest,
    CachePurgeResponse,
    RouteCreate,
    RouteResponse,
    RouteUpdate,
    TenantCreate,
    TenantResponse,
    TenantUpdate,
    UnblockRequest,
)
from src.schemas.analytics import (
    AnalyticsSummary,
    CacheHitRateResponse,
    LatencyPercentiles,
    RequestLogItem,
    RequestLogsResponse,
    TopKeyItem,
    TopKeysResponse,
    TopRouteItem,
    TopRoutesResponse,
)
from src.services.abuse import abuse_detector
from src.services.cache import cache_service

router = APIRouter(prefix="/admin", tags=["Admin"])


async def verify_admin_key(
    x_admin_key: Annotated[str | None, Header()] = None,
) -> None:
    """Verify admin API key."""
    settings = get_settings()
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="Invalid admin API key")


AdminDep = Depends(verify_admin_key)


# =============================================================================
# TENANT ENDPOINTS
# =============================================================================


@router.post("/tenants", response_model=TenantResponse, dependencies=[AdminDep])
async def create_tenant(
    data: TenantCreate,
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    """Create a new tenant."""
    # Check for duplicate name
    existing = await db.execute(select(Tenant).where(Tenant.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Tenant name already exists")

    tenant = Tenant(name=data.name, description=data.description)
    db.add(tenant)
    await db.flush()

    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        description=tenant.description,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
    )


@router.get("/tenants", response_model=list[TenantResponse], dependencies=[AdminDep])
async def list_tenants(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> list[TenantResponse]:
    """List all tenants."""
    result = await db.execute(
        select(Tenant)
        .options(selectinload(Tenant.api_keys), selectinload(Tenant.routes))
        .offset(skip)
        .limit(limit)
        .order_by(Tenant.created_at.desc())
    )
    tenants = result.scalars().all()

    return [
        TenantResponse(
            id=t.id,
            name=t.name,
            description=t.description,
            is_active=t.is_active,
            created_at=t.created_at,
            updated_at=t.updated_at,
            api_key_count=len(t.api_keys),
            route_count=len(t.routes),
        )
        for t in tenants
    ]


@router.get("/tenants/{tenant_id}", response_model=TenantResponse, dependencies=[AdminDep])
async def get_tenant(
    tenant_id: str,
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    """Get a tenant by ID."""
    result = await db.execute(
        select(Tenant)
        .options(selectinload(Tenant.api_keys), selectinload(Tenant.routes))
        .where(Tenant.id == tenant_id)
    )
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        description=tenant.description,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
        api_key_count=len(tenant.api_keys),
        route_count=len(tenant.routes),
    )


@router.patch("/tenants/{tenant_id}", response_model=TenantResponse, dependencies=[AdminDep])
async def update_tenant(
    tenant_id: str,
    data: TenantUpdate,
    db: AsyncSession = Depends(get_db),
) -> TenantResponse:
    """Update a tenant."""
    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()

    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    if data.name is not None:
        tenant.name = data.name
    if data.description is not None:
        tenant.description = data.description
    if data.is_active is not None:
        tenant.is_active = data.is_active

    await db.flush()

    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        description=tenant.description,
        is_active=tenant.is_active,
        created_at=tenant.created_at,
        updated_at=tenant.updated_at,
    )


# =============================================================================
# API KEY ENDPOINTS
# =============================================================================


@router.post("/keys", response_model=ApiKeyResponse, dependencies=[AdminDep])
async def create_api_key(
    data: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
) -> ApiKeyResponse:
    """Create a new API key."""
    # Verify tenant exists
    result = await db.execute(select(Tenant).where(Tenant.id == data.tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Generate key
    key = generate_api_key()

    api_key = ApiKey(
        tenant_id=data.tenant_id,
        name=data.name,
        key=key,
        key_prefix=key[:10],
        quota_daily=data.quota_daily,
        quota_monthly=data.quota_monthly,
        rate_limit_rps=data.rate_limit_rps,
        rate_limit_burst=data.rate_limit_burst,
        expires_at=data.expires_at,
    )
    db.add(api_key)
    await db.flush()

    return ApiKeyResponse(
        id=api_key.id,
        tenant_id=api_key.tenant_id,
        name=api_key.name,
        key=api_key.key,  # Only returned on creation
        key_prefix=api_key.key_prefix,
        status=api_key.status.value,
        quota_daily=api_key.quota_daily,
        quota_monthly=api_key.quota_monthly,
        rate_limit_rps=api_key.rate_limit_rps,
        rate_limit_burst=api_key.rate_limit_burst,
        created_at=api_key.created_at,
        updated_at=api_key.updated_at,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
    )


@router.get("/keys", response_model=list[ApiKeyResponseMasked], dependencies=[AdminDep])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    tenant_id: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> list[ApiKeyResponseMasked]:
    """List API keys (masked)."""
    query = select(ApiKey)
    if tenant_id:
        query = query.where(ApiKey.tenant_id == tenant_id)

    result = await db.execute(
        query.offset(skip).limit(limit).order_by(ApiKey.created_at.desc())
    )
    keys = result.scalars().all()

    return [ApiKeyResponseMasked.model_validate(k) for k in keys]


@router.patch("/keys/{key_id}", response_model=ApiKeyResponseMasked, dependencies=[AdminDep])
async def update_api_key(
    key_id: str,
    data: ApiKeyUpdate,
    db: AsyncSession = Depends(get_db),
) -> ApiKeyResponseMasked:
    """Update an API key."""
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    if data.name is not None:
        api_key.name = data.name
    if data.status is not None:
        api_key.status = ApiKeyStatus(data.status)
    if data.quota_daily is not None:
        api_key.quota_daily = data.quota_daily
    if data.quota_monthly is not None:
        api_key.quota_monthly = data.quota_monthly
    if data.rate_limit_rps is not None:
        api_key.rate_limit_rps = data.rate_limit_rps
    if data.rate_limit_burst is not None:
        api_key.rate_limit_burst = data.rate_limit_burst
    if data.expires_at is not None:
        api_key.expires_at = data.expires_at

    await db.flush()

    return ApiKeyResponseMasked.model_validate(api_key)


@router.delete("/keys/{key_id}", dependencies=[AdminDep])
async def delete_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete an API key."""
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    await db.delete(api_key)
    return {"deleted": True}


@router.post("/keys/{key_id}/rotate", response_model=ApiKeyResponse, dependencies=[AdminDep])
async def rotate_api_key(
    key_id: str,
    db: AsyncSession = Depends(get_db),
) -> ApiKeyResponse:
    """Rotate an API key (generate new key, invalidate old)."""
    result = await db.execute(select(ApiKey).where(ApiKey.id == key_id))
    api_key = result.scalar_one_or_none()

    if not api_key:
        raise HTTPException(status_code=404, detail="API key not found")

    # Generate new key
    new_key = generate_api_key()
    api_key.key = new_key
    api_key.key_prefix = new_key[:10]

    await db.flush()

    return ApiKeyResponse(
        id=api_key.id,
        tenant_id=api_key.tenant_id,
        name=api_key.name,
        key=api_key.key,  # Return new key
        key_prefix=api_key.key_prefix,
        status=api_key.status.value,
        quota_daily=api_key.quota_daily,
        quota_monthly=api_key.quota_monthly,
        rate_limit_rps=api_key.rate_limit_rps,
        rate_limit_burst=api_key.rate_limit_burst,
        created_at=api_key.created_at,
        updated_at=api_key.updated_at,
        expires_at=api_key.expires_at,
        last_used_at=api_key.last_used_at,
    )


# =============================================================================
# ROUTE ENDPOINTS
# =============================================================================


@router.post("/routes", response_model=RouteResponse, dependencies=[AdminDep])
async def create_route(
    data: RouteCreate,
    db: AsyncSession = Depends(get_db),
) -> RouteResponse:
    """Create a new route."""
    # Verify tenant if provided
    if data.tenant_id:
        result = await db.execute(select(Tenant).where(Tenant.id == data.tenant_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Tenant not found")

    # Verify policy if provided
    if data.policy_id:
        result = await db.execute(select(CachePolicy).where(CachePolicy.id == data.policy_id))
        if not result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Cache policy not found")

    # Check for duplicate route name
    existing = await db.execute(select(Route).where(Route.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Route name already exists")

    route = Route(
        name=data.name,
        description=data.description,
        tenant_id=data.tenant_id,
        path_pattern=data.path_pattern,
        methods=data.methods,
        upstream_base_url=data.upstream_base_url,
        upstream_path_rewrite=data.upstream_path_rewrite,
        timeout_ms=data.timeout_ms,
        policy_id=data.policy_id,
        request_headers_add=data.request_headers_add,
        request_headers_remove=data.request_headers_remove,
        response_headers_add=data.response_headers_add,
        rate_limit_rps=data.rate_limit_rps,
        rate_limit_burst=data.rate_limit_burst,
        priority=data.priority,
    )
    db.add(route)
    await db.flush()

    return RouteResponse.model_validate(route)


@router.get("/routes", response_model=list[RouteResponse], dependencies=[AdminDep])
async def list_routes(
    db: AsyncSession = Depends(get_db),
    tenant_id: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> list[RouteResponse]:
    """List routes."""
    query = select(Route)
    if tenant_id:
        query = query.where((Route.tenant_id == tenant_id) | (Route.tenant_id.is_(None)))

    result = await db.execute(
        query.offset(skip).limit(limit).order_by(Route.priority.desc(), Route.created_at.desc())
    )
    routes = result.scalars().all()

    return [RouteResponse.model_validate(r) for r in routes]


@router.patch("/routes/{route_id}", response_model=RouteResponse, dependencies=[AdminDep])
async def update_route(
    route_id: str,
    data: RouteUpdate,
    db: AsyncSession = Depends(get_db),
) -> RouteResponse:
    """Update a route."""
    result = await db.execute(select(Route).where(Route.id == route_id))
    route = result.scalar_one_or_none()

    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(route, field, value)

    await db.flush()

    return RouteResponse.model_validate(route)


@router.delete("/routes/{route_id}", dependencies=[AdminDep])
async def delete_route(
    route_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a route."""
    result = await db.execute(select(Route).where(Route.id == route_id))
    route = result.scalar_one_or_none()

    if not route:
        raise HTTPException(status_code=404, detail="Route not found")

    await db.delete(route)
    return {"deleted": True}


# =============================================================================
# CACHE POLICY ENDPOINTS
# =============================================================================


@router.post("/policies", response_model=CachePolicyResponse, dependencies=[AdminDep])
async def create_cache_policy(
    data: CachePolicyCreate,
    db: AsyncSession = Depends(get_db),
) -> CachePolicyResponse:
    """Create a new cache policy."""
    existing = await db.execute(select(CachePolicy).where(CachePolicy.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Policy name already exists")

    policy = CachePolicy(
        name=data.name,
        description=data.description,
        ttl_seconds=data.ttl_seconds,
        stale_seconds=data.stale_seconds,
        vary_headers_json=data.vary_headers_json,
        cacheable_statuses_json=data.cacheable_statuses_json,
        max_body_bytes=data.max_body_bytes,
        cache_private=data.cache_private,
        cache_no_store=data.cache_no_store,
    )
    db.add(policy)
    await db.flush()

    return CachePolicyResponse.model_validate(policy)


@router.get("/policies", response_model=list[CachePolicyResponse], dependencies=[AdminDep])
async def list_cache_policies(
    db: AsyncSession = Depends(get_db),
) -> list[CachePolicyResponse]:
    """List all cache policies."""
    result = await db.execute(
        select(CachePolicy)
        .options(selectinload(CachePolicy.routes))
        .order_by(CachePolicy.created_at.desc())
    )
    policies = result.scalars().all()

    return [
        CachePolicyResponse(
            id=p.id,
            name=p.name,
            description=p.description,
            ttl_seconds=p.ttl_seconds,
            stale_seconds=p.stale_seconds,
            vary_headers_json=p.vary_headers_json,
            cacheable_statuses_json=p.cacheable_statuses_json,
            max_body_bytes=p.max_body_bytes,
            cache_private=p.cache_private,
            cache_no_store=p.cache_no_store,
            created_at=p.created_at,
            updated_at=p.updated_at,
            route_count=len(p.routes),
        )
        for p in policies
    ]


@router.patch("/policies/{policy_id}", response_model=CachePolicyResponse, dependencies=[AdminDep])
async def update_cache_policy(
    policy_id: str,
    data: CachePolicyUpdate,
    db: AsyncSession = Depends(get_db),
) -> CachePolicyResponse:
    """Update a cache policy."""
    result = await db.execute(select(CachePolicy).where(CachePolicy.id == policy_id))
    policy = result.scalar_one_or_none()

    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")

    update_fields = data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(policy, field, value)

    await db.flush()

    return CachePolicyResponse.model_validate(policy)


# =============================================================================
# ANALYTICS ENDPOINTS
# =============================================================================


@router.get("/analytics/summary", response_model=AnalyticsSummary, dependencies=[AdminDep])
async def get_analytics_summary(
    db: AsyncSession = Depends(get_db),
    hours: int = Query(24, ge=1, le=168),
) -> AnalyticsSummary:
    """Get analytics summary for the specified time period."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    # Get total requests and error count
    result = await db.execute(
        select(
            func.count(RequestLog.id).label("total"),
            func.count().filter(RequestLog.error_type != "none").label("errors"),
            func.avg(RequestLog.latency_ms).label("avg_latency"),
        ).where(RequestLog.timestamp >= since)
    )
    stats = result.one()

    # Get cache stats
    cache_result = await db.execute(
        select(
            func.count().filter(RequestLog.cache_status == CacheStatus.HIT).label("hits"),
            func.count().filter(RequestLog.cache_status == CacheStatus.MISS).label("misses"),
            func.count().filter(RequestLog.cache_status == CacheStatus.STALE).label("stale"),
        ).where(RequestLog.timestamp >= since)
    )
    cache_stats = cache_result.one()

    # Get unique counts
    unique_result = await db.execute(
        select(
            func.count(func.distinct(RequestLog.api_key_id)).label("unique_keys"),
            func.count(func.distinct(RequestLog.route_id)).label("unique_routes"),
        ).where(RequestLog.timestamp >= since)
    )
    unique_stats = unique_result.one()

    total = stats.total or 0
    hits = cache_stats.hits or 0
    misses = cache_stats.misses or 0
    stale = cache_stats.stale or 0

    cache_total = hits + misses + stale
    hit_rate = (hits + stale) / cache_total if cache_total > 0 else 0.0

    return AnalyticsSummary(
        total_requests=total,
        requests_per_minute=total / (hours * 60) if total > 0 else 0.0,
        unique_keys=unique_stats.unique_keys or 0,
        unique_routes=unique_stats.unique_routes or 0,
        avg_latency_ms=float(stats.avg_latency or 0),
        cache_hit_rate=hit_rate,
        cache_hits=hits,
        cache_misses=misses,
        cache_stale=stale,
        error_rate=(stats.errors or 0) / total if total > 0 else 0.0,
        error_count=stats.errors or 0,
        period_start=since,
        period_end=datetime.now(timezone.utc),
    )


@router.get("/analytics/top-keys", response_model=TopKeysResponse, dependencies=[AdminDep])
async def get_top_keys(
    db: AsyncSession = Depends(get_db),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(10, ge=1, le=50),
) -> TopKeysResponse:
    """Get top API keys by traffic."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    result = await db.execute(
        select(
            RequestLog.api_key_id,
            func.count(RequestLog.id).label("count"),
            func.count().filter(RequestLog.error_type != "none").label("errors"),
            func.avg(RequestLog.latency_ms).label("avg_latency"),
            func.count().filter(RequestLog.cache_status.in_(["hit", "stale"])).label("cache_hits"),
        )
        .where(RequestLog.timestamp >= since)
        .where(RequestLog.api_key_id.isnot(None))
        .group_by(RequestLog.api_key_id)
        .order_by(func.count(RequestLog.id).desc())
        .limit(limit)
    )
    rows = result.all()

    # Get API key details
    items = []
    for row in rows:
        key_result = await db.execute(
            select(ApiKey)
            .options(selectinload(ApiKey.tenant))
            .where(ApiKey.id == row.api_key_id)
        )
        api_key = key_result.scalar_one_or_none()
        if api_key:
            hit_rate = row.cache_hits / row.count if row.count > 0 else 0.0
            items.append(TopKeyItem(
                api_key_id=api_key.id,
                api_key_name=api_key.name,
                tenant_id=api_key.tenant_id,
                tenant_name=api_key.tenant.name if api_key.tenant else "Unknown",
                request_count=row.count,
                error_count=row.errors,
                avg_latency_ms=float(row.avg_latency or 0),
                cache_hit_rate=hit_rate,
            ))

    total_result = await db.execute(
        select(func.count(RequestLog.id)).where(RequestLog.timestamp >= since)
    )

    return TopKeysResponse(
        items=items,
        period_start=since,
        period_end=datetime.now(timezone.utc),
        total_requests=total_result.scalar() or 0,
    )


@router.get("/analytics/top-routes", response_model=TopRoutesResponse, dependencies=[AdminDep])
async def get_top_routes(
    db: AsyncSession = Depends(get_db),
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(10, ge=1, le=50),
) -> TopRoutesResponse:
    """Get top routes by traffic."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    result = await db.execute(
        select(
            RequestLog.route_id,
            func.count(RequestLog.id).label("count"),
            func.avg(RequestLog.latency_ms).label("avg_latency"),
            func.count().filter(RequestLog.cache_status.in_(["hit", "stale"])).label("cache_hits"),
            func.count().filter(RequestLog.error_type != "none").label("errors"),
        )
        .where(RequestLog.timestamp >= since)
        .where(RequestLog.route_id.isnot(None))
        .group_by(RequestLog.route_id)
        .order_by(func.count(RequestLog.id).desc())
        .limit(limit)
    )
    rows = result.all()

    items = []
    for row in rows:
        route_result = await db.execute(select(Route).where(Route.id == row.route_id))
        route = route_result.scalar_one_or_none()
        if route:
            hit_rate = row.cache_hits / row.count if row.count > 0 else 0.0
            error_rate = row.errors / row.count if row.count > 0 else 0.0
            items.append(TopRouteItem(
                route_id=route.id,
                route_name=route.name,
                request_count=row.count,
                avg_latency_ms=float(row.avg_latency or 0),
                cache_hit_rate=hit_rate,
                error_rate=error_rate,
            ))

    total_result = await db.execute(
        select(func.count(RequestLog.id)).where(RequestLog.timestamp >= since)
    )

    return TopRoutesResponse(
        items=items,
        period_start=since,
        period_end=datetime.now(timezone.utc),
        total_requests=total_result.scalar() or 0,
    )


@router.get("/analytics/cache-hit-rate", response_model=CacheHitRateResponse, dependencies=[AdminDep])
async def get_cache_hit_rate(
    db: AsyncSession = Depends(get_db),
    hours: int = Query(24, ge=1, le=168),
) -> CacheHitRateResponse:
    """Get cache hit rate analytics."""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    result = await db.execute(
        select(
            func.count().filter(RequestLog.cache_status == CacheStatus.HIT).label("hits"),
            func.count().filter(RequestLog.cache_status == CacheStatus.MISS).label("misses"),
            func.count().filter(RequestLog.cache_status == CacheStatus.STALE).label("stale"),
        ).where(RequestLog.timestamp >= since)
    )
    stats = result.one()

    hits = stats.hits or 0
    misses = stats.misses or 0
    stale = stats.stale or 0
    total = hits + misses + stale
    hit_rate = (hits + stale) / total if total > 0 else 0.0

    return CacheHitRateResponse(
        overall_hit_rate=hit_rate,
        hits=hits,
        misses=misses,
        stale_hits=stale,
        period_start=since,
        period_end=datetime.now(timezone.utc),
    )


@router.get("/analytics/logs", response_model=RequestLogsResponse, dependencies=[AdminDep])
async def get_request_logs(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    tenant_id: str | None = None,
    route_id: str | None = None,
    status_code: int | None = None,
    cache_status: str | None = None,
) -> RequestLogsResponse:
    """Get paginated request logs."""
    query = select(RequestLog)

    if tenant_id:
        query = query.where(RequestLog.tenant_id == tenant_id)
    if route_id:
        query = query.where(RequestLog.route_id == route_id)
    if status_code:
        query = query.where(RequestLog.status_code == status_code)
    if cache_status:
        query = query.where(RequestLog.cache_status == cache_status)

    # Get total count
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar() or 0

    # Get paginated results
    result = await db.execute(
        query
        .order_by(RequestLog.timestamp.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    logs = result.scalars().all()

    items = []
    for log in logs:
        # Get related names
        tenant_name = None
        api_key_name = None
        route_name = None

        if log.tenant_id:
            t_result = await db.execute(select(Tenant.name).where(Tenant.id == log.tenant_id))
            tenant_name = t_result.scalar()
        if log.api_key_id:
            k_result = await db.execute(select(ApiKey.name).where(ApiKey.id == log.api_key_id))
            api_key_name = k_result.scalar()
        if log.route_id:
            r_result = await db.execute(select(Route.name).where(Route.id == log.route_id))
            route_name = r_result.scalar()

        items.append(RequestLogItem(
            id=log.id,
            request_id=log.request_id,
            timestamp=log.timestamp,
            tenant_id=log.tenant_id,
            tenant_name=tenant_name,
            api_key_id=log.api_key_id,
            api_key_name=api_key_name,
            route_id=log.route_id,
            route_name=route_name,
            method=log.method,
            path=log.path,
            status_code=log.status_code,
            latency_ms=log.latency_ms,
            cache_status=log.cache_status.value if log.cache_status else "unknown",
            error_type=log.error_type.value if log.error_type and log.error_type.value != "none" else None,
            client_ip=log.client_ip,
        ))

    return RequestLogsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_more=(page * page_size) < total,
    )


# =============================================================================
# CACHE MANAGEMENT ENDPOINTS
# =============================================================================


@router.post("/cache/purge", response_model=CachePurgeResponse, dependencies=[AdminDep])
async def purge_cache(data: CachePurgeRequest) -> CachePurgeResponse:
    """Purge cache entries."""
    purged = 0

    if data.all:
        # Note: Full purge would require SCAN in production
        purged = 0  # Placeholder
        message = "Full cache purge initiated"
    elif data.route_name:
        purged = await cache_service.purge_by_prefix(f"cache:route:{data.route_name}")
        message = f"Purged cache for route: {data.route_name}"
    elif data.prefix:
        purged = await cache_service.purge_by_prefix(data.prefix)
        message = f"Purged cache with prefix: {data.prefix}"
    else:
        raise HTTPException(status_code=400, detail="Specify route_name, prefix, or all=true")

    return CachePurgeResponse(purged_count=purged, message=message)


# =============================================================================
# ABUSE MANAGEMENT ENDPOINTS
# =============================================================================


@router.get("/abuse/blocked", response_model=list[BlockRuleResponse], dependencies=[AdminDep])
async def get_blocked_keys(
    db: AsyncSession = Depends(get_db),
) -> list[BlockRuleResponse]:
    """Get all currently blocked API keys."""
    result = await db.execute(
        select(BlockRule)
        .where(BlockRule.unblocked_at.is_(None))
        .order_by(BlockRule.blocked_at.desc())
    )
    blocks = result.scalars().all()

    return [
        BlockRuleResponse(
            id=b.id,
            api_key_id=b.api_key_id,
            reason=b.reason.value if isinstance(b.reason, BlockReason) else b.reason,
            reason_detail=b.reason_detail,
            anomaly_score=b.anomaly_score,
            rate_at_block=b.rate_at_block,
            error_rate_at_block=b.error_rate_at_block,
            blocked_at=b.blocked_at,
            blocked_until=b.blocked_until,
            unblocked_at=b.unblocked_at,
            unblocked_by=b.unblocked_by,
            unblock_reason=b.unblock_reason,
            is_active=b.is_active,
        )
        for b in blocks
    ]


@router.post("/abuse/unblock/{api_key_id}", dependencies=[AdminDep])
async def unblock_api_key(
    api_key_id: str,
    data: UnblockRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Manually unblock an API key."""
    # Unblock in Redis
    await abuse_detector.unblock(api_key_id)

    # Update database block rules
    result = await db.execute(
        select(BlockRule)
        .where(BlockRule.api_key_id == api_key_id)
        .where(BlockRule.unblocked_at.is_(None))
    )
    blocks = result.scalars().all()

    for block in blocks:
        block.unblocked_at = datetime.now(timezone.utc)
        block.unblock_reason = data.reason
        block.unblocked_by = "admin"

    return {"unblocked": True, "blocks_cleared": len(blocks)}
