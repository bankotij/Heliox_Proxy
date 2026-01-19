"""Gateway proxy endpoints - the main request handling."""

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.background import BackgroundTask

from src.database import get_db
from src.gateway.proxy import GatewayProxy, gateway_proxy
from src.gateway.router import GatewayRouter
from src.models import RequestLog
from src.models.request_log import CacheStatus, ErrorType
from src.services.abuse import abuse_detector

router = APIRouter(tags=["Gateway"])


async def log_request(
    db_factory,
    request_id: str,
    tenant_id: str | None,
    api_key_id: str | None,
    route_id: str | None,
    method: str,
    path: str,
    query_string: str | None,
    client_ip: str | None,
    user_agent: str | None,
    status_code: int,
    latency_ms: int,
    cache_status: CacheStatus,
    error_type: ErrorType,
    upstream_latency_ms: int | None,
    upstream_status: int | None,
    response_size: int | None,
) -> None:
    """Background task to log request metrics."""
    from src.database import get_db_context

    async with get_db_context() as db:
        log_entry = RequestLog(
            request_id=request_id,
            timestamp=datetime.now(timezone.utc),
            tenant_id=tenant_id,
            api_key_id=api_key_id,
            route_id=route_id,
            method=method,
            path=path,
            query_string=query_string,
            client_ip=client_ip,
            user_agent=user_agent,
            status_code=status_code,
            latency_ms=latency_ms,
            cache_status=cache_status,
            error_type=error_type,
            upstream_latency_ms=upstream_latency_ms,
            upstream_status_code=upstream_status,
            response_size_bytes=response_size,
        )
        db.add(log_entry)


@router.api_route(
    "/g/{route_name}/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def gateway_proxy_handler(
    request: Request,
    route_name: str,
    path: str = "",
    db: AsyncSession = Depends(get_db),
) -> Response:
    """
    Main gateway proxy endpoint.
    
    Proxies requests to upstream services based on route configuration.
    
    Path: /g/{route_name}/{path}
    - route_name: The configured route name
    - path: The path to forward to upstream
    
    Headers:
    - X-API-Key: Required for authentication
    
    Features:
    - Response caching with TTL
    - Stale-while-revalidate
    - Rate limiting
    - Quota enforcement
    - Abuse detection
    """
    start_time = time.perf_counter()
    request_id = getattr(request.state, "request_id", "unknown")

    # Get client info
    client_ip = _get_client_ip(request)
    user_agent = request.headers.get("User-Agent")
    query_string = str(request.query_params) if request.query_params else None

    # Create router and process request
    router_instance = GatewayRouter(db)
    api_key_header = request.headers.get("X-API-Key")

    context = await router_instance.process_request(
        route_name=route_name,
        path=f"/{path}" if path else "/",
        method=request.method,
        api_key_header=api_key_header,
    )

    # Handle authentication errors
    if not context.auth.authenticated:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        error_response = JSONResponse(
            status_code=401 if context.auth.error_code in ("missing_api_key", "invalid_api_key") else 403,
            content={
                "error": context.auth.error_code,
                "message": context.auth.error,
                "request_id": request_id,
            },
        )
        error_response.background = BackgroundTask(
            log_request,
            db_factory=None,
            request_id=request_id,
            tenant_id=None,
            api_key_id=None,
            route_id=None,
            method=request.method,
            path=f"/g/{route_name}/{path}",
            query_string=query_string,
            client_ip=client_ip,
            user_agent=user_agent,
            status_code=error_response.status_code,
            latency_ms=latency_ms,
            cache_status=CacheStatus.BYPASS,
            error_type=ErrorType.AUTH_FAILED,
            upstream_latency_ms=None,
            upstream_status=None,
            response_size=None,
        )
        return error_response

    tenant_id = context.auth.tenant.id if context.auth.tenant else None
    api_key_id = context.auth.api_key.id if context.auth.api_key else None

    # Handle route not found
    if not context.route_match.matched:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return JSONResponse(
            status_code=404,
            content={
                "error": "route_not_found",
                "message": context.route_match.error,
                "request_id": request_id,
            },
            background=BackgroundTask(
                log_request,
                db_factory=None,
                request_id=request_id,
                tenant_id=tenant_id,
                api_key_id=api_key_id,
                route_id=None,
                method=request.method,
                path=f"/g/{route_name}/{path}",
                query_string=query_string,
                client_ip=client_ip,
                user_agent=user_agent,
                status_code=404,
                latency_ms=latency_ms,
                cache_status=CacheStatus.BYPASS,
                error_type=ErrorType.VALIDATION_ERROR,
                upstream_latency_ms=None,
                upstream_status=None,
                response_size=None,
            ),
        )

    route_id = context.route_match.route.id

    # Handle abuse block
    if context.abuse_check and context.abuse_check.is_blocked:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return JSONResponse(
            status_code=429,
            content={
                "error": "blocked",
                "message": f"Temporarily blocked: {context.abuse_check.reason}",
                "retry_after": int(context.abuse_check.block_until - time.time()) if context.abuse_check.block_until else 300,
                "request_id": request_id,
            },
            headers={"Retry-After": str(int(context.abuse_check.block_until - time.time()) if context.abuse_check.block_until else 300)},
            background=BackgroundTask(
                log_request,
                db_factory=None,
                request_id=request_id,
                tenant_id=tenant_id,
                api_key_id=api_key_id,
                route_id=route_id,
                method=request.method,
                path=f"/g/{route_name}/{path}",
                query_string=query_string,
                client_ip=client_ip,
                user_agent=user_agent,
                status_code=429,
                latency_ms=latency_ms,
                cache_status=CacheStatus.BYPASS,
                error_type=ErrorType.BLOCKED,
                upstream_latency_ms=None,
                upstream_status=None,
                response_size=None,
            ),
        )

    # Handle rate limiting
    if context.rate_limit and not context.rate_limit.allowed:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return JSONResponse(
            status_code=429,
            content={
                "error": "rate_limited",
                "message": "Rate limit exceeded",
                "retry_after": context.rate_limit.retry_after,
                "limit": context.rate_limit.limit,
                "remaining": context.rate_limit.remaining,
                "request_id": request_id,
            },
            headers={
                "Retry-After": str(int(context.rate_limit.retry_after or 1)),
                "X-RateLimit-Limit": str(context.rate_limit.limit),
                "X-RateLimit-Remaining": str(context.rate_limit.remaining),
                "X-RateLimit-Reset": str(int(context.rate_limit.reset_after_seconds)),
            },
            background=BackgroundTask(
                log_request,
                db_factory=None,
                request_id=request_id,
                tenant_id=tenant_id,
                api_key_id=api_key_id,
                route_id=route_id,
                method=request.method,
                path=f"/g/{route_name}/{path}",
                query_string=query_string,
                client_ip=client_ip,
                user_agent=user_agent,
                status_code=429,
                latency_ms=latency_ms,
                cache_status=CacheStatus.BYPASS,
                error_type=ErrorType.RATE_LIMITED,
                upstream_latency_ms=None,
                upstream_status=None,
                response_size=None,
            ),
        )

    # Handle quota exceeded
    if not context.quota_allowed:
        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return JSONResponse(
            status_code=429,
            content={
                "error": "quota_exceeded",
                "message": f"Quota exceeded: {context.quota_error}",
                "request_id": request_id,
            },
            background=BackgroundTask(
                log_request,
                db_factory=None,
                request_id=request_id,
                tenant_id=tenant_id,
                api_key_id=api_key_id,
                route_id=route_id,
                method=request.method,
                path=f"/g/{route_name}/{path}",
                query_string=query_string,
                client_ip=client_ip,
                user_agent=user_agent,
                status_code=429,
                latency_ms=latency_ms,
                cache_status=CacheStatus.BYPASS,
                error_type=ErrorType.QUOTA_EXCEEDED,
                upstream_latency_ms=None,
                upstream_status=None,
                response_size=None,
            ),
        )

    # Proxy the request
    proxy_result = await gateway_proxy.proxy_request(
        request=request,
        context=context,
        path=f"/{path}" if path else "/",
    )

    latency_ms = int((time.perf_counter() - start_time) * 1000)

    # Set cache status in request state for logging middleware
    request.state.cache_status = proxy_result.cache_status.value

    # Add rate limit headers to response
    if context.rate_limit:
        proxy_result.response.headers["X-RateLimit-Limit"] = str(context.rate_limit.limit)
        proxy_result.response.headers["X-RateLimit-Remaining"] = str(context.rate_limit.remaining)
        proxy_result.response.headers["X-RateLimit-Reset"] = str(int(context.rate_limit.reset_after_seconds))

    # Add request ID
    proxy_result.response.headers["X-Request-Id"] = request_id

    # Record abuse metrics
    is_error = proxy_result.error_type != ErrorType.NONE or proxy_result.response.status_code >= 400
    await abuse_detector.record_request(
        api_key_id=api_key_id,
        is_error=is_error,
        error_type=proxy_result.error_type.value if is_error else None,
    )

    # Log request in background
    proxy_result.response.background = BackgroundTask(
        log_request,
        db_factory=None,
        request_id=request_id,
        tenant_id=tenant_id,
        api_key_id=api_key_id,
        route_id=route_id,
        method=request.method,
        path=f"/g/{route_name}/{path}",
        query_string=query_string,
        client_ip=client_ip,
        user_agent=user_agent,
        status_code=proxy_result.response.status_code,
        latency_ms=latency_ms,
        cache_status=proxy_result.cache_status,
        error_type=proxy_result.error_type,
        upstream_latency_ms=proxy_result.upstream_latency_ms,
        upstream_status=proxy_result.upstream_status,
        response_size=len(proxy_result.response.body) if hasattr(proxy_result.response, "body") else None,
    )

    return proxy_result.response


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    if request.client:
        return request.client.host

    return "unknown"
