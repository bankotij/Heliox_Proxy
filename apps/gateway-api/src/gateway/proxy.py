"""Gateway proxy - handles upstream requests with caching and coalescing."""

import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode

import httpx
import structlog
from starlette.requests import Request
from starlette.responses import Response

from src.gateway.router import GatewayContext
from src.models import CachePolicy, Route
from src.models.request_log import CacheStatus, ErrorType
from src.services.bloom import negative_cache
from src.services.cache import (
    CacheEntry,
    CacheEntryStatus,
    CacheKeyBuilder,
    cache_metrics,
    cache_service,
)

logger = structlog.get_logger(__name__)


@dataclass
class ProxyResult:
    """Result of proxying a request."""

    response: Response
    cache_status: CacheStatus
    error_type: ErrorType
    upstream_latency_ms: int | None = None
    upstream_status: int | None = None


class GatewayProxy:
    """
    Handles upstream proxying with caching, SWR, and coalescing.
    
    Features:
    - Response caching with configurable TTL
    - Stale-while-revalidate for improved latency
    - Stampede protection (one fetch per key)
    - Request coalescing (waiters share result)
    - Negative caching via bloom filter
    """

    def __init__(self, timeout_ms: int = 30000) -> None:
        self._default_timeout = timeout_ms / 1000  # Convert to seconds
        self._client: httpx.AsyncClient | None = None

    async def get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                follow_redirects=True,
                timeout=httpx.Timeout(self._default_timeout),
            )
        return self._client

    async def close(self) -> None:
        """Close HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def proxy_request(
        self,
        request: Request,
        context: GatewayContext,
        path: str,
    ) -> ProxyResult:
        """
        Proxy a request to upstream with caching.
        
        Args:
            request: Original incoming request
            context: Gateway context with auth and route info
            path: Path to forward to upstream
        
        Returns:
            ProxyResult with response and metadata
        """
        route = context.route_match.route
        policy = context.route_match.policy

        # Build cache key
        cache_key = await self._build_cache_key(request, context, path)

        # Check bloom filter for likely 404s
        if await self._check_bloom_filter(route.name, path):
            cache_metrics.record_hit()
            return ProxyResult(
                response=Response(
                    content=b'{"error": "Not Found"}',
                    status_code=404,
                    media_type="application/json",
                ),
                cache_status=CacheStatus.HIT,
                error_type=ErrorType.NONE,
            )

        # Check if caching is disabled
        if policy and policy.cache_no_store:
            return await self._fetch_upstream(request, context, path, cache_key)

        # Try to get from cache with SWR support
        try:
            entry, status = await cache_service.get_or_fetch(
                cache_key=cache_key,
                fetch_fn=lambda: self._fetch_and_build_entry(request, context, path, policy),
                ttl_seconds=policy.ttl_seconds if policy else 300,
                stale_seconds=policy.stale_seconds if policy else 60,
            )

            # Update metrics
            if status == CacheEntryStatus.FRESH:
                cache_metrics.record_hit()
                cache_status = CacheStatus.HIT
            elif status == CacheEntryStatus.STALE:
                cache_metrics.record_stale()
                cache_status = CacheStatus.STALE
            else:
                cache_metrics.record_miss()
                cache_status = CacheStatus.MISS

            # Build response from cache entry
            response = self._build_response(entry)

            return ProxyResult(
                response=response,
                cache_status=cache_status,
                error_type=ErrorType.NONE,
                upstream_status=entry.status_code,
            )

        except Exception as e:
            logger.error("Cache fetch failed", error=str(e), cache_key=cache_key)
            cache_metrics.record_error()
            return await self._fetch_upstream(request, context, path, cache_key)

    async def _build_cache_key(
        self,
        request: Request,
        context: GatewayContext,
        path: str,
    ) -> str:
        """Build canonical cache key."""
        policy = context.route_match.policy
        route = context.route_match.route

        # Parse query params
        query_params = dict(parse_qs(str(request.query_params)))

        # Get vary headers
        vary_headers = {}
        if policy and policy.vary_headers:
            for header in policy.vary_headers:
                value = request.headers.get(header)
                if value:
                    vary_headers[header.lower()] = value

        return CacheKeyBuilder.build(
            method=request.method,
            route_name=route.name,
            path=path,
            query_params=query_params,
            vary_headers=vary_headers,
            tenant_id=context.auth.tenant.id if context.auth.tenant else None,
        )

    async def _check_bloom_filter(self, route_name: str, path: str) -> bool:
        """Check if path is likely a 404 via bloom filter."""
        try:
            return await negative_cache.is_likely_404(route_name, path)
        except Exception as e:
            logger.warning("Bloom filter check failed", error=str(e))
            return False

    async def _fetch_upstream(
        self,
        request: Request,
        context: GatewayContext,
        path: str,
        cache_key: str | None = None,
    ) -> ProxyResult:
        """Fetch directly from upstream without caching."""
        route = context.route_match.route

        try:
            start = time.perf_counter()
            upstream_response = await self._make_upstream_request(request, route, path)
            latency_ms = int((time.perf_counter() - start) * 1000)

            response = Response(
                content=upstream_response.content,
                status_code=upstream_response.status_code,
                headers=dict(upstream_response.headers),
            )

            return ProxyResult(
                response=response,
                cache_status=CacheStatus.BYPASS,
                error_type=ErrorType.NONE,
                upstream_latency_ms=latency_ms,
                upstream_status=upstream_response.status_code,
            )

        except httpx.TimeoutException:
            return ProxyResult(
                response=Response(
                    content=b'{"error": "Upstream timeout"}',
                    status_code=504,
                    media_type="application/json",
                ),
                cache_status=CacheStatus.BYPASS,
                error_type=ErrorType.UPSTREAM_TIMEOUT,
            )
        except httpx.RequestError as e:
            logger.error("Upstream request failed", error=str(e))
            return ProxyResult(
                response=Response(
                    content=b'{"error": "Upstream error"}',
                    status_code=502,
                    media_type="application/json",
                ),
                cache_status=CacheStatus.BYPASS,
                error_type=ErrorType.UPSTREAM_ERROR,
            )

    async def _fetch_and_build_entry(
        self,
        request: Request,
        context: GatewayContext,
        path: str,
        policy: CachePolicy | None,
    ) -> CacheEntry:
        """Fetch from upstream and build cache entry."""
        route = context.route_match.route

        start = time.perf_counter()
        response = await self._make_upstream_request(request, route, path)
        latency_ms = int((time.perf_counter() - start) * 1000)

        # Check if response is cacheable
        if policy:
            if not policy.is_cacheable_status(response.status_code):
                raise ValueError(f"Status {response.status_code} not cacheable")
            if len(response.content) > policy.max_body_bytes:
                raise ValueError("Response too large to cache")

        # Record 404s in bloom filter
        if response.status_code == 404:
            await negative_cache.record_404(route.name, path)

        # Build vary key
        vary_key = ""
        if policy and policy.vary_headers:
            vary_parts = []
            for header in policy.vary_headers:
                value = request.headers.get(header, "")
                vary_parts.append(f"{header}:{value}")
            vary_key = "|".join(vary_parts)

        return CacheEntry(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=response.content,
            created_at=time.time(),
            ttl_seconds=policy.ttl_seconds if policy else 300,
            stale_seconds=policy.stale_seconds if policy else 60,
            vary_key=vary_key,
        )

    async def _make_upstream_request(
        self,
        request: Request,
        route: Route,
        path: str,
    ) -> httpx.Response:
        """Make the actual upstream HTTP request."""
        client = await self.get_client()

        # Build upstream URL
        upstream_url = route.get_upstream_url(path)

        # Add query string if present
        if request.query_params:
            upstream_url = f"{upstream_url}?{request.query_params}"

        # Build headers
        headers = dict(request.headers)

        # Remove hop-by-hop headers
        hop_by_hop = [
            "connection", "keep-alive", "proxy-authenticate",
            "proxy-authorization", "te", "trailers", "transfer-encoding",
            "upgrade", "host",
        ]
        for header in hop_by_hop:
            headers.pop(header, None)

        # Apply route header transformations
        if route.request_headers_remove:
            for header in route.request_headers_remove:
                headers.pop(header.lower(), None)

        if route.request_headers_add:
            headers.update(route.request_headers_add)

        # Get request body
        body = await request.body() if request.method in ("POST", "PUT", "PATCH") else None

        # Configure timeout
        timeout = route.timeout_ms / 1000

        # Make request
        response = await client.request(
            method=request.method,
            url=upstream_url,
            headers=headers,
            content=body,
            timeout=timeout,
        )

        return response

    def _build_response(self, entry: CacheEntry) -> Response:
        """Build Starlette response from cache entry."""
        headers = dict(entry.headers)

        # Remove hop-by-hop headers
        hop_by_hop = [
            "connection", "keep-alive", "transfer-encoding",
            "content-encoding", "content-length",
        ]
        for header in hop_by_hop:
            headers.pop(header, None)
            headers.pop(header.title(), None)

        # Add cache headers
        headers["X-Cache"] = "HIT" if entry.get_status() == CacheEntryStatus.FRESH else "STALE"
        headers["Age"] = str(int(entry.age_seconds))

        return Response(
            content=entry.body,
            status_code=entry.status_code,
            headers=headers,
        )


# Global proxy instance
gateway_proxy = GatewayProxy()


async def get_gateway_proxy() -> GatewayProxy:
    """Dependency to get gateway proxy."""
    return gateway_proxy
